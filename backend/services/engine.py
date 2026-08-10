import os
import json
import cv2
import base64
import yt_dlp
import google.genai as genai
from google.genai import types
from groq import Groq
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
from services.profile import get_system_instructions

load_dotenv()

# Configuration
GEMINI_KEY = os.getenv("GOOGLE_API_KEY")
GROQ_KEY = os.getenv("GROQ_API_KEY")

gemini_client = genai.Client(api_key=GEMINI_KEY) if GEMINI_KEY else None
groq_client = Groq(api_key=GROQ_KEY) if GROQ_KEY and "your_groq" not in GROQ_KEY else None

async def extract_frames(video_url: str, max_frames: int = 3) -> List[str]:
    """Extracts low-res frames for multimodal analysis."""
    ydl_opts = {'format': 'best[height<=360]', 'quiet': True, 'no_warnings': True}
    frames_b64 = []
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            stream_url = info['url']
        cap = cv2.VideoCapture(stream_url)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames > 0:
            frame_step = max(int(total_frames / (max_frames + 1)), 1)
            for i in range(frame_step, total_frames, frame_step):
                if len(frames_b64) >= max_frames: break
                cap.set(cv2.CAP_PROP_POS_FRAMES, i)
                ret, frame = cap.read()
                if not ret: break
                frame = cv2.resize(frame, (400, 225)) # Even smaller for Groq Vision speed
                _, buffer = cv2.imencode('.jpg', frame)
                frames_b64.append(base64.b64encode(buffer).decode('utf-8'))
        cap.release()
    except Exception: pass
    return frames_b64

async def generate_summary_with_prompt(transcript: str, master_prompt: str) -> Dict[str, Any]:
    """Generates an outstanding executive summary and handles custom user intent separately."""
    if not groq_client: return {"summary": ["Groq client not configured."], "custom_insights": None}
    
    prompt = f"""
    {master_prompt}
    
    TASK: Analyze the following transcript and provide two distinct sections.
    IMPORTANT: BOTH SECTIONS MUST STRICTLY ADHERE TO THE CORE PERSONA BLUEPRINT DEFINED ABOVE. Do not deviate from the academic tone and depth requested.
    
    SECTION 1: CORE SUMMARY
    - Provide exactly 5 high-impact, elite-level bullet points.
    - Focus on the fundamental 'why' and 'how'.
    - Use bolding (e.g., **Term**) for key technical concepts.
    - Each bullet must be a substantial observation.
    
    SECTION 2: DYNAMIC CUSTOM SYNTHESIS
    - Address the instructions in the "DYNAMIC USER INTENT" section above.
    - IMPORTANT: Maintain the Persona Blueprint tone. Do not provide generic answers.
    - Use high-quality Markdown (headers, lists, or paragraphs as appropriate).
    - If no specific intent was provided, provide a 'Strategic Outlook' on the topic.
    
    DELIMITER: You MUST separate the two sections with the exact string: ===CUSTOM_INSIGHTS===
    
    NOTE: DO NOT output labels like "SECTION 1", "SECTION 2", or "CORE SUMMARY" in your response. Start directly with the content.
    
    TRANSCRIPT:
    {transcript[:10000]}
    """

    try:
        completion = groq_client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.3-70b-versatile",
        )
        content = completion.choices[0].message.content
        
        parts = content.split('===CUSTOM_INSIGHTS===')
        summary_text = parts[0].strip()
        custom_insights = parts[1].strip() if len(parts) > 1 else None
        
        # Parse bullets for Section 1
        import re
        lines = summary_text.split('\n')
        bullets = []
        for line in lines:
            line = line.strip()
            match = re.match(r'^[-*\d.]+\s*(.*)', line)
            if match:
                bullet_text = match.group(1).strip()
                if len(bullet_text) > 10:
                    bullets.append(bullet_text)
        
        if not bullets:
            bullets = [l.strip() for l in lines if len(l.strip()) > 20][:5]
            
        return {
            "summary": bullets[:5],
            "custom_insights": custom_insights
        }
    except Exception as e:
        return {"summary": [f"Error: {str(e)}"], "custom_insights": None}

