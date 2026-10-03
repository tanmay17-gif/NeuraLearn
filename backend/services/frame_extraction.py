import os
import asyncio
import tempfile
import uuid
import shutil
import subprocess
from dataclasses import dataclass
from typing import Dict, Optional

# Semaphore for ffmpeg processes
ffmpeg_semaphore = asyncio.Semaphore(int(os.getenv("FFMPEG_CONCURRENCY", "3")))


@dataclass(frozen=True)
class ResolvedVideoStream:
    url: str
    http_headers: Dict[str, str]
    duration: Optional[float]


def get_ffmpeg_executable() -> str:
    """Use system FFmpeg when installed, otherwise use the bundled binary."""
    executable = shutil.which("ffmpeg")
    if executable:
        return executable

    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError as error:
        raise RuntimeError(
            "FFmpeg is unavailable. Install the backend requirements to enable "
            "timestamp-based video frame extraction."
        ) from error


def _timestamp_to_seconds(timestamp: str) -> float:
    parts = timestamp.split(":")
    if len(parts) == 1:
        return float(parts[0])
    if len(parts) == 2:
        minutes, seconds = parts
        return int(minutes) * 60 + float(seconds)
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    raise ValueError(f"Invalid timestamp: {timestamp}")


async def resolve_youtube_stream_url(video_url_or_id: str) -> ResolvedVideoStream:
    """Resolve an available YouTube video stream without requiring Redis or a fixed format."""
    import yt_dlp

    video_url = video_url_or_id
    if not video_url.startswith(("http://", "https://")):
        video_url = f"https://www.youtube.com/watch?v={video_url}"

    def resolve() -> str:
        options = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "skip_download": True,
        }
        with yt_dlp.YoutubeDL(options) as youtube_dl:
            info = youtube_dl.extract_info(
                video_url,
                download=False,
                process=True,
            )

        formats = [
            format_info
            for format_info in info.get("formats", [])
            if format_info.get("url")
            and format_info.get("vcodec") not in (None, "none")
            and format_info.get("protocol") != "mhtml"
        ]
        if not formats:
            raise RuntimeError("yt-dlp returned no playable video-only formats.")

        within_resolution_limit = [
            format_info
            for format_info in formats
            if format_info.get("height") is not None
            and format_info["height"] <= 720
        ]
        if within_resolution_limit:
            progressive_formats = [
                format_info
                for format_info in within_resolution_limit
                if format_info.get("protocol")
                not in {"m3u8", "m3u8_native", "http_dash_segments", "dash"}
            ]
            candidates = progressive_formats or within_resolution_limit
            selected_format = max(
                candidates,
                key=lambda item: (
                    item.get("height", 0),
                    item.get("vcodec", "").startswith("avc1"),
                    item.get("tbr", 0) or 0,
                ),
            )
        else:
            unknown_resolution = [
                format_info
                for format_info in formats
                if format_info.get("height") is None
            ]
            candidates = unknown_resolution or formats
            progressive_formats = [
                format_info
                for format_info in candidates
                if format_info.get("protocol")
                not in {"m3u8", "m3u8_native", "http_dash_segments", "dash"}
            ]
            candidates = progressive_formats or candidates
            selected_format = (
                max(
                    candidates,
                    key=lambda item: item.get("tbr", 0) or 0,
                )
                if unknown_resolution
                else min(
                    candidates,
                    key=lambda item: (
                        item.get("height", float("inf")),
                        not item.get("vcodec", "").startswith("avc1"),
                    ),
                )
            )

        headers = selected_format.get("http_headers") or info.get("http_headers") or {}
        return ResolvedVideoStream(
            url=selected_format["url"],
            http_headers={
                str(name): str(value)
                for name, value in headers.items()
            },
            duration=selected_format.get("duration") or info.get("duration"),
        )

    return await asyncio.to_thread(resolve)


async def extract_frame_at_timestamp(
    video_path_or_url: str, 
    timestamp_sec: str, 
    is_remote: bool = False,
    http_headers: Optional[Dict[str, str]] = None,
) -> str:
    """
    Extracts a frame from a video at a specific timestamp.
    Returns the path to the temporary image file. The caller is responsible for cleanup.
    """
    ffmpeg_executable = get_ffmpeg_executable()
    temp_dir = tempfile.mkdtemp(prefix="frame_ext_")
    output_path = os.path.join(temp_dir, f"frame_{uuid.uuid4().hex}.jpg")

    async with ffmpeg_semaphore:
        input_options = []
        if is_remote and http_headers:
            header_block = "".join(
                f"{name}: {value}\r\n"
                for name, value in http_headers.items()
            )
            input_options.extend(["-headers", header_block])

        if is_remote:
            try:
                ts_float = _timestamp_to_seconds(timestamp_sec)
                coarse = max(0.0, ts_float - 2.0)
                fine = ts_float - coarse
                
                cmd = [
                    ffmpeg_executable, "-y",
                    "-ss", str(coarse),
                    *input_options,
                    "-i", video_path_or_url,
                    "-ss", str(fine),
                    "-vframes", "1",
                    "-q:v", "2",
                    output_path
                ]
            except ValueError:
                # If parsing fails (e.g. HH:MM:SS string), just use the string directly
                cmd = [
                    ffmpeg_executable, "-y",
                    "-ss", timestamp_sec,
                    *input_options,
                    "-i", video_path_or_url,
                    "-vframes", "1",
                    "-q:v", "2",
                    output_path
                ]
        else:
            # Local file, fast seek
            cmd = [
                ffmpeg_executable, "-y",
                "-ss", timestamp_sec,
                "-i", video_path_or_url,
                "-vframes", "1",
                "-q:v", "2",
                output_path
            ]
            
        try:
            process = await asyncio.to_thread(
                subprocess.run,
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=15.0,
                check=False,
            )
            if process.returncode != 0:
                err_text = process.stderr.decode("utf-8", errors="replace")
                raise RuntimeError(f"ffmpeg frame extraction failed: {err_text}")

            if not os.path.exists(output_path):
                raise RuntimeError("ffmpeg completed but frame was not created")

            return output_path
        except subprocess.TimeoutExpired as error:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise RuntimeError("ffmpeg frame extraction timed out") from error
        except Exception:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise
