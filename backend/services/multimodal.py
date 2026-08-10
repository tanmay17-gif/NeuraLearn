import os
import cv2
import base64
import yt_dlp
import google.genai as genai
from typing import List, Dict
from dotenv import load_dotenv
from services.profile import get_system_instructions

load_dotenv()

# Configure Gemini
api_key = os.getenv("GOOGLE_API_KEY")
client = None
if api_key:
    client = genai.Client(api_key=api_key)

async def extract_frames(video_url: str, interval_seconds: int = 60, max_frames: int = 10) -> List[str]:
    """
    Extracts key frames from a YouTube video URL using yt-dlp and OpenCV.
    Returns a list of base64 encoded strings.
    """
    ydl_opts = {
        'format': 'best[height<=480]', # Low res for faster processing
        'quiet': True,
        'no_warnings': True,
    }
    
    frames_b64 = []
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            stream_url = info['url']
            
        cap = cv2.VideoCapture(stream_url)
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        if fps == 0:
            return []

        frame_step = int(fps * interval_seconds)
        
        count = 0
        for i in range(0, total_frames, frame_step):
            if count >= max_frames:
                break
            
            cap.set(cv2.CAP_PROP_POS_FRAMES, i)
            ret, frame = cap.read()
            if not ret:
                break
            
            # Resize for efficiency
            frame = cv2.resize(frame, (640, 360))
            
            # Encode as JPG
            _, buffer = cv2.imencode('.jpg', frame)
            b64_str = base64.b64encode(buffer).decode('utf-8')
            frames_b64.append(b64_str)
            count += 1
            
        cap.release()
    except Exception as e:
        print(f"Error extracting frames: {str(e)}")
        
    return frames_b64

async def generate_multimodal_summary(transcript: str, frames_b64: List[str], level: str = "intermediate") -> str:
    """
    Generates a personalized, visual-aware summary using Gemini 2.0 Flash's multimodal capabilities.
    """
    if not api_key or not client:
        return "Error: GOOGLE_API_KEY not set. Cannot generate multimodal summary."

    if not frames_b64:
        return "No visual frames available for analysis."

    level_instructions = {
        "beginner": "Focus on visual analogies, simple diagrams, and prominent on-screen text. Explain what is happening visually in simple terms.",
        "intermediate": "Analyze slides, code snippets, or demonstrations. Connect visual cues to the core technical concepts mentioned in the transcript.",
        "expert": "Identify specific technical details on screen (e.g., architectural diagrams, complex equations, specific UI elements). Focus on high-level synthesis of visual and auditory data."
    }

    instruction = level_instructions.get(level.lower(), level_instructions["intermediate"])

    # Prepare multimodal content
    # We send the transcript + the frames as images
    
    prompt = f"""
    You are NeuraLearn AI, a research-grade knowledge assistant specialized in multimodal analysis.
    You have been provided with a video transcript and key frames from the video.
    
    TASK: Generate a "Visual-Semantic Synthesis" summary.
    
    TARGET AUDIENCE LEVEL: {level.upper()}
    INSTRUCTIONS: {instruction}
    
    RULES:
    1. Synthesize the transcript with the visual information from the frames.
    2. Mention specific visual elements (e.g., "In the first slide shown...", "The demonstration highlights...").
    3. Use Markdown formatting.
    4. Focus on how the visual content reinforces or expands upon the spoken word.
    {get_system_instructions()}
    
    TRANSCRIPT:
    {transcript[:15000]}
    
    OUTPUT: Visual-Aware Personalized Summary
    """
    
    contents = [prompt]
    for b64 in frames_b64:
        contents.append({
            "mime_type": "image/jpeg",
            "data": b64
        })
    
    try:
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=contents
        )
        return response.text
    except Exception as e:
        return f"Failed to generate multimodal summary: {str(e)}"
