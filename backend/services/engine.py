import asyncio
import os
import json
import cv2
import base64
import google.genai as genai
from google.genai import types
from groq import Groq
from typing import Callable, List, Dict, Any, Optional
from dotenv import load_dotenv
from services.profile import get_system_instructions

load_dotenv()

# Configuration
GEMINI_KEY = os.getenv("GOOGLE_API_KEY")
GROQ_KEY = os.getenv("GROQ_API_KEY")

gemini_client = genai.Client(api_key=GEMINI_KEY) if GEMINI_KEY else None
groq_client = Groq(api_key=GROQ_KEY) if GROQ_KEY and "your_groq" not in GROQ_KEY else None

SUMMARY_INPUT_CHAR_LIMIT = 10000
SUMMARY_MAX_REDUCTION_PASSES = 8
SUMMARY_CHUNK_CONCURRENCY = 3

LEVEL_INSTRUCTIONS = {
    "beginner": "Explain the topic for a beginner. Define specialized terms briefly and use plain language without omitting important ideas.",
    "intermediate": "Give an advanced synthesis for a learner with basic familiarity. Explain important mechanisms and trade-offs, defining specialized terms when useful.",
    "expert": "Give an expert-level synthesis with precise terminology and nuanced technical detail, while staying strictly within the source.",
}
SUMMARY_DETAIL_DELIMITER = "===DETAILED_EXPLANATION==="
SUMMARY_CUSTOM_DELIMITER = "===CUSTOM_INSIGHTS==="
SUMMARY_FORMATS = {"bullets", "paragraphs", "table", "numbered steps"}
VISUAL_ANALYSIS_START = "### AUTOMATIC VISUAL ANALYSIS ###"


def _normalize_summary_format(preferred_format: str) -> str:
    if not isinstance(preferred_format, str):
        return "bullets"
    normalized = preferred_format.strip().lower()
    if normalized in {"paragraph", "prose"}:
        normalized = "paragraphs"
    if normalized in {"numbered", "numbered list", "numbered steps"}:
        normalized = "numbered steps"
    return normalized if normalized in SUMMARY_FORMATS else "bullets"


def _summary_format_instructions(preferred_format: str, preferred_length: str) -> str:
    format_instructions = {
        "bullets": (
            "Write exactly 5 concise, informative bullet points covering the source's main ideas. "
            "Use bolding for key technical concepts."
        ),
        "paragraphs": (
            "Write SECTION 1 as one concise brief-summary paragraph. Then write the exact delimiter "
            f"{SUMMARY_DETAIL_DELIMITER} on its own line, followed by SECTION 2 as a thorough "
            "detailed explanation in short prose paragraphs. Do not use bullets, numbered lists, "
            "or tables in either section."
        ),
        "table": (
            "Write the core summary as one compact Markdown table with columns for topic and "
            "source-supported explanation. Do not add facts absent from the source."
        ),
        "numbered steps": (
            "Write the core summary as a concise numbered list. Number items only when the source "
            "presents an order or sequence; otherwise use numbered summary points."
        ),
    }[preferred_format]
    normalized_length = (
        preferred_length.strip().lower()
        if isinstance(preferred_length, str)
        else "default"
    )
    length_instructions = {
        "shorter": "Keep the entire summary brief and prioritize only the most important source points.",
        "detailed": "Include thorough detail for all important source points without adding outside material.",
        "detailed and concise": (
            "Give a concise overview first, then retain the important detail in the explanation; "
            "remove repetition and filler."
        ),
    }.get(normalized_length, "Use the depth requested by the persona and selected level.")
    return f"FORMAT REQUIREMENT: {format_instructions}\nLENGTH REQUIREMENT: {length_instructions}"


