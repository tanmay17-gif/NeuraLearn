import os
import re
import base64
import tempfile
import requests
import yt_dlp
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


async def get_transcript(url: str) -> Dict[str, Any]:
    """
    Fetches transcript using youtube-transcript-api (instance-based).
    Uses COOKIES_BASE64 env var (cloud) or local cookies.txt (dev), 
    then falls back to yt-dlp.
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
            if "bot" in err_lower or "429" in err_lower or "blocking" in err_lower or isinstance(e, CouldNotRetrieveTranscript):
                raise Exception(
                    "YouTube is blocking automated requests from this server. "
                    "Add your COOKIES_BASE64 to Render environment variables to fix this."
                )
            raise e

    except (TranscriptsDisabled, NoTranscriptFound):
        raise Exception("This video has no captions available. Try a different video.")
    except Exception as e:
        if "YouTube is blocking" in str(e) or "COOKIES_BASE64" in str(e):
            raise e
        raise Exception(f"Could not get transcript: {str(e)[:200]}")
