from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends, Security, BackgroundTasks
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, field_validator
from typing import List, Optional, Dict, Any, Literal
import shutil
import os
import uuid
import hashlib
import json
from services.transcription import get_transcript
from services import engine
from services.memory import save_to_memory, search_memory
from services.profile import update_preference, get_profile, update_persona_blueprint, refine_persona_with_ai
from services.supabase_client import verify_auth_token
from services.cache import get_cached_synthesis, set_cached_synthesis, check_rate_limit
from services import graph as graph_service

api_router = APIRouter()
security = HTTPBearer(auto_error=False)

async def inject_frame_explanations(video_id_or_url: str, dynamic_extra: str, is_youtube: bool, user_id: str) -> str:
    """Scans dynamic_extra for timestamps, extracts frames, explains them, and appends to the prompt."""
    if not dynamic_extra:
        return dynamic_extra
        
    import re
    # Match HH:MM:SS, MM:SS, or seconds
    matches = re.finditer(r"\b(\d{1,2}:\d{2}:\d{2}|\d{1,2}:\d{2}|\d+(?:\.\d+)?)\b", dynamic_extra)
    timestamps = [m.group(1) for m in matches]
    
    if not timestamps:
        return dynamic_extra
        
    print(f"Found timestamps in prompt: {timestamps}")
    from services.frame_extraction import extract_frame_at_timestamp
    from services.vision_client import explain_frame_with_vision
    
    explanations = []
    for ts in set(timestamps):
        try:
            stream_url = video_id_or_url
            if is_youtube:
                import redis
                import asyncio
                import urllib.parse
                import hashlib
                r = redis.Redis(host=os.getenv("REDIS_HOST", "localhost"), port=6379, db=0, decode_responses=True)
                url_hash = hashlib.md5(video_id_or_url.encode()).hexdigest()
                cache_key = f"ytdlp:resolved:{url_hash}"
                stream_url = r.get(cache_key)
                if not stream_url:
                    cmd = ["yt-dlp", "-g", "-f", "bestvideo[height<=720]", f"https://www.youtube.com/watch?v={video_id_or_url}"]
                    process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                    stdout, stderr = await process.communicate()
                    if process.returncode != 0:
                        raise Exception("yt-dlp failed")
                    stream_url = stdout.decode("utf-8").strip()
                    r.setex(cache_key, 3600, stream_url)
            
            frame_path = await extract_frame_at_timestamp(stream_url, ts, is_remote=is_youtube)
            vision_res = await explain_frame_with_vision(frame_path, user_id, "Explain this frame clearly.")
            
            explanations.append(f"Visual details at timestamp {ts}:\n{vision_res['explanation']}")
            
            import os
            try:
                os.remove(frame_path)
            except:
                pass
        except Exception as e:
            print(f"Failed to auto-explain frame at {ts}: {e}")
            
    if explanations:
        dynamic_extra += "\n\n### AUTOMATIC DIAGRAM EXPLANATIONS ###\n" + "\n\n".join(explanations)
        
    return dynamic_extra

def get_current_user(credentials: HTTPAuthorizationCredentials = Security(security)) -> str:
    if not credentials:
        return "default_user"
    try:
        user_id = verify_auth_token(credentials.credentials)
        if not user_id: return "default_user"
        return user_id
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid authentication token.")

def get_current_jwt(credentials: HTTPAuthorizationCredentials = Security(security)) -> Optional[str]:
    if not credentials:
        return None
    return credentials.credentials

class VideoRequest(BaseModel):
    url: str
    level: Optional[str] = "intermediate"
    dynamic_extra: Optional[str] = ""
    manual_transcript: Optional[str] = ""
    use_profile: bool = True

class ModuleRequest(BaseModel):
    video_id: str
    transcript: str
    video_url: Optional[str] = None
    level: Optional[str] = "intermediate"
    dynamic_extra: Optional[str] = ""
    use_profile: bool = True

class FeedbackRequest(BaseModel):
    video_id: str
    module: str
    rating: str
    level: str
    custom_feedback: Optional[str] = ""

class ProcessingResponse(BaseModel):
    video_id: str
    title: str
    summary: List[str]
    transcript: str
    custom_insights: Optional[str] = None

class EvaluateSubmitRequest(BaseModel):
    participant_id: str
    video_id: str
    shown_as_A: str
    ratings_A: Dict[str, int]
    ratings_B: Dict[str, int]
    preference: str
    preference_reason: str
    profile_version_used: Optional[int] = None