async def process_uploaded_video(file_path: str, master_prompt: str) -> Dict[str, Any]:
    """
    Processes a locally uploaded video.
    PRIMARY: Extracts audio and uses Groq Whisper for transcription + Groq LLM for summary.
    FALLBACK: Gemini multimodal if Groq is unavailable.
    """
    # --- PRIMARY PATH: Groq Whisper (no Gemini quota needed) ---
    if groq_client:
        try:
            import subprocess
            import tempfile

            # Extract audio from video using ffmpeg
            audio_path = file_path + "_audio.mp3"
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", file_path, "-vn", "-ar", "16000", "-ac", "1", "-b:a", "64k", audio_path],
                capture_output=True, timeout=120
            )

            if result.returncode != 0:
                raise Exception(f"ffmpeg failed: {result.stderr.decode()}")

            # Transcribe with Groq Whisper
            with open(audio_path, "rb") as audio_file:
                transcription = groq_client.audio.transcriptions.create(
                    file=audio_file,
                    model="whisper-large-v3-turbo",
                    response_format="text"
                )

            # Cleanup audio file
            try:
                os.remove(audio_path)
            except Exception:
                pass

            transcript_text = transcription if isinstance(transcription, str) else transcription.text

            # Generate summary using existing Groq text pipeline
            engine_result = await generate_summary_with_prompt(transcript_text, master_prompt=master_prompt)

            return {
                "transcript": transcript_text,
                "summary": engine_result["summary"],
                "custom_insights": engine_result["custom_insights"]
            }

        except FileNotFoundError:
            # ffmpeg not installed, fall through to Gemini
            print("ffmpeg not found. Falling back to Gemini multimodal...")
        except Exception as e:
            err_str = str(e)
            if "does not contain any stream" in err_str:
                print("Video contains no audio track. Falling back to Gemini for visual-only analysis...")
            else:
                print(f"Groq Whisper pipeline error: {err_str}. Falling back to Gemini...")
            try:
                os.remove(file_path + "_audio.mp3")
            except Exception:
                pass

    # --- FALLBACK: Gemini Multimodal ---
    if not gemini_client:
        raise Exception(
            "Video processing failed. Either ffmpeg is not installed, the video has no audio, "
            "or Groq Whisper failed, AND Gemini fallback is not configured."
        )

    try:
        file = gemini_client.files.upload(file=file_path)

        import time
        while file.state.name == "PROCESSING":
            time.sleep(5)
            file = gemini_client.files.get(name=file.name)

        if file.state.name == "FAILED":
            raise Exception("Gemini video processing failed.")

        prompt = f"""
        {master_prompt}
        
        TASK: Perform a deep multimodal analysis of this video.
        
        OUTPUT STRUCTURE:
        1. TRANSCRIPT: Provide a highly accurate transcription of the audio (or describe visuals if no audio).
        2. CORE SUMMARY: Provide exactly 5 high-impact bullet points.
        3. CUSTOM SYNTHESIS: Address any instructions in the "DYNAMIC USER INTENT" section above.
        
        DELIMITERS: 
        - Start the transcript section with ===TRANSCRIPT_START===
        - Start the summary section with ===SUMMARY_START===
        - Start the custom synthesis with ===CUSTOM_START===
        
        Maintain the Persona Blueprint tone throughout.
        """

        response = gemini_client.models.generate_content(
            model='gemini-2.0-flash',
            contents=[file, prompt]
        )

        text = response.text
        transcript = text.split("===TRANSCRIPT_START===")[-1].split("===SUMMARY_START===")[0].strip()
        summary_raw = text.split("===SUMMARY_START===")[-1].split("===CUSTOM_START===")[0].strip()
        custom_insights = text.split("===CUSTOM_START===")[-1].strip()

        import re
        bullets = []
        for line in summary_raw.split('\n'):
            line = line.strip()
            match = re.match(r'^[-*\d.]+\s*(.*)', line)
            if match:
                bullet_text = match.group(1).strip()
                if len(bullet_text) > 10:
                    bullets.append(bullet_text)

        return {
            "transcript": transcript,
            "summary": bullets[:5],
            "custom_insights": custom_insights
        }
    except Exception as e:
        err_str = str(e)
        if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
            raise Exception("Your Google Gemini API free-tier quota has been exhausted. Please wait or use a video with audio so Groq can process it instead.")
        elif "does not contain any stream" in err_str:
             raise Exception("This video has no audio track, and Gemini fallback failed. Please upload a video with sound.")
        raise Exception(f"Video processing failed: {err_str}")




