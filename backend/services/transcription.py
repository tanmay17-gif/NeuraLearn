import os
import re
import base64
import tempfile
import asyncio
import requests
import yt_dlp
import google.genai as genai
from google.genai import types as genai_types
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled, 
    NoTranscriptFound,
    CouldNotRetrieveTranscript
)
from typing import Dict, Any, Optional
from http.cookiejar import MozillaCookieJar


def _get_cookies_path() -> Optional[str]:
    """
    Resolve cookies.txt path. Checks:
    1. COOKIES_BASE64 env var (for Render/cloud deployment)
    2. Local cookies.txt file (for local dev)
    """
    # 1. Check for base64-encoded cookies from environment variable
    cookies_b64 = os.getenv("COOKIES_BASE64", "").strip()
    if cookies_b64:
        try:
            cookies_data = base64.b64decode(cookies_b64).decode("utf-8")
            # Write to a temp file that persists for this process lifetime
            tmp = tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False, prefix="yt_cookies_"
            )
            tmp.write(cookies_data)
            tmp.close()
            print(f"[transcription] Loaded cookies from COOKIES_BASE64 env var → {tmp.name}")
            return tmp.name
        except Exception as e:
            print(f"[transcription] Failed to decode COOKIES_BASE64: {e}")

    # 2. Check local file paths
    possible_paths = [
        os.path.join(os.getcwd(), "cookies.txt"),
        os.path.join(os.getcwd(), "backend", "cookies.txt"),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "cookies.txt")),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "cookies.txt")),
    ]
    for path in possible_paths:
        if os.path.exists(path):
            print(f"[transcription] Using local cookies.txt: {path}")
            return path

    return None


def _extract_video_id(url: str) -> str:
    """Extracts video ID from any YouTube URL including Shorts."""
    url = url.strip()
    if "youtu.be/" in url:
        return url.split("youtu.be/")[1].split("?")[0]
    if "/shorts/" in url:
        return url.split("/shorts/")[1].split("?")[0]
    if "v=" in url:
        return url.split("v=")[1].split("&")[0]
    return url


async def get_transcript_yt_dlp(video_id: str, cookies_path: str = None) -> str:
    """Fallback method using yt-dlp to extract subtitles/transcripts."""
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    ydl_opts = {
        'skip_download': True,
        'writesubtitles': True,
        'writeautomaticsub': True,
        'subtitleslangs': ['en.*', 'en'],
        'quiet': True,
        'no_warnings': True,
    }

    if cookies_path and os.path.exists(cookies_path):
        ydl_opts['cookiefile'] = cookies_path
    else:
        # Only try browser cookies in local dev (not on cloud servers)
        if os.getenv("RENDER") is None:
            try:
                ydl_opts['cookiesfrombrowser'] = ('chrome',)
            except Exception:
                pass

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            subtitles = info.get('subtitles', {}) or info.get('automatic_captions', {})
            en_subs = None
            for lang in ['en', 'en-US', 'en-GB']:
                if lang in subtitles:
                    en_subs = subtitles[lang]
                    break

            if not en_subs and subtitles:
                for lang in subtitles:
                    if lang.startswith('en'):
                        en_subs = subtitles[lang]
                        break

            if en_subs:
                sub_url = None
                for fmt in en_subs:
                    if fmt.get('ext') == 'json3':
                        sub_url = fmt['url']
                        break
                if not sub_url and en_subs:
                    sub_url = en_subs[0]['url']

                if sub_url:
                    resp = requests.get(sub_url)
                    if resp.status_code == 200:
                        text = resp.text
                        if sub_url.endswith('.json3') or 'json3' in sub_url:
                            try:
                                import json
                                data = json.loads(text)
                                return " ".join([
                                    event.get('segs', [{}])[0].get('utf8', '')
                                    for event in data.get('events', [])
                                    if 'segs' in event
                                ])
                            except Exception:
                                pass
                        text = re.sub(r'<[^>]+>', '', text)
                        text = re.sub(r'\d{2}:\d{2}:\d{2}\.\d{3} --> \d{2}:\d{2}:\d{2}\.\d{3}', '', text)
                        return text.strip()
        return None
    except Exception as e:
        print(f"[transcription] yt-dlp fallback error: {e}")
        return None