def _extract_visual_evidence(master_prompt: str) -> str:
    """Extract successful frame analysis so the model can use it as source material."""
    _, marker, remaining = master_prompt.partition(VISUAL_ANALYSIS_START)
    if not marker:
        return ""

    section_end = len(remaining)
    for boundary in ("\n\n### VISUAL ANALYSIS LIMITATION ###", "\n## OPERATING PROTOCOLS:"):
        boundary_index = remaining.find(boundary)
        if boundary_index >= 0:
            section_end = min(section_end, boundary_index)
    return remaining[:section_end].strip()


def _parse_summary_output(content: str, preferred_format: str) -> Dict[str, Any]:
    """Parse the structured model output while preserving the requested presentation."""
    import re

    summary_format = _normalize_summary_format(preferred_format)
    summary_text, separator, custom_text = content.partition(SUMMARY_CUSTOM_DELIMITER)
    custom_insights = custom_text.strip() if separator else ""

    if summary_format == "paragraphs":
        brief, detail_separator, detailed = summary_text.partition(SUMMARY_DETAIL_DELIMITER)
        if not detail_separator or not brief.strip() or not detailed.strip():
            raise RuntimeError("The model did not return both requested summary paragraphs.")
        summary = [brief.strip(), detailed.strip()]
    elif summary_format == "bullets":
        bullets = []
        for line in summary_text.splitlines():
            match = re.match(r"^\s*[-*]\s+(.+?)\s*$", line)
            if match and len(match.group(1).strip()) > 10:
                bullets.append(match.group(1).strip())
        if len(bullets) != 5:
            raise RuntimeError(
                f"The model returned {len(bullets)} summary bullets instead of 5."
            )
        summary = bullets
    else:
        if not summary_text.strip():
            raise RuntimeError("The model returned an empty video summary.")
        summary = [summary_text.strip()]

    return {
        "summary": summary,
        "summary_format": summary_format,
        "custom_insights": custom_insights or None,
    }


def _split_transcript(transcript: str, max_chars: int = SUMMARY_INPUT_CHAR_LIMIT) -> List[str]:
    """Split transcript text into bounded chunks without dropping source characters."""
    chunks = []
    start = 0
    while start < len(transcript):
        end = min(start + max_chars, len(transcript))
        if end < len(transcript):
            boundary_start = start + max_chars // 2
            boundary = max(
                transcript.rfind("\n", boundary_start, end),
                transcript.rfind(". ", boundary_start, end),
                transcript.rfind("? ", boundary_start, end),
                transcript.rfind("! ", boundary_start, end),
                transcript.rfind(" ", boundary_start, end),
            )
            if boundary >= boundary_start:
                end = boundary + 1
        chunks.append(transcript[start:end])
        start = end
    return chunks


def _summarize_transcript_chunk(transcript_chunk: str) -> str:
    prompt = f"""
    Create faithful, concise notes from the source material below. It may be a
    video transcript excerpt or notes from an earlier reduction pass. Preserve
    every distinct topic, claim, explanation, example, name, qualification, and
    conclusion. Keep the source order. Do not add outside facts, speculation,
    recommendations, or conclusions. These notes will be combined with other
    parts of the same video, so do not add an introduction or standalone ending.
    Keep the notes under 700 words.

    SOURCE MATERIAL:
    {transcript_chunk}
    """
    completion = groq_client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        model="openai/gpt-oss-120b",
    )
    return completion.choices[0].message.content.strip()


def _summarize_study_notes_chunk(source_chunk: str) -> str:
    prompt = f"""
    Produce detailed, faithful study notes from this source material. It may be
    a video transcript excerpt or notes from an earlier reduction pass. Capture
    each distinct subject, definition, mechanism, example, named entity, claim,
    qualification, and conclusion in this part. Preserve the order. Do not add
    outside knowledge, invented examples, recommendations, or implications.
    Do not repeat an introduction or conclusion for the whole video. Keep these
    notes under 700 words.

    SOURCE MATERIAL:
    {source_chunk}
    """
    completion = groq_client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        model="openai/gpt-oss-120b",
    )
    return completion.choices[0].message.content.strip()