async def generate_summary(transcript: str, level: str = "intermediate", user_id: str = "default_user") -> List[str]:
    # Fallback/Helper that uses the new engine
    from services.profile import get_master_prompt
    master_prompt = get_master_prompt(user_id)
    return await generate_summary_with_prompt(transcript, master_prompt)

async def generate_notes(transcript: str, level: str = "intermediate", user_id: str = "default_user") -> str:
    """Generates research-grade structured notes using the Master Prompt."""
    if not groq_client: return "Groq client not configured."
    
    from services.profile import get_master_prompt
    master_prompt = get_master_prompt(user_id)

    prompt = f"""
    {master_prompt}
    
    TASK: Create a 'Scientific Synthesis' of the following transcript in high-quality Markdown.
    Use a professional, editorial tone consistent with the Persona Blueprint.
    
    Include:
    - # Abstract (Brief overview)
    - ## Core Architecture/Concepts (Deep dive)
    - ## Implementation Details (If applicable)
    - ## Critical Analysis (Pros/Cons or Trade-offs)
    
    TRANSCRIPT:
    {transcript[:15000]}
    """
    try:
        completion = groq_client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.3-70b-versatile",
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"Error: {str(e)}"

async def generate_visual_analysis(transcript: str, video_url: str, level: str = "intermediate", user_id: str = "default_user") -> str:
    """Generates visual insights consistent with the Master Prompt."""
    frames = await extract_frames(video_url)
    if not frames: return "No visual frames could be extracted."
    
    from services.profile import get_master_prompt
    master_prompt = get_master_prompt(user_id)

    vision_prompt = f"""
    {master_prompt}
    
    TASK: Analyze these {len(frames)} frames from the video.
    Identify:
    1. Key visual elements (diagrams, code, slides).
    2. Contextual relevance to the transcript.
    
    Write a professional markdown section titled 'Visual-Semantic Synthesis' in the tone of the Persona Blueprint.
    
    TRANSCRIPT PREVIEW: {transcript[:1000]}
    """
    # ... rest of the vision logic using vision_prompt

    # 1. Try Groq Vision (Llama 3.2)
    if groq_client:
        try:
            content = [{"type": "text", "text": vision_prompt}]
            for b64 in frames:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
                })
            
            completion = groq_client.chat.completions.create(
                messages=[{"role": "user", "content": content}],
                model="llama-3.2-11b-vision-preview",
            )
            return completion.choices[0].message.content
        except Exception as e:
            print(f"Groq Vision Error: {e}. Falling back to Gemini...")

    # 2. Fallback to Gemini
    if gemini_client:
        try:
            contents = [vision_prompt]
            for b64 in frames:
                contents.append(types.Part.from_bytes(data=base64.b64decode(b64), mime_type="image/jpeg"))
            
            response = gemini_client.models.generate_content(model='gemini-2.0-flash', contents=contents)
            return response.text
        except Exception as e:
            print(f"Gemini Vision Error: {e}. Moving to Final Logic Fallback...")

    # 3. Final Fallback: Text-Based Visual Deduction (The "Self-Healing" Layer)
    if groq_client:
        try:
            fallback_prompt = f"""
            The visual analysis engine is currently under high load. 
            Based on the following transcript, deduce what visual elements (slides, code, diagrams) 
            were likely shown at these moments. 
            
            Format as a professional 'Visual Deduction' report.
            
            TRANSCRIPT:
            {transcript[:4000]}
            """
            completion = groq_client.chat.completions.create(
                messages=[{"role": "user", "content": fallback_prompt}],
                model="llama-3.3-70b-versatile",
            )
            return "Note: Visual synthesis generated from transcript analysis.\n\n" + completion.choices[0].message.content
        except Exception:
            pass

    return "Visual analysis currently unavailable due to extreme API load. Please try again in 60 seconds."

