import os
import re
import requests
import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled, 
    NoTranscriptFound,
    CouldNotRetrieveTranscript
)
from typing import Dict, Any
from http.cookiejar import MozillaCookieJar

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
        # Try to read from browser if on local machine (highly effective for dev)
        try:
            ydl_opts['cookiesfrombrowser'] = ('chrome', 'firefox', 'edge', 'brave', 'safari')
        except Exception: pass

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
                        if sub_url.endswith('.json3'):
                            try:
                                import json
                                data = json.loads(text)
                                return " ".join([event.get('segs', [{}])[0].get('utf8', '') for event in data.get('events', []) if 'segs' in event])
                            except: pass
                        text = re.sub(r'<[^>]+>', '', text)
                        text = re.sub(r'\d{2}:\d{2}:\d{2}\.\d{3} --> \d{2}:\d{2}:\d{2}\.\d{3}', '', text)
                        return text.strip()
            return None
    except Exception as e:
        print(f"yt-dlp fallback error: {e}")
        return None

async def get_transcript(url: str) -> Dict[str, Any]:
    """
    Fetches transcript using youtube-transcript-api (instance-based).
    Uses cookies.txt if found or falls back to yt-dlp.
    """
    video_id = _extract_video_id(url)
    
    # 1. Resolve cookies path
    possible_paths = [
        os.path.join(os.getcwd(), "cookies.txt"),
        os.path.join(os.getcwd(), "backend", "cookies.txt"),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "cookies.txt")),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "cookies.txt"))
    ]
    
    cookies_path = None
    for path in possible_paths:
        if os.path.exists(path):
            cookies_path = path
            break

    # 2. Setup session with cookies if available
    session = requests.Session()
    if cookies_path:
        try:
            cj = MozillaCookieJar(cookies_path)
            cj.load(ignore_discard=True, ignore_expires=True)
            session.cookies = cj
        except Exception as e:
            print(f"Error loading cookies.txt: {e}")

    try:
        # 3. Try YouTubeTranscriptApi (Instance Mode)
        try:
            api = YouTubeTranscriptApi(http_client=session)
            transcript_list = api.list(video_id)
            
            try:
                transcript = transcript_list.find_transcript(['en', 'en-US', 'en-GB'])
            except Exception:
                transcript = next(iter(transcript_list))
            
            fetched = transcript.fetch()
            full_text = " ".join([t.text if hasattr(t, 'text') else t['text'] for t in fetched])
            
            return {
                "video_id": video_id,
                "title": f"Video {video_id}",
                "text": full_text
            }
        except (TranscriptsDisabled, NoTranscriptFound) as e:
            raise e
        except Exception as e:
            # 4. Fallback to yt-dlp
            yt_dlp_text = await get_transcript_yt_dlp(video_id, cookies_path)
            if yt_dlp_text:
                return {
                    "video_id": video_id,
                    "title": f"Video {video_id} (yt-dlp fallback)",
                    "text": yt_dlp_text
                }
            
            # Detailed blocking message
            if "bot" in str(e).lower() or "429" in str(e) or "blocking" in str(e).lower() or isinstance(e, CouldNotRetrieveTranscript):
                raise Exception(
                    "YouTube is blocking automated requests. To fix:\n"
                    "1. Export your cookies using the 'Get cookies.txt LOCALLY' extension.\n"
                    "2. Save the file as 'cookies.txt' in the backend folder.\n"
                    "3. Alternatively, ensure your Chrome/Firefox browser is logged into YouTube."
                )
            raise e

    except (TranscriptsDisabled, NoTranscriptFound):
        raise Exception("This video has no captions available. Try a different video.")
    except Exception as e:
        if "YouTube is blocking" in str(e):
            raise e
        raise Exception(f"Could not get transcript: {str(e)[:150]}")