async def _map_reduce_transcript(
    transcript: str,
    summarize_chunk: Callable[[str], str],
) -> str:
    """Build bounded context from the whole transcript without truncating it."""
    if not transcript.strip():
        raise ValueError("The video transcript is empty.")

    semaphore = asyncio.Semaphore(SUMMARY_CHUNK_CONCURRENCY)

    async def summarize(chunk: str) -> str:
        async with semaphore:
            note = await asyncio.to_thread(summarize_chunk, chunk)
        if not note:
            raise RuntimeError("The model returned empty notes for a transcript section.")
        return note

    chunks = _split_transcript(transcript)
    notes = await asyncio.gather(*(summarize(chunk) for chunk in chunks))
    combined = "\n\n".join(notes)
    reduction_passes = 0

    while len(combined) > SUMMARY_INPUT_CHAR_LIMIT:
        if reduction_passes >= SUMMARY_MAX_REDUCTION_PASSES:
            raise RuntimeError("Could not condense the full transcript within the model context limit.")
        reduced_notes = await asyncio.gather(
            *(summarize(chunk) for chunk in _split_transcript(combined))
        )
        reduced = "\n\n".join(reduced_notes)
        if len(reduced) >= len(combined):
            raise RuntimeError("Could not condense the full transcript within the model context limit.")
        combined = reduced
        reduction_passes += 1

    return combined


async def extract_frames(
    video_url: str,
    max_frames: int = 3,
    is_youtube: bool = True,
) -> List[str]:
    """Extracts evenly spaced, low-resolution frames for multimodal analysis."""
    frames_b64 = []
    cap = None
    try:
        if is_youtube:
            from services.frame_extraction import (
                extract_frame_at_timestamp,
                resolve_youtube_stream_url,
            )

            resolved_stream = await resolve_youtube_stream_url(video_url)
            if not resolved_stream.duration or resolved_stream.duration <= 0:
                print("[METRIC] Extraction: Failed (Video duration unavailable)")
                return []

            for index in range(1, max_frames + 1):
                timestamp = resolved_stream.duration * index / (max_frames + 1)
                frame_path = await extract_frame_at_timestamp(
                    resolved_stream.url,
                    f"{timestamp:.3f}",
                    is_remote=True,
                    http_headers=resolved_stream.http_headers,
                )
                try:
                    with open(frame_path, "rb") as frame_file:
                        frames_b64.append(
                            base64.b64encode(frame_file.read()).decode("utf-8")
                        )
                finally:
                    import shutil

                    shutil.rmtree(os.path.dirname(frame_path), ignore_errors=True)
            print(f"[METRIC] Extraction: Success ({len(frames_b64)} Frames)")
            return frames_b64
        else:
            stream_url = video_url

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
        if frames_b64:
            print(f"[METRIC] Extraction: Success ({len(frames_b64)} Frames)")
        else:
            print("[METRIC] Extraction: Failed (No video frames available)")
    except Exception as e:
        print(f"[METRIC] Extraction: Failed (Frames) - {e}")
    finally:
        if cap is not None:
            cap.release()
    return frames_b64

