import os
import datetime
import json
from typing import Dict, Any, List, Optional
from services.supabase_client import supabase

def get_profile(user_id: str = "default_user", jwt: Optional[str] = None) -> Dict[str, Any]:
    """Fetches user profile from Supabase with default fallback."""
    default_prof = {"user_id": user_id, "persona_blueprint": "", "instructions": [], "support_level": 0, "preferred_length": "default", "preferred_format": "bullets", "profile_version": 1, "feedback_count": 0}
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

    allowed_keys = ["user_id", "persona_blueprint", "instructions", "support_level", "preferred_length", "preferred_format", "profile_version", "feedback_count"]
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


def refine_persona_with_ai(user_id: str, feedback_type: str, custom_feedback: str = "", jwt: Optional[str] = None) -> str:
    """
    Uses the Groq LLM to intelligently rewrite the persona blueprint based on
    negative feedback while STRICTLY preserving all key user details.
    Returns the new blueprint text.
    """
    profile = get_profile(user_id, jwt=jwt)
    current_blueprint = profile.get("persona_blueprint", "").strip()

    if not current_blueprint:
        current_blueprint = "The user is a high-level intellectual seeking deep synthesis."

    # Map feedback type to a clear instruction
    feedback_instructions = {
        "too_long": "The user felt the output was TOO LONG. Rewrite the persona to explicitly request shorter, more concise, and to-the-point responses. Add a clear instruction like 'Keep responses brief and dense.'",
        "too_technical": "The user felt the output was TOO TECHNICAL. Rewrite the persona to request simpler language, fewer jargon terms, and clearer analogies. Add an instruction to explain concepts in accessible terms.",
        "wrong_format": "The user felt the output had the WRONG FORMAT. Rewrite the persona to be more flexible about formatting, requesting a clean structure (e.g., prefer paragraph flow over heavy bullet points, or vice versa). Add a clear formatting preference.",
        "other": f"The user has provided this custom feedback: '{custom_feedback}'. Incorporate this feedback by adjusting the persona accordingly."
    }

    instruction = feedback_instructions.get(feedback_type, feedback_instructions["other"])
    if feedback_type == "other" and not custom_feedback:
        instruction = "The user gave negative feedback. Make the persona slightly more accessible and clear."

    refine_prompt = f"""You are an expert at writing AI persona blueprints for learning assistants.

The user's CURRENT persona blueprint is:
---
{current_blueprint}
---

FEEDBACK TO ADDRESS:
{instruction}

YOUR TASK:
Rewrite the persona blueprint to address the feedback while STRICTLY PRESERVING all key details the user defined: their background, academic level, subject area, goals, and any specific instructions they gave.

DO NOT remove, dilute, or generalize any key identifying information.
DO NOT add new assumptions about the user that weren't in the original.
ONLY make targeted changes that address the feedback.
Keep the rewritten persona at a similar length or shorter.
Write ONLY the new persona text — no explanations, no labels, no preamble."""

    try:
        from groq import Groq
        groq_key = os.getenv("GROQ_API_KEY", "")
        if not groq_key or "your_groq" in groq_key:
            raise Exception("Groq not configured")
        client = Groq(api_key=groq_key)
        completion = client.chat.completions.create(
            messages=[{"role": "user", "content": refine_prompt}],
            model="openai/gpt-oss-120b",
            max_tokens=800,
        )
        refined = completion.choices[0].message.content.strip()
        print(f"[profile] AI refined persona for user {user_id} (feedback: {feedback_type})")
        return refined
    except Exception as e:
        print(f"[profile] AI refinement failed: {e}, using heuristic fallback")
        # Heuristic fallback
        additions = {
            "too_long": "\n\nIMPORTANT: Keep all responses concise and brief. Avoid lengthy elaborations.",
            "too_technical": "\n\nIMPORTANT: Use simple, accessible language. Avoid heavy jargon. Explain terms clearly.",
            "wrong_format": "\n\nIMPORTANT: Prefer clean paragraph prose over dense bullet lists. Use clear structure.",
        }
        addition = additions.get(feedback_type, f"\n\nNote: {custom_feedback}" if custom_feedback else "")
        return current_blueprint + addition

def update_preference(user_id: str, level: str, rating: str, jwt: Optional[str] = None):
    """Evolve Persona: Derives behaviors from ratings."""
    profile = get_profile(user_id, jwt=jwt)
    if rating == "up":
        # Decrease support level (increase detail), min 0
        profile["support_level"] = max(0, profile.get("support_level", 0) - 1)
    elif rating == "down":
        pass # Handle general down if necessary
    elif rating == "too_long":
        profile["preferred_length"] = "shorter"
    elif rating == "too_technical":
        # Increase support level (simplify content)
        profile["support_level"] = profile.get("support_level", 0) + 1
    elif rating == "wrong_format":
        current_format = profile.get("preferred_format", "bullets")
        profile["preferred_format"] = "paragraph" if current_format == "bullets" else "bullets"

    profile["profile_version"] = profile.get("profile_version", 0) + 1
    profile["feedback_count"] = profile.get("feedback_count", 0) + 1

    trigger_event = f"Feedback applied: rating={rating}, level={level}"
    save_profile(user_id, profile, trigger_event=trigger_event, jwt=jwt)

def get_master_prompt(user_id: str, dynamic_extra: str = "", jwt: Optional[str] = None) -> str:
    """THE MASTER PROMPT ENGINE"""
    profile = get_profile(user_id, jwt=jwt)
    blueprint = profile.get("persona_blueprint", "")
    learned = profile.get("instructions", [])
    support_level = profile.get("support_level", 0)
    preferred_length = profile.get("preferred_length", "default")
    preferred_format = profile.get("preferred_format", "bullets")

    prompt = "## CORE PERSONA BLUEPRINT\n"
    if blueprint:
        prompt += f"{blueprint}\n"
    else:
        prompt += "The user is a high-level intellectual seeking deep synthesis.\n"

    prompt += "\n## PERSONALIZATION SETTINGS:\n"
    prompt += f"- Support Level (Complexity Reduction): {support_level} (Higher = Simpler Vocabulary/Concepts)\n"
    prompt += f"- Preferred Length: {preferred_length}\n"
    prompt += f"- Preferred Format: {preferred_format}\n"

    if learned:
        prompt += "\n## REFINED BEHAVIORAL PATTERNS (LEARNED):\n"
        for l in learned:
            prompt += f"- {l}\n"

    if dynamic_extra:
        prompt += f"\n## DYNAMIC USER INTENT:\n{dynamic_extra}\n"

    prompt += "\n## OPERATING PROTOCOLS:\n1. Prioritize structural logic.\n2. Assume high baseline intelligence.\n3. Adjust vocabulary based on Support Level.\n4. Follow Preferred Length and Format strictly."
    return prompt

def get_system_instructions(user_id: str = "default_user") -> str:
    return get_master_prompt(user_id)
