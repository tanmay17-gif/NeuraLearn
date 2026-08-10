"""
graph.py — Persistent Knowledge Graph service.

Handles:
  - Fetching a user's existing concept graph from Supabase
  - LLM-based semantic concept merging (deduplication)
  - Persisting new nodes/edges and video-concept timestamp links
  - Mastery score updates via EWMA on flashcard feedback
"""

import json
from typing import Any, Dict, List, Optional, Tuple
from groq import Groq
from services.supabase_client import supabase
import os

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY")) if os.getenv("GROQ_API_KEY") else None

# ---------------------------------------------------------------------------
# FETCH
# ---------------------------------------------------------------------------

def fetch_user_concepts(user_id: str, jwt: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return recent concept nodes for a user (capped at 300 for LLM deduplication)."""
    try:
        result = supabase.table("concepts", jwt=jwt).select("id,label").eq("user_id", user_id).limit(300).execute()
        return result.data or []
    except Exception as e:
        print(f"[graph] fetch_user_concepts error: {e}")
        return []


def fetch_full_graph(user_id: str, jwt: Optional[str] = None) -> Dict[str, Any]:
    """Return the full graph (concepts + edges) for the global view."""
    try:
        concepts = supabase.table("concepts", jwt=jwt).select("*").eq("user_id", user_id).execute().data or []
        # Fetch edges where either side belongs to this user via user_id column
        edges = supabase.table("concept_edges", jwt=jwt).select("*").eq("user_id", user_id).execute().data or []

        # Attach video_concepts to each concept node for timestamp/visual data
        for concept in concepts:
            try:
                vc = (
                    supabase.table("video_concepts", jwt=jwt)
                    .select("video_id,timestamp_seconds,visual_insight")
                    .eq("concept_id", concept["id"])
                    .execute()
                    .data or []
                )
                concept["video_links"] = vc
                # Use the earliest timestamp as the default seek target
                with_ts = [v for v in vc if v.get("timestamp_seconds")]
                concept["timestamp_seconds"] = with_ts[0]["timestamp_seconds"] if with_ts else 0
            except Exception:
                concept["video_links"] = []
                concept["timestamp_seconds"] = 0

        return {"nodes": concepts, "edges": edges}
    except Exception as e:
        print(f"[graph] fetch_full_graph error: {e}")
        return {"nodes": [], "edges": []}


# ---------------------------------------------------------------------------
# CONCEPT MATCHING (LLM-based deduplication)
# ---------------------------------------------------------------------------

def _build_merge_prompt(new_nodes: List[Dict], existing_labels: List[Dict]) -> str:
    existing_str = json.dumps([{"id": e["id"], "label": e["label"]} for e in existing_labels], indent=2)
    new_str = json.dumps([{"id": n["id"], "label": n["label"]} for n in new_nodes], indent=2)
    MERGE_THRESHOLD = os.getenv("CONCEPT_MERGE_THRESHOLD", ">85% semantic similarity")
    return f"""
You are a knowledge graph deduplication engine.

EXISTING CONCEPTS (already in the user's graph):
{existing_str}

NEW CONCEPTS (just extracted from a new video):
{new_str}

TASK: For each NEW concept, decide if it is semantically the same as an EXISTING concept.
- "Machine Learning" and "ML" are the same.
- "Neural Networks" and "Deep Learning" are NOT the same.
- Use semantic judgment, not just string matching.

Return a valid JSON object:
{{
    "matches": [
        {{"new_id": "new_concept_id", "existing_id": "uuid-of-matching-existing-concept"}}
    ]
}}

Only include pairs where you are confident ({MERGE_THRESHOLD}).
If no matches exist, return: {{"matches": []}}
"""


def find_concept_matches(
    new_nodes: List[Dict], existing_concepts: List[Dict]
) -> Dict[str, str]:
    """
    Returns a dict mapping new_node_id -> existing_concept_id for detected duplicates.
    Uses Groq LLM. Falls back to empty dict (no merging) on failure.
    """
    if not groq_client or not existing_concepts or not new_nodes:
        return {}
    try:
        prompt = _build_merge_prompt(new_nodes, existing_concepts)
        completion = groq_client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.3-70b-versatile",
            response_format={"type": "json_object"},
            max_tokens=512,
        )
        data = json.loads(completion.choices[0].message.content)
        matches = data.get("matches", [])
        return {m["new_id"]: m["existing_id"] for m in matches if "new_id" in m and "existing_id" in m}
    except Exception as e:
        print(f"[graph] concept matching LLM error: {e}")
        return {}


# ---------------------------------------------------------------------------
# PERSIST
# ---------------------------------------------------------------------------

def persist_graph(
    user_id: str,
    video_id: str,
    extracted: Dict[str, Any],
    visual_insights_by_label: Optional[Dict[str, str]] = None,
    jwt: Optional[str] = None
) -> Dict[str, Any]:
    """
    Merges and persists extracted nodes/edges into the Supabase Postgres graph.

    Returns:
        {
            "merged": int,   # concepts that matched an existing node
            "new": int,      # concepts that were inserted fresh
            "edges_added": int,
        }
    """
    raw_nodes: List[Dict] = extracted.get("nodes", [])
    raw_edges: List[Dict] = extracted.get("edges", [])
    visual_insights = visual_insights_by_label or {}
    
    print(f"[graph] persist_graph started. Received {len(raw_nodes)} raw nodes and {len(raw_edges)} raw edges.")

    if not raw_nodes:
        print("[graph] No raw nodes found, returning 0s")
        return {"merged": 0, "new": 0, "edges_added": 0}

    # 1. Fetch existing concepts for this user
    existing_concepts = fetch_user_concepts(user_id, jwt=jwt)

    # 2. Run LLM-based merging to find duplicates
    merge_map: Dict[str, str] = find_concept_matches(raw_nodes, existing_concepts)
    # merge_map: { extracted_node_id -> existing_supabase_concept_id }

    # 3. Build a local mapping: extracted_node_id -> final supabase concept_id
    id_map: Dict[str, str] = {}
    merged_count = 0
    new_count = 0

    for node in raw_nodes:
        node_id = node["id"]

        if node_id in merge_map:
            # This node merges into an existing concept
            final_id = merge_map[node_id]
            id_map[node_id] = final_id
            merged_count += 1
        else:
            # Insert as a new concept
            try:
                row = {
                    "user_id": user_id,
                    "label": node.get("label", node_id),
                    "description": node.get("description", ""),
                    "mastery_score": 0,
                }
                result = supabase.table("concepts", jwt=jwt).upsert(row, on_conflict="user_id,label").execute()
                print(f"[graph] upsert result for '{row['label']}': {result.data}")
                if result.data:
                    final_id = result.data[0]["id"]
                    id_map[node_id] = final_id
                    new_count += 1
                else:
                    print(f"[graph] WARNING: no data returned from upsert for '{row['label']}'")
            except Exception as e:
                print(f"[graph] concept insert error for '{node.get('label')}': {e}")
                continue

    # 4. Insert video_concepts (timestamp + visual links) for each concept
    for node in raw_nodes:
        node_id = node["id"]
        concept_db_id = id_map.get(node_id)
        if not concept_db_id:
            continue
        label = node.get("label", "")
        visual_insight = visual_insights.get(label.lower(), None)
        try:
            vc_row = {
                "concept_id": concept_db_id,
                "video_id": video_id,
                "timestamp_seconds": node.get("timestamp_seconds", 0),
                "visual_insight": visual_insight,
            }
            supabase.table("video_concepts", jwt=jwt).insert(vc_row).execute()
        except Exception as e:
            print(f"[graph] video_concepts insert error: {e}")

    # 5. Insert edges — resolve both sides to supabase concept IDs
    edges_added = 0
    for edge in raw_edges:
        from_id = id_map.get(edge.get("source_id", ""))
        to_id = id_map.get(edge.get("target_id", ""))
        if not from_id or not to_id:
            continue
        try:
            edge_row = {
                "user_id": user_id,
                "from_concept_id": from_id,
                "to_concept_id": to_id,
                "relationship_type": edge.get("relationship", "relates to"),
            }
            supabase.table("concept_edges", jwt=jwt).upsert(
                edge_row, on_conflict="from_concept_id,to_concept_id"
            ).execute()
            edges_added += 1
        except Exception as e:
            print(f"[graph] edge insert error: {e}")

    return {"merged": merged_count, "new": new_count, "edges_added": edges_added}


# ---------------------------------------------------------------------------
# VISION GROUNDING
# ---------------------------------------------------------------------------

def map_vision_to_concepts(user_id: str, video_id: str, vision_markdown: str, jwt: Optional[str] = None):
    """
    Takes a generated visual analysis report and attempts to map its insights
    to the existing concepts for this video.
    Updates the `video_concepts` table with the `visual_insight`.
    """
    if not groq_client: return

    try:
        # Fetch existing concepts for this video
        vc_data = supabase.table("video_concepts", jwt=jwt).select("id, concept_id, concepts(label)").eq("video_id", video_id).execute().data
        if not vc_data: return

        concepts = [{"vc_id": row["id"], "label": row["concepts"]["label"]} for row in vc_data if row.get("concepts")]
        if not concepts: return

        concepts_str = json.dumps(concepts, indent=2)
        prompt = f"""
        You are an AI linking visual analysis to knowledge graph concepts.
        
        VISUAL ANALYSIS REPORT:
        {vision_markdown}
        
        AVAILABLE CONCEPTS FOR THIS VIDEO:
        {concepts_str}
        
        TASK:
        If any part of the visual analysis strongly supports or relates to an available concept, extract a concise "Visual Insight" (1-3 sentences describing the diagram/slide/code).
        
        Return a JSON mapping of video_concept IDs (vc_id) to the extracted visual insight.
        
        JSON Schema:
        {{
            "mappings": [
                {{ "vc_id": "uuid", "insight": "The diagram shows..." }}
            ]
        }}
        """
        completion = groq_client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.3-70b-versatile",
            response_format={"type": "json_object"},
            max_tokens=512,
        )
        data = json.loads(completion.choices[0].message.content)
        
        for mapping in data.get("mappings", []):
            vc_id = mapping.get("vc_id")
            insight = mapping.get("insight")
            if vc_id and insight:
                # Direct update bypassing user_id since vc_id is unique, but it's safe since it's a backend automated process
                supabase.table("video_concepts", jwt=jwt).eq("id", vc_id).update({"visual_insight": insight}).execute()

    except Exception as e:
        print(f"[graph] vision mapping error: {e}")

# ---------------------------------------------------------------------------
# MASTERY SCORING (EWMA)
# ---------------------------------------------------------------------------

EWMA_DECAY = 0.8       # Weight on existing score
EWMA_LEARN = 0.2       # Weight on new signal
CORRECT_SIGNAL = 100
INCORRECT_SIGNAL = 0

def update_mastery(user_id: str, concept_id: str, correct: bool, jwt: Optional[str] = None) -> Dict[str, Any]:
    """
    Applies an EWMA update to the concept's mastery_score.
    Also validates that the concept belongs to the requesting user.

    Returns updated concept data or raises on validation failure.
    """
    # Fetch concept — explicit user_id filter prevents IDOR even if RLS has a gap
    try:
        result = (
            supabase.table("concepts", jwt=jwt)
            .select("id,mastery_score,label")
            .eq("id", str(concept_id))
            .eq("user_id", user_id)
            .execute()
        )
    except Exception as e:
        raise ValueError("Failed to fetch concept for mastery update.")

    if not result.data:
        raise ValueError("Concept not found or does not belong to this user.")

    concept = result.data[0]
    old_score = concept.get("mastery_score", 0) or 0
    signal = CORRECT_SIGNAL if correct else INCORRECT_SIGNAL
    new_score = round(old_score * EWMA_DECAY + signal * EWMA_LEARN)
    new_score = max(0, min(100, new_score))  # Clamp to [0, 100]

    try:
        supabase.table("concepts", jwt=jwt).eq("id", str(concept_id)).eq("user_id", user_id).update(
            {"mastery_score": new_score}
        ).execute()
    except Exception as e:
        raise ValueError("Failed to update mastery score.")

    return {
        "concept_id": concept_id,
        "label": concept.get("label"),
        "old_score": old_score,
        "new_score": new_score,
    }
