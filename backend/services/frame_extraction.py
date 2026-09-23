import os
import asyncio
import tempfile
import base64
import uuid
import shutil
from typing import Optional

# Semaphore for ffmpeg processes
ffmpeg_semaphore = asyncio.Semaphore(int(os.getenv("FFMPEG_CONCURRENCY", "3")))

async def extract_frame_at_timestamp(
    video_path_or_url: str, 
    timestamp_sec: str, 
    is_remote: bool = False
) -> str:
    """
    Extracts a frame from a video at a specific timestamp.
    Returns the path to the temporary image file. The caller is responsible for cleanup.
    """
    temp_dir = tempfile.mkdtemp(prefix="frame_ext_")
    output_path = os.path.join(temp_dir, f"frame_{uuid.uuid4().hex}.jpg")
    
    async with ffmpeg_semaphore:
        if is_remote:
            # Coarse input-seek before -i and fine output-seek after
            # To do this correctly, we parse timestamp_sec to a float, do coarse seek 2s before, and fine seek the rest
            try:
                ts_float = float(timestamp_sec)
                coarse = max(0.0, ts_float - 2.0)
                fine = ts_float - coarse
                
                cmd = [
                    "ffmpeg", "-y",
                    "-ss", str(coarse),
                    "-i", video_path_or_url,
                    "-ss", str(fine),
                    "-vframes", "1",
                    "-q:v", "2",
                    output_path
                ]
            except ValueError:
                # If parsing fails (e.g. HH:MM:SS string), just use the string directly
                cmd = [
                    "ffmpeg", "-y",
                    "-ss", timestamp_sec,
                    "-i", video_path_or_url,
                    "-vframes", "1",
                    "-q:v", "2",
                    output_path
                ]
        else:
            # Local file, fast seek
            cmd = [
                "ffmpeg", "-y",
                "-ss", timestamp_sec,
                "-i", video_path_or_url,
                "-vframes", "1",
                "-q:v", "2",
                output_path
            ]
            
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=15.0)
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise Exception("ffmpeg frame extraction timed out")
            
        if process.returncode != 0:
            err_text = stderr.decode('utf-8', errors='replace')
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise Exception(f"ffmpeg frame extraction failed: {err_text}")
            
        if not os.path.exists(output_path):
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise Exception("ffmpeg completed but frame was not created")
            
        return output_path