@api_router.post("/upload")
async def upload_video(
    file: UploadFile = File(...),
    level: str = Form("intermediate"),
    dynamic_extra: str = Form(""),
    use_profile: bool = Form(True),
    user_id: str = Depends(get_current_user),
    jwt: Optional[str] = Depends(get_current_jwt)
):
    # RATE LIMITING
    if not await check_rate_limit(user_id, limit=5, window=60):
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Please wait a minute.")

    file_path = None
    try:
        # PATH TRAVERSAL FIX
        safe_filename = f"{uuid.uuid4()}_{os.path.basename(file.filename)}"
        temp_dir = os.path.join(os.getcwd(), "temp_uploads")
        os.makedirs(temp_dir, exist_ok=True)
        file_path = os.path.join(temp_dir, safe_filename)
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        dynamic_extra = await inject_frame_explanations(file_path, dynamic_extra, is_youtube=False, user_id=user_id)
        if use_profile:
            from services.profile import get_master_prompt, get_profile
            master_prompt = get_master_prompt(user_id, dynamic_extra, jwt=jwt)
            prof_version = get_profile(user_id, jwt=jwt).get("profile_version", 1)
        else:
            master_prompt = "Summarize this video."
            prof_version = None

        import time
        start_t = time.time()

        try:
            from services.transcription import get_local_video_transcript
            transcript = await get_local_video_transcript(file_path)
            
            engine_result = await engine.generate_summary_with_prompt(transcript, master_prompt=master_prompt)
            result = {
                "transcript": transcript,
                "summary": engine_result["summary"],
                "custom_insights": engine_result["custom_insights"]
            }
        except Exception as e:
            print(f"Fallback to legacy process_uploaded_video due to: {e}")
            result = await engine.process_uploaded_video(file_path, master_prompt=master_prompt)
        
        latency = int((time.time() - start_t) * 1000)
        from services.supabase_client import supabase
        if supabase:
            try:
                supabase.table("generation_log", jwt=jwt).insert({
                    "user_id": user_id,
                    "video_id": f"upload_{safe_filename}",
                    "use_profile": use_profile,
                    "profile_version_used": prof_version,
                    "prompt_text": master_prompt,
                    "summary_output": " ".join(result["summary"]),
                    "model_name": "gemini-2.0-flash / groq",
                    "latency_ms": latency,
                    "cache_hit": False
                })
            except Exception as log_e:
                print(f"Generation log error: {log_e}")
        
        save_to_memory(
            video_id=f"upload_{safe_filename}",
            title=f"Uploaded: {file.filename}",
            content=" ".join(result["summary"]),
            user_id=user_id,
            profile_version_used=prof_version
        )

        return ProcessingResponse(
            video_id=f"upload_{safe_filename}",
            title=file.filename,
            summary=result["summary"],
            transcript=result["transcript"],
            custom_insights=result["custom_insights"]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail="Video processing failed.")
    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass

@api_router.post("/process", response_model=ProcessingResponse)
async def process_video(
    request: VideoRequest,
    user_id: str = Depends(get_current_user),
    jwt: Optional[str] = Depends(get_current_jwt)
):
    # RATE LIMITING
    if not await check_rate_limit(user_id, limit=10, window=60):
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Please wait a minute.")

    # CACHING
    cache_key = f"process:{hashlib.md5((request.url + request.level + request.dynamic_extra + user_id + str(request.use_profile)).encode()).hexdigest()}"
    cached = await get_cached_synthesis(cache_key)
    if cached:
        from services.supabase_client import supabase
        if supabase:
            try:
                prof_version = get_profile(user_id, jwt=jwt).get("profile_version", 1) if request.use_profile else None
                supabase.table("generation_log", jwt=jwt).insert({
                    "user_id": user_id,
                    "video_id": cached.get("video_id", request.url),
                    "use_profile": request.use_profile,
                    "profile_version_used": prof_version,
                    "prompt_text": "CACHE_HIT",
                    "summary_output": " ".join(cached.get("summary", [])),
                    "model_name": "cache",
                    "latency_ms": 0,
                    "cache_hit": True
                })
            except Exception:
                pass
        return ProcessingResponse(**cached)

    try:
        if request.manual_transcript:
            transcript_data = {
                "video_id": "manual_" + str(len(request.manual_transcript)),
                "title": "Manual Synthesis",
                "text": request.manual_transcript
            }
        else:
            transcript_data = await get_transcript(request.url)
        
        request.dynamic_extra = await inject_frame_explanations(request.url, request.dynamic_extra, is_youtube=True, user_id=user_id)
        if request.use_profile:
            from services.profile import get_master_prompt, get_profile
            master_prompt = get_master_prompt(user_id, request.dynamic_extra, jwt=jwt)
            prof_version = get_profile(user_id, jwt=jwt).get("profile_version", 1)
        else:
            master_prompt = "Summarize this video."
            prof_version = None

        import time
        start_t = time.time()

        engine_result = await engine.generate_summary_with_prompt(
            transcript_data["text"], 
            master_prompt=master_prompt
        )
        latency = int((time.time() - start_t) * 1000)
        
        summary = engine_result["summary"]
        custom_insights = engine_result["custom_insights"]
        
        from services.supabase_client import supabase
        if supabase:
            try:
                supabase.table("generation_log", jwt=jwt).insert({
                    "user_id": user_id,
                    "video_id": transcript_data["video_id"],
                    "use_profile": request.use_profile,
                    "profile_version_used": prof_version,
                    "prompt_text": master_prompt,
                    "summary_output": " ".join(summary),
                    "model_name": "gemini-2.0-flash / groq",
                    "latency_ms": latency,
                    "cache_hit": False
                })
            except Exception as log_e:
                print(f"Generation log error: {log_e}")
        
        content_to_save = " ".join(summary)
        if custom_insights:
            content_to_save += f"\n\nCUSTOM SYNTHESIS:\n{custom_insights}"

        save_to_memory(
            video_id=transcript_data["video_id"],
            title=transcript_data["title"],
            content=content_to_save,
            user_id=user_id,
            profile_version_used=prof_version
        )

        response_data = {
            "video_id": transcript_data["video_id"],
            "title": transcript_data["title"],
            "summary": summary,
            "transcript": transcript_data["text"],
            "custom_insights": custom_insights
        }
        
        await set_cached_synthesis(cache_key, response_data)
        return ProcessingResponse(**response_data)

    except Exception as e:
        err = str(e)
        if "blocking" in err.lower() or "bot" in err.lower() or "429" in err:
            raise HTTPException(status_code=503, detail="YouTube is blocking automated requests from this server. Please paste the video transcript manually using the 'Manual Transcript' option.")
        raise HTTPException(status_code=500, detail=f"Failed to process video: {err[:200]}")


@api_router.post("/generate/{module}")
async def generate_module(
    module: str, 
    request: ModuleRequest, 
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user),
    jwt: Optional[str] = Depends(get_current_jwt)
):
    VALID_MODULES = {"notes", "visuals", "map", "flashcards"}
    if module not in VALID_MODULES:
        raise HTTPException(status_code=400, detail="Invalid module.")

    cache_key = f"module:{module}:{hashlib.md5((request.video_id + request.level + user_id).encode()).hexdigest()}"
    cached = await get_cached_synthesis(cache_key)
    if cached:
        return {"data": cached}

    try:
        data = None
        if module == "notes":
            data = await engine.generate_notes(request.transcript, level=request.level, user_id=user_id)

        elif module == "visuals":
            if not request.video_url:
                raise HTTPException(status_code=400, detail="video_url is required for visual analysis.")
            data = await engine.generate_visual_analysis(
                request.transcript, request.video_url, level=request.level, user_id=user_id
            )
            # Link visual insights to existing concepts in the background safely
            background_tasks.add_task(graph_service.map_vision_to_concepts, user_id, request.video_id, data, jwt)

        elif module == "map":
            # Extract structured graph from transcript
            extracted = await engine.extract_knowledge_graph(
                request.transcript, user_id=user_id, video_id=request.video_id
            )
            # Persist + merge into the user's persistent graph
            merge_stats = graph_service.persist_graph(
                user_id=user_id,
                video_id=request.video_id,
                extracted=extracted,
                jwt=jwt
            )
            # Return the raw extracted graph for immediate rendering,
            # plus merge stats so the caller can surface them in the UI.
            data = {**extracted, "merge_stats": merge_stats}

        elif module == "flashcards":
            data = await engine.generate_flashcards(request.transcript, user_id=user_id, video_id=request.video_id)

        await set_cached_synthesis(cache_key, data)
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        print(f"[generate/{module}] ERROR for user {user_id}: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate module: {str(e)}")


