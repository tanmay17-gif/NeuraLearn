import os
import datetime
from typing import Dict, Any, List, Optional
from services.supabase_client import supabase

def get_profile(user_id: str = "default_user", jwt: Optional[str] = None) -> Dict[str, Any]:
    """Fetches user profile from Supabase with default fallback."""
    default_prof = {"user_id": user_id, "persona_blueprint": "", "instructions": [], "maturity_score": 0, "profile_version": 1, "feedback_count": 0}
    if not supabase:
        return default_prof

    try:
        table = supabase.table("profiles", jwt=jwt) if jwt else supabase.table("profiles")
        response = table.select("*").eq("user_id", user_id).execute()
        if response.data:
            prof = response.data[0]
            prof.setdefault("profile_version", 1)
            prof.setdefault("feedback_count", 0)
            return prof
        else:
            return default_prof
    except Exception as e:
        print(f"Supabase Profile Fetch Error: {e}")
        return default_prof

def save_profile(user_id: str, profile: Dict[str, Any], trigger_event: str = "Profile updated", jwt: Optional[str] = None):
    """Updates user profile in Supabase and records history."""
    if not supabase:
        print("[profile] No supabase client — skipping save.")
        return

    allowed_keys = ["user_id", "persona_blueprint", "instructions", "maturity_score", "profile_version", "feedback_count"]
    clean_profile = {k: v for k, v in profile.items() if k in allowed_keys}
    clean_profile["last_updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

    try:
        upsert_table = supabase.table("profiles", jwt=jwt) if jwt else supabase.table("profiles")
        result = upsert_table.upsert(clean_profile, on_conflict="user_id")
        print(f"[profile] Saved profile for {user_id}: version={clean_profile.get('profile_version')}, trigger={trigger_event}")

        history_record = {
            "user_id": user_id,
            "profile_snapshot": clean_profile,
            "profile_version": clean_profile.get("profile_version", 1),
            "trigger_event": trigger_event
        }
        hist_table = supabase.table("profile_history", jwt=jwt) if jwt else supabase.table("profile_history")
        hist_table.insert(history_record)
        print(f"[profile] History snapshot saved for {user_id}")

        return result
    except Exception as e:
        print(f"[profile] Supabase Save Error for user {user_id}: {e}")
        raise

def update_persona_blueprint(user_id: str, blueprint: str, jwt: Optional[str] = None):
    """Sets the core identity of the user."""
    print(f"[profile] Updating persona blueprint for user {user_id}")
    profile = get_profile(user_id, jwt=jwt)
    profile["persona_blueprint"] = blueprint
    profile["profile_version"] = profile.get("profile_version", 0) + 1
    profile["feedback_count"] = profile.get("feedback_count", 0) + 1
    save_profile(user_id, profile, trigger_event="Updated persona blueprint", jwt=jwt)
    print(f"[profile] Blueprint updated successfully for user {user_id}")

def update_preference(user_id: str, level: str, rating: str, jwt: Optional[str] = None):
    """Evolve Persona: Derives behaviors from ratings."""
    profile = get_profile(user_id, jwt=jwt)
    if rating == "down":
        behavior_map = {
            "beginner": "Avoid over-simplification. Use precise analogies.",
            "intermediate": "Increase technical density. Focus on architecture.",
            "expert": "Deeper synthesis required. Assume mastery of basics."
        }
        new_instruction = behavior_map.get(level, "Refine tone for higher technical precision.")
        if "instructions" not in profile: profile["instructions"] = []
        if new_instruction not in profile["instructions"]:
            profile["instructions"].append(new_instruction)

    profile["maturity_score"] = profile.get("maturity_score", 0) + 1
    profile["profile_version"] = profile.get("profile_version", 0) + 1
    profile["feedback_count"] = profile.get("feedback_count", 0) + 1

    trigger_event = f"Feedback applied: rating={rating}, level={level}"
    save_profile(user_id, profile, trigger_event=trigger_event, jwt=jwt)

def get_master_prompt(user_id: str, dynamic_extra: str = "", jwt: Optional[str] = None) -> str:
    """THE MASTER PROMPT ENGINE"""
    profile = get_profile(user_id, jwt=jwt)
    blueprint = profile.get("persona_blueprint", "")
    learned = profile.get("instructions", [])

    prompt = "## CORE PERSONA BLUEPRINT\n"
    if blueprint:
        prompt += f"{blueprint}\n"
    else:
        prompt += "The user is a high-level intellectual seeking deep synthesis.\n"

    if learned:
        prompt += "\n## REFINED BEHAVIORAL PATTERNS (LEARNED):\n"
        for l in learned:
            prompt += f"- {l}\n"

    if dynamic_extra:
        prompt += f"\n## DYNAMIC USER INTENT:\n{dynamic_extra}\n"

    prompt += "\n## OPERATING PROTOCOLS:\n1. Prioritize structural logic.\n2. Assume high baseline intelligence.\n3. Maintain Blueprint tone."
    return prompt

def get_system_instructions(user_id: str = "default_user") -> str:
    return get_master_prompt(user_id)
