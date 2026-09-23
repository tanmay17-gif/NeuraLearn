from typing import Dict, Any, List
from services.supabase_client import supabase

def save_to_memory(video_id: str, title: str, content: str, user_id: str = "default_user", profile_version_used: int = None):
    """Saves video knowledge to Supabase — no embeddings needed."""
    if not supabase: return
    data = {
        "video_id": video_id,
        "title": title,
        "content": content[:500],  # trim for storage
        "user_id": user_id,
        "profile_version_used": profile_version_used
    }
    try:
        supabase.table("knowledge").upsert(data, on_conflict="video_id").execute()
    except Exception as e:
        print(f"Memory save note (non-critical): {e}")

def search_memory(query: str, top_k: int = 3, user_id: str = "default_user") -> List[Dict[str, Any]]:
    """Returns recent knowledge items — simplified without vector search."""
    if not supabase: return []
    try:
        response = supabase.table("knowledge").select("*").eq("user_id", user_id).execute()
        return [{"video_id": r["video_id"], "title": r["title"], "content": r["content"]} for r in (response.data or [])[:top_k]]
    except Exception as e:
        print(f"Memory fetch note (non-critical): {e}")
        return []