@api_router.post("/feedback")
async def save_feedback(
    request: FeedbackRequest,
    user_id: str = Depends(get_current_user),
    jwt: Optional[str] = Depends(get_current_jwt)
):
    update_preference(user_id, request.level, request.rating, jwt=jwt)
    return {"status": "success"}


class RefinedPersonaRequest(BaseModel):
    feedback_type: str  # too_long | too_technical | wrong_format | other
    custom_feedback: Optional[str] = ""


@api_router.post("/profile/refine-persona")
async def refine_persona(
    request: RefinedPersonaRequest,
    user_id: str = Depends(get_current_user),
    jwt: Optional[str] = Depends(get_current_jwt)
):
    """Uses AI to rewrite persona based on negative feedback while preserving key user details."""
    if user_id == "default_user":
        raise HTTPException(status_code=401, detail="Authentication required.")
    try:
        # AI rewrites the persona
        new_blueprint = refine_persona_with_ai(
            user_id=user_id,
            feedback_type=request.feedback_type,
            custom_feedback=request.custom_feedback or "",
            jwt=jwt
        )
        # Save it
        update_persona_blueprint(user_id, new_blueprint, jwt=jwt)
        return {"status": "success", "refined_blueprint": new_blueprint}
    except Exception as e:
        print(f"[refine-persona] ERROR for user {user_id}: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to refine persona: {str(e)}")


@api_router.get("/profile/{target_user_id}")
async def get_user_profile(
    target_user_id: str,
    current_user_id: str = Depends(get_current_user),
    jwt: Optional[str] = Depends(get_current_jwt),
):
    if target_user_id != current_user_id and current_user_id != "default_user":
        raise HTTPException(status_code=403, detail="Not authorized to view this profile.")
    return get_profile(target_user_id, jwt=jwt)


@api_router.post("/profile/custom")
async def set_custom_instructions(
    request: Dict[str, str],
    user_id: str = Depends(get_current_user),
    jwt: Optional[str] = Depends(get_current_jwt)
):
    try:
        blueprint = request.get("blueprint", "")
        print(f"[profile/custom] Saving blueprint for user {user_id}: '{blueprint[:60]}...' ({len(blueprint)} chars)")
        update_persona_blueprint(user_id, blueprint, jwt=jwt)
        return {"status": "success"}
    except Exception as e:
        print(f"[profile/custom] ERROR for user {user_id}: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save persona: {str(e)}")


@api_router.post("/search")
async def search_knowledge(request: Dict[str, Any], user_id: str = Depends(get_current_user)):
    query = request.get("query", "")
    results = search_memory(query, user_id=user_id)
    return {"results": results}


@api_router.post("/evaluate/submit")
async def submit_evaluation(
    request: EvaluateSubmitRequest,
    user_id: str = Depends(get_current_user),
    jwt: Optional[str] = Depends(get_current_jwt)
):
    from services.supabase_client import supabase
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase not configured.")
    try:
        supabase.table("evaluation_response", jwt=jwt).insert({
            "participant_id": request.participant_id,
            "video_id": request.video_id,
            "shown_as_A": request.shown_as_A,
            "ratings_A": request.ratings_A,
            "ratings_B": request.ratings_B,
            "preference": request.preference,
            "preference_reason": request.preference_reason,
            "profile_version_used": request.profile_version_used
        })
        return {"status": "success"}
    except Exception as e:
        print(f"Evaluation submit error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to submit evaluation: {e}")

# ---------------------------------------------------------------------------
# KNOWLEDGE GRAPH ENDPOINTS
# ---------------------------------------------------------------------------

@api_router.get("/graph")
async def get_knowledge_graph(user_id: str = Depends(get_current_user), jwt: Optional[str] = Depends(get_current_jwt)):
    """
    Returns the user's full persistent Knowledge Graph.
    Explicit user_id filter on every Supabase call + RLS enforced via forwarded JWT.
    """
    if user_id == "default_user":
        raise HTTPException(status_code=401, detail="Authentication required to access your Knowledge Graph.")
    try:
        full_graph = graph_service.fetch_full_graph(user_id, jwt=jwt)
        return full_graph
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to load Knowledge Graph.")


from pydantic import BaseModel, field_validator, UUID4

class GraphFeedbackRequest(BaseModel):
    concept_id: UUID4
    correct: bool
    
    @field_validator("concept_id")
    @classmethod
    def convert_uuid_to_str(cls, v) -> str:
        return str(v)