async def get_transcript_via_gemini(url: str) -> Optional[str]:
    """
    Ultimate fallback: use Gemini's native YouTube understanding.
    Gemini 1.5 Flash can directly process YouTube URLs — no cookies needed.
    Works for all users regardless of server IP blocking.
    """
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return None
    try:
        print(f"[transcription] Trying Gemini native YouTube processing for {url}")
        client = genai.Client(api_key=api_key)
        
        def _call():
            return client.models.generate_content(
                model="gemini-3.5-flash",
                contents=[
                    genai_types.Part(
                        file_data=genai_types.FileData(file_uri=url)
                    ),
                    """Provide a complete, verbatim transcript of all spoken words in this video.
                    Include everything that is said. Do not summarize. Do not skip any parts.
                    Format as plain text without timestamps."""
                ]
            )
        
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, _call)
        text = response.text.strip()
        if text and len(text) > 100:
            print(f"[transcription] Gemini YouTube fallback succeeded ({len(text)} chars)")
            return text
        return None
    except Exception as e:
        print(f"[transcription] Gemini YouTube fallback error: {e}")
        return None



async def get_transcript(url: str) -> Dict[str, Any]:
    """
    Fetches transcript using youtube-transcript-api (instance-based).
    Uses COOKIES_BASE64 env var (cloud) or local cookies.txt (dev), 
    then falls back to yt-dlp, then falls back to Gemini native processing.
    """
    video_id = _extract_video_id(url)
    cookies_path = _get_cookies_path()

    # Setup session with cookies if available
    session = requests.Session()
    if cookies_path:
        try:
            cj = MozillaCookieJar(cookies_path)
            cj.load(ignore_discard=True, ignore_expires=True)
            session.cookies = cj
        except Exception as e:
            print(f"[transcription] Error loading cookies: {e}")

    try:
        # 1. Try YouTubeTranscriptApi
        try:
            api = YouTubeTranscriptApi(http_client=session)
            transcript_list = api.list(video_id)

            try:
                transcript = transcript_list.find_transcript(['en', 'en-US', 'en-GB'])
            except Exception:
                transcript = next(iter(transcript_list))

            fetched = transcript.fetch()
            full_text = " ".join([
                t.text if hasattr(t, 'text') else t['text'] for t in fetched
            ])

            return {
                "video_id": video_id,
                "title": f"Video {video_id}",
                "text": full_text
            }

        except (TranscriptsDisabled, NoTranscriptFound) as e:
            raise e

        except Exception as e:
            # 2. Fallback to yt-dlp
            print(f"[transcription] youtube-transcript-api failed ({e}), trying yt-dlp...")
            yt_dlp_text = await get_transcript_yt_dlp(video_id, cookies_path)
            if yt_dlp_text:
                return {
                    "video_id": video_id,
                    "title": f"Video {video_id} (yt-dlp)",
                    "text": yt_dlp_text
                }

            err_lower = str(e).lower()
            is_blocked = "bot" in err_lower or "429" in err_lower or "blocking" in err_lower or isinstance(e, CouldNotRetrieveTranscript)
            
            # 3. Ultimate fallback — Gemini native YouTube processing (works for all users!)
            print(f"[transcription] Both primary methods failed, trying Gemini native fallback...")
            gemini_text = await get_transcript_via_gemini(url)
            if gemini_text:
                return {
                    "video_id": video_id,
                    "title": f"Video {video_id} (Gemini)",
                    "text": gemini_text
                }
            
            if is_blocked:
                raise Exception(
                    "YouTube is blocking automated requests from this server. "
                    "Please use the 'Manual Transcript' option or try again later."
                )
            raise e


    except (TranscriptsDisabled, NoTranscriptFound):
        raise Exception("This video has no captions available. Try a different video.")
    except Exception as e:
        if "YouTube is blocking" in str(e) or "COOKIES_BASE64" in str(e):
            raise e
        raise Exception(f"Could not get transcript: {str(e)[:200]}")


import math
import shutil
import uuid
import subprocess
from groq import AsyncGroq
# Isolated semaphore for audio (can reuse the vision one or make a new one, but they share Groq)
from services.vision_client import vision_groq_semaphore
# Semaphore for ffmpeg processes (reusing the one from frame_extraction)
from services.frame_extraction import ffmpeg_semaphore

