import os
import json
from google import genai
from typing import List, Dict
from dotenv import load_dotenv

load_dotenv()

# Configure Gemini
api_key = os.getenv("GOOGLE_API_KEY")
client = None
if api_key:
    client = genai.Client(api_key=api_key)

async def generate_flashcards(transcript: str, level: str = "intermediate") -> List[Dict[str, str]]:
    """
    Generates adaptive flashcards based on the video transcript and user expertise level.
    """
    if not api_key or not client:
        return [{"question": "Error", "answer": "GOOGLE_API_KEY not set."}]

    level_prompts = {
        "beginner": "Create simple, conceptual questions focusing on 'What' and 'Why'. Avoid jargon.",
        "intermediate": "Create a mix of conceptual and technical questions. Focus on 'How' things work and relationships between concepts.",
        "expert": "Create deep technical questions, edge cases, and architectural inquiries. Focus on 'Trade-offs' and implementation details."
    }

    prompt = f"""
    You are System X, a specialized learning scientist.
    Based on the provided video transcript, generate a set of 5-7 high-quality flashcards.
    
    TARGET AUDIENCE LEVEL: {level.upper()}
    SPECIFIC FOCUS: {level_prompts.get(level.lower(), level_prompts['intermediate'])}
    
    OUTPUT FORMAT: JSON ONLY (a list of objects with 'question' and 'answer' keys).
    
    TRANSCRIPT:
    {transcript[:15000]}
    
    JSON:
    """

    try:
        response = client.models.generate_content(
            model='gemini-3.8-flash',
            contents=[prompt],
            config={
                'response_mime_type': 'application/json'
            }
        )
        
        cards = json.loads(response.text)
        if isinstance(cards, list):
            return cards
        elif isinstance(cards, dict) and "flashcards" in cards:
            return cards["flashcards"]
        return [{"question": "Could not parse flashcards", "answer": "Please try again."}]
    except Exception as e:
        return [{"question": f"Failed to generate: {str(e)}", "answer": "N/A"}]