@api_router.post("/graph/feedback")
async def update_graph_mastery(
    request: GraphFeedbackRequest,
    user_id: str = Depends(get_current_user),
    jwt: Optional[str] = Depends(get_current_jwt)
):
    """
    Updates the mastery_score of a specific concept via EWMA.
    Validates that the concept belongs to the requesting user before writing.
    """
    if user_id == "default_user":
        raise HTTPException(status_code=401, detail="Authentication required.")
        
    # RATE LIMITING
    if not await check_rate_limit(user_id, limit=30, window=60):
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Please wait a minute.")
        
    try:
        result = graph_service.update_mastery(
            user_id=user_id,
            concept_id=request.concept_id,
            correct=request.correct,
            jwt=jwt
        )
        return {"status": "success", **result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to update mastery score.")

import re
import urllib.parse
from services.frame_extraction import extract_frame_at_timestamp
from services.vision_client import explain_frame_with_vision
from services.supabase_client import supabase

class FrameExplainRequest(BaseModel):
    video_id: str
    timestamp: str
    is_youtube: bool

@api_router.post("/api/explain-frame")
async def explain_frame(
    request: FrameExplainRequest, 
    user_id: str = Depends(get_current_user)
):
    # RATE LIMITING (independent)
    if not await check_rate_limit(user_id, limit=10, window=60, prefix="explain_frame:"):
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Please wait a minute.")

    # Validate timestamp (HH:MM:SS, MM:SS, or float)
    if not re.match(r"^(\d{1,2}:\d{2}:\d{2}|\d{1,2}:\d{2}|\d+(\.\d+)?)$", request.timestamp):
        raise HTTPException(status_code=400, detail="Invalid timestamp format. Use HH:MM:SS, MM:SS, or seconds.")

    try:
        if request.is_youtube:
            # Resolve stream URL
            import redis
            import asyncio
            r = redis.Redis(host=os.getenv("REDIS_HOST", "localhost"), port=6379, db=0, decode_responses=True)
            url_hash = hashlib.md5(request.video_id.encode()).hexdigest()
            cache_key = f"ytdlp:resolved:{url_hash}"
            
            stream_url = r.get(cache_key)
            if not stream_url:
                cmd = ["yt-dlp", "-g", "-f", "bestvideo[height<=720]", f"https://www.youtube.com/watch?v={request.video_id}"]
                process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                stdout, stderr = await process.communicate()
                if process.returncode != 0:
                    raise Exception(f"Failed to resolve YouTube URL: {stderr.decode('utf-8', 'replace')}")
                stream_url = stdout.decode("utf-8").strip()
                
                # Try parsing expire from URL to cache
                try:
                    parsed_url = urllib.parse.urlparse(stream_url)
                    query_params = urllib.parse.parse_qs(parsed_url.query)
                    expire = int(query_params.get("expire", [0])[0])
                    import time
                    now = int(time.time())
                    ttl = max(0, expire - now - 300)
                    if ttl > 0:
                        r.setex(cache_key, ttl, stream_url)
                except Exception:
                    r.setex(cache_key, 3600, stream_url) # Fallback TTL
        else:
            # Local file upload check
            if not os.path.exists(request.video_id):
                raise HTTPException(status_code=404, detail="Local video file not found.")
            stream_url = request.video_id

        # Extract frame
        frame_path = await extract_frame_at_timestamp(stream_url, request.timestamp, is_remote=request.is_youtube)

        # Upload frame to Supabase storage if possible
        frame_url = None
        if supabase and supabase.url and supabase.key:
            try:
                dest_path = f"{user_id}/{uuid.uuid4().hex}.jpg"
                frame_url = supabase.storage().upload("frames", frame_path, dest_path)
            except Exception as e:
                print(f"Failed to upload frame to Supabase: {e}")
        
        if not frame_url:
            with open(frame_path, "rb") as f:
                frame_b64 = base64.b64encode(f.read()).decode('utf-8')
                frame_url = f"data:image/jpeg;base64,{frame_b64}"

        # Get Explanation
        from services.profile import get_profile
        dynamic_extra = "Explain this frame clearly."
        vision_res = await explain_frame_with_vision(frame_path, user_id, dynamic_extra)
        
        # Cleanup
        try:
            os.remove(frame_path)
            os.rmdir(os.path.dirname(frame_path))
        except Exception:
            pass

        return {
            "explanation": vision_res["explanation"],
            "frame_url_or_base64": frame_url,
            "provider_used": vision_res["provider"]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