async def generate_summary_with_prompt(
    transcript: str,
    master_prompt: str,
    level: str = "intermediate",
    preferred_format: str = "bullets",
    preferred_length: str = "default",
) -> Dict[str, Any]:
    """Generates an outstanding executive summary and handles custom user intent separately."""
    if not groq_client:
        raise RuntimeError("Groq is not configured; cannot generate a video summary.")

    try:
        if not transcript.strip():
            raise ValueError("The video transcript is empty.")
        visual_evidence = _extract_visual_evidence(master_prompt)
        complete_source = transcript
        if visual_evidence:
            complete_source += (
                "\n\nVISUAL EVIDENCE FROM VIDEO FRAMES:\n"
                f"{visual_evidence}"
            )

        if len(complete_source) > SUMMARY_INPUT_CHAR_LIMIT:
            source_material = await _map_reduce_transcript(
                complete_source,
                _summarize_transcript_chunk,
            )
            source_label = "COMPREHENSIVE NOTES FROM THE VIDEO TRANSCRIPT AND VISUAL ANALYSIS"
        else:
            source_material = complete_source
            source_label = (
                "TRANSCRIPT AND VISUAL FRAME ANALYSIS"
                if visual_evidence
                else "TRANSCRIPT"
            )

        selected_level = level.lower()
        summary_format = _normalize_summary_format(preferred_format)
        level_instruction = LEVEL_INSTRUCTIONS.get(
            selected_level,
            LEVEL_INSTRUCTIONS["intermediate"],
        )
        prompt = f"""
    {master_prompt}
    
    TASK: Summarize the provided source material and provide two distinct sections.
    Treat it as the sole authority for claims about the video. Do not add outside
    facts, future predictions, invented examples, recommendations, or conclusions.
    If a point is unclear or absent, do not guess. Follow the selected level and
    the persona's tone, vocabulary, depth, length, and formatting preferences.

    SELECTED LEVEL ({selected_level}):
    {level_instruction}
    
    SECTION 1: CORE SUMMARY
    {_summary_format_instructions(summary_format, preferred_length)}
    
    SECTION 2: DYNAMIC CUSTOM SYNTHESIS
    - Address only explicit instructions in the DYNAMIC USER INTENT above.
    - Clearly distinguish requested analysis from claims made by the video.
    - If the intent includes AUTOMATIC VISUAL ANALYSIS, use it as evidence only for
      visual details; do not guess details that are unclear or unavailable.
    - If there is no explicit request, leave this section empty.
    
    DELIMITER: You MUST separate the core summary and dynamic synthesis with the exact
    string: {SUMMARY_CUSTOM_DELIMITER}
    
    NOTE: Do not output section labels. Do not add a strategic outlook unless requested.
    
    {source_label}:
    {source_material}
        """

        completion = await asyncio.to_thread(
            groq_client.chat.completions.create,
            messages=[{"role": "user", "content": prompt}],
            model="openai/gpt-oss-120b",
        )
        content = completion.choices[0].message.content
        if not content or not content.strip():
            raise RuntimeError("The model returned an empty video summary.")
        
        return _parse_summary_output(content, summary_format)
    except Exception as e:
        raise RuntimeError(f"Video summary generation failed: {e}") from e

