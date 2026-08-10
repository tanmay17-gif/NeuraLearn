import os
from typing import Dict, Any, List
from services.supabase_client import supabase

def get_profile(user_id: str = "default_user") -> Dict[str, Any]:
    """Fetches user profile from Supabase with default fallback."""
    if not supabase:
        return {"user_id": user_id, "persona_blueprint": "", "instructions": [], "maturity_score": 0}

    try:
        response = supabase.table("profiles").select("*").eq("user_id", user_id).execute()
        if response.data:
            return response.data[0]
        else:
            return {"user_id": user_id, "persona_blueprint": "", "instructions": [], "maturity_score": 0}
    except Exception as e:
        print(f"Supabase Profile Fetch Error: {e}")
        return {"user_id": user_id, "persona_blueprint": ""}

def save_profile(user_id: str, profile: Dict[str, Any]):
    """Updates user profile in Supabase. Only sends supported columns."""
    if not supabase: 
        print("[profile] No supabase client — skipping save.")
        return
    
    # CLEANING: Only send columns that definitely exist in the profiles table
    allowed_keys = ["user_id", "persona_blueprint", "instructions", "maturity_score"]
    clean_profile = {k: v for k, v in profile.items() if k in allowed_keys}
    
    try:
        result = supabase.table("profiles").upsert(clean_profile, on_conflict="user_id")
        print(f"[profile] Saved profile for {user_id}: {clean_profile}")
        return result
    except Exception as e:
        print(f"[profile] Supabase Save Error for user {user_id}: {e}")
        raise

def update_persona_blueprint(user_id: str, blueprint: str):
    """Sets the core identity of the user."""
    print(f"[profile] Updating persona blueprint for user {user_id}")
    profile = get_profile(user_id)
    profile["persona_blueprint"] = blueprint
    save_profile(user_id, profile)
    print(f"[profile] Blueprint updated successfully for user {user_id}")

def update_preference(user_id: str, level: str, rating: str):
    """Evolve Persona: Derives behaviors from ratings."""
    profile = get_profile(user_id)
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
    save_profile(user_id, profile)

def get_master_prompt(user_id: str, dynamic_extra: str = "") -> str:
    """THE MASTER PROMPT ENGINE"""
    profile = get_profile(user_id)
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