async def check_local_subtitles(file_path: str) -> Optional[str]:
    """Check if local video has embedded subtitles using ffprobe."""
    try:
        cmd = [
            "ffprobe", "-v", "error", 
            "-select_streams", "s", 
            "-show_entries", "stream=index:tags=language", 
            "-of", "csv=p=0", file_path
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await process.communicate()
        if stdout.strip():
            # Extract subtitles using ffmpeg if present
            temp_sub = tempfile.mktemp(suffix=".srt")
            extract_cmd = ["ffmpeg", "-y", "-i", file_path, "-map", "0:s:0", temp_sub]
            ext_proc = await asyncio.create_subprocess_exec(
                *extract_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            await ext_proc.communicate()
            if os.path.exists(temp_sub):
                with open(temp_sub, "r", encoding="utf-8") as f:
                    content = f.read()
                os.remove(temp_sub)
                import re
                text = re.sub(r'<[^>]+>', '', content)
                text = re.sub(r'\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}', '', text)
                text = re.sub(r'^\d+$', '', text, flags=re.MULTILINE)
                return text.strip()
    except Exception:
        pass
    return None

async def extract_audio_chunk(input_path: str, output_path: str, start_sec: float, duration_sec: float):
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start_sec),
        "-t", str(duration_sec),
        "-i", input_path,
        "-vn", "-acodec", "libmp3lame", "-q:a", "2",
        output_path
    ]
    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise Exception(f"Failed to extract chunk: {stderr.decode('utf-8', errors='replace')}")

async def transcribe_audio_chunk(audio_path: str) -> str:
    async with vision_groq_semaphore:
        client = AsyncGroq(api_key=os.environ.get("GROQ_API_KEY"))
        try:
            with open(audio_path, "rb") as f:
                transcription = await asyncio.wait_for(client.audio.transcriptions.create(
                    file=(os.path.basename(audio_path), f.read()),
                    model="whisper-large-v3-turbo",
                    response_format="text"
                ), timeout=60.0)
            return transcription if isinstance(transcription, str) else transcription.text
        except Exception as e:
            print(f"Chunk transcription failed: {e}")
            return "[transcription gap]"

async def get_local_video_transcript(file_path: str) -> str:
    """Extract audio and transcribe local video using Whisper."""
    existing = await check_local_subtitles(file_path)
    if existing:
        return existing
        
    temp_dir = tempfile.mkdtemp(prefix="audio_ext_")
    audio_path = os.path.join(temp_dir, "audio.mp3")
    
    try:
        async with ffmpeg_semaphore:
            cmd = [
                "ffmpeg", "-y", "-i", file_path, 
                "-vn", "-acodec", "libmp3lame", "-q:a", "2", 
                audio_path
            ]
            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            if process.returncode != 0:
                raise Exception(f"Audio extraction failed: {stderr.decode('utf-8', errors='replace')}")
                
        file_size = os.path.getsize(audio_path)
        max_size = 25 * 1024 * 1024
        
        if file_size <= max_size:
            transcript = await transcribe_audio_chunk(audio_path)
            return transcript
            
        # Needs chunking
        target_bitrate_bps = 256000 # 256kbps conservative
        chunk_seconds = (max_size * 8 * 0.85) / target_bitrate_bps
        
        probe_cmd = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", audio_path
        ]
        probe_proc = await asyncio.create_subprocess_exec(
            *probe_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        probe_out, _ = await probe_proc.communicate()
        try:
            total_duration = float(probe_out.strip())
        except ValueError:
            total_duration = file_size / (target_bitrate_bps / 8)
            
        chunks = []
        current_sec = 0.0
        overlap = 2.0
        chunk_idx = 0
        
        while current_sec < total_duration:
            chunk_out = os.path.join(temp_dir, f"chunk_{chunk_idx}.mp3")
            duration = min(chunk_seconds, total_duration - current_sec)
            if duration <= 0: break
            
            async with ffmpeg_semaphore:
                await extract_audio_chunk(audio_path, chunk_out, current_sec, duration)
                
            chunks.append(chunk_out)
            current_sec += (duration - overlap)
            chunk_idx += 1
            
        tasks = [transcribe_audio_chunk(c) for c in chunks]
        results = await asyncio.gather(*tasks)
        
        return " ".join(results)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