async def process_uploaded_video(
    file_path: str,
    master_prompt: str,
    level: str = "intermediate",
    preferred_format: str = "bullets",
    preferred_length: str = "default",
) -> Dict[str, Any]:
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
            print("[METRIC] Extraction: Success (Audio)")

            # Generate summary using existing Groq text pipeline
            engine_result = await generate_summary_with_prompt(
                transcript_text,
                master_prompt=master_prompt,
                level=level,
                preferred_format=preferred_format,
                preferred_length=preferred_length,
            )

            return {
                "transcript": transcript_text,
                **engine_result,
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

        summary_format = _normalize_summary_format(preferred_format)
        prompt = f"""
        {master_prompt}

        SELECTED LEVEL ({level}):
        {LEVEL_INSTRUCTIONS.get(level.lower(), LEVEL_INSTRUCTIONS["intermediate"])}

        TASK: Transcribe and summarize the complete video.
        Use only information present in the video. Do not add outside facts,
        future predictions, invented examples, or recommendations. Follow the
        selected level and persona when explaining the video's own material.

        OUTPUT STRUCTURE:
        1. TRANSCRIPT: Transcribe the audio as completely as possible (or describe visuals if there is no audio).
        2. CORE SUMMARY: Follow this required format and length:
        {_summary_format_instructions(summary_format, preferred_length)}
        3. CUSTOM SYNTHESIS: Address only explicit instructions in DYNAMIC USER INTENT; otherwise leave empty.
        
        DELIMITERS: 
        - Start the transcript section with ===TRANSCRIPT_START===
        - Start the summary section with ===SUMMARY_START===
        - For paragraph format, separate the brief and detailed sections with
          {SUMMARY_DETAIL_DELIMITER}
        - Start the custom synthesis with ===CUSTOM_START===
        
        Maintain the Persona Blueprint tone throughout.
        """

        response = gemini_client.models.generate_content(
            model='gemini-3.8-flash',
            contents=[file, prompt]
        )

        text = response.text
        if not text:
            raise RuntimeError("Gemini returned an empty video analysis.")
        required_delimiters = (
            "===TRANSCRIPT_START===",
            "===SUMMARY_START===",
            "===CUSTOM_START===",
        )
        if not text or any(delimiter not in text for delimiter in required_delimiters):
            raise RuntimeError("Gemini returned an incomplete video analysis.")
        transcript = text.split("===TRANSCRIPT_START===", 1)[1].split("===SUMMARY_START===", 1)[0].strip()
        summary_raw = text.split("===SUMMARY_START===", 1)[1].split("===CUSTOM_START===", 1)[0].strip()
        custom_insights = text.split("===CUSTOM_START===", 1)[1].strip() or None

        if not transcript:
            raise RuntimeError("Gemini returned an empty video transcript.")

        return {
            "transcript": transcript,
            **_parse_summary_output(
                f"{summary_raw}{SUMMARY_CUSTOM_DELIMITER}{custom_insights or ''}",
                summary_format,
            ),
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
    result = await generate_summary_with_prompt(transcript, master_prompt, level=level)
    return result["summary"]

async def generate_notes(
    transcript: str,
    level: str = "intermediate",
    user_id: str = "default_user",
    dynamic_extra: str = "",
    use_profile: bool = True,
    jwt: Optional[str] = None,
) -> str:
    """Generate source-grounded study notes covering the complete transcript."""
    if not groq_client:
        raise RuntimeError("Groq is not configured; cannot generate study notes.")

    try:
        from services.profile import get_master_prompt

        master_prompt = (
            get_master_prompt(user_id, dynamic_extra, jwt=jwt)
            if use_profile
            else "No user persona is active. Follow the selected learning level."
        )
        selected_level = level.lower()
        level_instruction = LEVEL_INSTRUCTIONS.get(
            selected_level,
            LEVEL_INSTRUCTIONS["intermediate"],
        )
        source_material = await _map_reduce_transcript(
            transcript,
            _summarize_study_notes_chunk,
        )
        prompt = f"""
    {master_prompt}

    TASK: Produce accurate, detailed study notes based only on the provided
    source material. This is a synthesis of what the video says, not an
    invitation to supplement it with general knowledge.

    SELECTED LEARNING LEVEL ({selected_level}):
    {level_instruction}

    SOURCE-FIDELITY RULES:
    - Include only claims, examples, recommendations, and technical details supported by the source.
    - Do not invent implementation advice, pros/cons, security guidance, use cases, trends, or conclusions.
    - If you draw an implication explicitly requested by the user, label it as an inference and state its source basis.
    - Preserve qualifications and uncertainty; do not strengthen claims.
    - Never silently correct or replace a source term. Quote it and flag it as unclear if it appears erroneous.

    FORMAT:
    - Start with a concise title and overview.
    - Organize topics in the order presented.
    - Explain concepts, mechanisms, and examples that the source actually covers.
    - Include a glossary only for terms used in the source.
    - Omit sections the source does not support; do not pad with generic advice.
    - Use clear Markdown headings and nested bullets where they improve readability.

    SOURCE NOTES FROM THE COMPLETE VIDEO:
    {source_material}
    """
        completion = await asyncio.to_thread(
            groq_client.chat.completions.create,
            messages=[{"role": "user", "content": prompt}],
            model="openai/gpt-oss-120b",
        )
        content = completion.choices[0].message.content
        if not content or not content.strip():
            raise RuntimeError("The model returned empty study notes.")
        return content.strip()
    except Exception as e:
        raise RuntimeError(f"Study-notes generation failed: {e}") from e

async def generate_visual_analysis(
    transcript: str,
    video_url: str,
    level: str = "intermediate",
    user_id: str = "default_user",
    dynamic_extra: str = "",
    is_youtube: bool = True,
    max_frames: int = 3,
) -> str:
    """Analyzes sampled video frames and answers any supplied visual focus."""
    frames = await extract_frames(
        video_url,
        max_frames=max_frames,
        is_youtube=is_youtube,
    )
    if not frames:
        return (
            "Visual analysis unavailable: no frames could be extracted. "
            "Do not infer or guess what the video showed."
        )
    
    from services.profile import get_master_prompt
    master_prompt = get_master_prompt(user_id)

    level_instruction = LEVEL_INSTRUCTIONS.get(
        level.lower(),
        LEVEL_INSTRUCTIONS["intermediate"],
    )
    vision_prompt = f"""
    {master_prompt}

    TASK: Analyze these {len(frames)} representative frames sampled across the video.
    Address the user's visual focus request and describe relevant visible content
    such as diagrams, charts, code, slides, or images. Do not imply the frames are
    from a particular timestamp. Describe only details that are actually legible.
    If the requested item is not visible in the sampled frames, say so rather than
    guessing.

    USER'S VISUAL FOCUS REQUEST:
    {dynamic_extra or "Describe the important visual content in these frames."}

    TARGET LEVEL: {level_instruction}

    Write a professional markdown section titled 'Visual-Semantic Synthesis' in the tone of the Persona Blueprint.
    
    TRANSCRIPT PREVIEW: {transcript[:1000]}
    """

    # Prefer Gemini for diagram-focused visual analysis; retain Groq as fallback.
    if gemini_client:
        try:
            contents = [vision_prompt]
            for b64 in frames:
                contents.append(
                    types.Part.from_bytes(
                        data=base64.b64decode(b64),
                        mime_type="image/jpeg",
                    )
                )

            response = await asyncio.to_thread(
                gemini_client.models.generate_content,
                model="gemini-3.5-flash-lite",
                contents=contents,
            )
            if response.text and response.text.strip():
                return response.text.strip()
        except Exception as e:
            print(f"Gemini Vision Error: {e}. Falling back to Groq...")

    if groq_client:
        try:
            content = [{"type": "text", "text": vision_prompt}]
            for b64 in frames:
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                    }
                )

            completion = await asyncio.to_thread(
                groq_client.chat.completions.create,
                messages=[{"role": "user", "content": content}],
                model="qwen/qwen3.8-27b",
            )
            explanation = completion.choices[0].message.content
            if explanation and explanation.strip():
                return explanation.strip()
        except Exception as e:
            print(f"Groq Vision Error: {e}.")

    return (
        "Visual analysis unavailable: all configured vision providers failed or "
        "returned an empty response. No visual details were inferred."
    )

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
            model="openai/gpt-oss-120b",
            response_format={"type": "json_object"}
        )
        content = completion.choices[0].message.content
        parsed = json.loads(content)
        print("[METRIC] JSON Parse: Success (Knowledge Graph)")
        return parsed
    except Exception as e:
        print(f"[METRIC] JSON Parse: Failed (Knowledge Graph) - {e}")
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
            model="openai/gpt-oss-120b",
            response_format={"type": "json_object"}
        )
        data = json.loads(completion.choices[0].message.content)
        print("[METRIC] JSON Parse: Success (Flashcards)")
        return data.get("flashcards", [])
    except Exception as e:
        print(f"[METRIC] JSON Parse: Failed (Flashcards) - {e}")
        return []
