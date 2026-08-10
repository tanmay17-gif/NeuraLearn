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
from services.profile import update_preference, get_profile, update_persona_blueprint
from services.supabase_client import verify_auth_token
from services.cache import get_cached_synthesis, set_cached_synthesis, check_rate_limit
from services import graph as graph_service

api_router = APIRouter()
security = HTTPBearer(auto_error=False)

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

class ModuleRequest(BaseModel):
    video_id: str
    transcript: str
    video_url: Optional[str] = None
    level: Optional[str] = "intermediate"
    dynamic_extra: Optional[str] = ""

class FeedbackRequest(BaseModel):
    video_id: str
    module: str
    rating: str
    level: str

class ProcessingResponse(BaseModel):
    video_id: str
    title: str
    summary: List[str]
    transcript: str
    custom_insights: Optional[str] = None

@api_router.post("/upload")
async def upload_video(
    file: UploadFile = File(...),
    level: str = Form("intermediate"),
    dynamic_extra: str = Form(""),
    user_id: str = Depends(get_current_user)
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
            
        from services.profile import get_master_prompt
        master_prompt = get_master_prompt(user_id, dynamic_extra)

        result = await engine.process_uploaded_video(file_path, master_prompt=master_prompt)
        os.remove(file_path)
        
        save_to_memory(
            video_id=f"upload_{safe_filename}",
            title=f"Uploaded: {file.filename}",
            content=" ".join(result["summary"]),
            user_id=user_id
        )

        return ProcessingResponse(
            video_id=f"upload_{safe_filename}",
            title=file.filename,
            summary=result["summary"],
            transcript=result["transcript"],
            custom_insights=result["custom_insights"]
        )
    except Exception as e:
        if file_path:
            try:
                if os.path.exists(file_path): os.remove(file_path)
            except Exception:
                pass
        raise HTTPException(status_code=500, detail="Video processing failed.")

@api_router.post("/process", response_model=ProcessingResponse)
async def process_video(request: VideoRequest, user_id: str = Depends(get_current_user)):
    # RATE LIMITING
    if not await check_rate_limit(user_id, limit=10, window=60):
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Please wait a minute.")

    # CACHING
    cache_key = f"process:{hashlib.md5((request.url + request.level + request.dynamic_extra + user_id).encode()).hexdigest()}"
    cached = await get_cached_synthesis(cache_key)
    if cached:
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
        
        from services.profile import get_master_prompt
        master_prompt = get_master_prompt(user_id, request.dynamic_extra)

        engine_result = await engine.generate_summary_with_prompt(
            transcript_data["text"], 
            master_prompt=master_prompt
        )
        
        summary = engine_result["summary"]
        custom_insights = engine_result["custom_insights"]
        
        content_to_save = " ".join(summary)
        if custom_insights:
            content_to_save += f"\n\nCUSTOM SYNTHESIS:\n{custom_insights}"

        save_to_memory(
            video_id=transcript_data["video_id"],
            title=transcript_data["title"],
            content=content_to_save,
            user_id=user_id
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
async def save_feedback(request: FeedbackRequest, user_id: str = Depends(get_current_user)):
    update_preference(user_id, request.level, request.rating)
    return {"status": "success"}


@api_router.get("/profile/{target_user_id}")
async def get_user_profile(target_user_id: str, current_user_id: str = Depends(get_current_user)):
    if target_user_id != current_user_id and current_user_id != "default_user":
        raise HTTPException(status_code=403, detail="Not authorized to view this profile.")
    return get_profile(target_user_id)


@api_router.post("/profile/custom")
async def set_custom_instructions(request: Dict[str, str], user_id: str = Depends(get_current_user)):
    try:
        blueprint = request.get("blueprint", "")
        print(f"[profile/custom] Saving blueprint for user {user_id}: '{blueprint[:60]}...' ({len(blueprint)} chars)")
        update_persona_blueprint(user_id, blueprint)
        return {"status": "success"}
    except Exception as e:
        print(f"[profile/custom] ERROR for user {user_id}: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save persona: {str(e)}")


@api_router.post("/search")
async def search_knowledge(request: Dict[str, Any], user_id: str = Depends(get_current_user)):
    query = request.get("query", "")
    results = search_memory(query, user_id=user_id)
    return {"results": results}


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