async def extract_knowledge_graph(transcript: str, user_id: str, video_id: str) -> Dict[str, Any]:
    """Generates a structured knowledge graph using JSON mode and Identity Blueprint."""
    if not groq_client: return {"nodes": [], "edges": []}
    
    from services.profile import get_master_prompt
    master_prompt = get_master_prompt(user_id)
    
    prompt = f"""
    {master_prompt}
    
    TASK: Extract a Personal Knowledge Graph from this transcript.
    CRITICAL: Prioritize extracting concepts, themes, and nodes that strictly align with the user's Persona Blueprint provided above.
    
    Output a valid JSON object with the following schema:
    {{
        "nodes": [
            {{ "id": "unique_string_id", "label": "Concept Name", "description": "Short explanation", "timestamp_seconds": 0 }}
        ],
        "edges": [
            {{ "source_id": "unique_string_id", "target_id": "unique_string_id", "relationship": "e.g., depends on, relates to, causes" }}
        ]
    }}
    
    RULES:
    - Keep labels concise (1-3 words).
    - Estimate the best timestamp in seconds if possible, or 0 if general.
    - Extract up to 15 key nodes.
    
    TRANSCRIPT:
    {transcript[:15000]}
    """
    try:
        completion = groq_client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.3-70b-versatile",
            response_format={"type": "json_object"}
        )
        content = completion.choices[0].message.content
        return json.loads(content)
    except Exception as e:
        print(f"Graph extraction failed: {e}")
        return {"nodes": [], "edges": []}

async def generate_flashcards(transcript: str, user_id: str = "default_user", video_id: str = "") -> List[Dict[str, str]]:
    """Generates high-quality active recall flashcards mapped to graph concepts."""
    if not groq_client: return []
    
    # Attempt to fetch concept nodes for this video to ground the flashcards
    concept_str = "No existing graph concepts found."
    try:
        from services.supabase_client import supabase
        result = supabase.table("video_concepts").select("concept_id, concepts(label)").eq("video_id", video_id).execute()
        if result.data:
            nodes = []
            for r in result.data:
                lbl = r.get("concepts", {}).get("label")
                if lbl:
                    nodes.append(f"- ID: {r['concept_id']} | Label: {lbl}")
            if nodes:
                concept_str = "\n".join(nodes)
    except Exception as e:
        print(f"Failed to fetch concepts for flashcards: {e}")

    prompt = f"""
    Based on the transcript, create 6 challenging 'Active Recall' flashcards in JSON format.
    
    If a flashcard relates strongly to one of the following Graph Concepts, include its exact ID in 'concept_id'. Otherwise omit 'concept_id' or set to null.
    GRAPH CONCEPTS:
    {concept_str}
    
    JSON Schema:
    {{
        "flashcards": [
            {{ "question": "Question?", "answer": "Answer.", "concept_id": "uuid-string-or-null" }}
        ]
    }}
    
    TRANSCRIPT:
    {transcript[:8000]}
    """
    try:
        completion = groq_client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.3-70b-versatile",
            response_format={"type": "json_object"}
        )
        data = json.loads(completion.choices[0].message.content)
        return data.get("flashcards", [])
    except Exception:
        return []
