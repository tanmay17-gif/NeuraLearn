import os
from google import genai
from typing import List, Dict
from dotenv import load_dotenv

load_dotenv()

# Configure Gemini
api_key = os.getenv("GOOGLE_API_KEY")
client = None
if api_key:
    client = genai.Client(api_key=api_key)

async def generate_structured_notes(transcript: str, level: str = "intermediate") -> str:
    """
    Generates structured, research-grade markdown notes from a transcript.
    """
    if not api_key or not client:
        return "Error: GOOGLE_API_KEY not set. Cannot generate structured notes."

    level_instructions = {
        "beginner": "Use simple language, explain analogies, and avoid technical jargon. Focus on 'What' and 'Why'.",
        "intermediate": "Maintain a balanced tone. Explain core concepts but assume basic familiarity with the topic.",
        "expert": "Use high-level technical terminology, focus on advanced insights, and detailed architectural/conceptual breakdowns. Assume high prior knowledge."
    }

    instruction = level_instructions.get(level.lower(), level_instructions["intermediate"])

    prompt = f"""
    You are System X, a research-grade knowledge assistant.
    Convert the following video transcript into high-quality, structured academic notes.
    
    TARGET AUDIENCE LEVEL: {level.upper()}
    INSTRUCTIONS: {instruction}
    
    RULES:
    1. Use Markdown formatting.
    2. Include a "Conceptual Overview" section.
    3. Use nested bullets for detailed explanations.
    4. Bold key technical terms.
    5. Add a "Glossary of Key Terms" at the end if applicable.
    6. Maintain a professional, academic tone.
    7. Use H3 and H4 headers for sub-sections.
    
    TRANSCRIPT:
    {transcript[:20000]}  # Increased limit for detailed notes
    
    OUTPUT: Structured Markdown Notes
    """
    
    try:
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt
        )
        return response.text
    except Exception as e:
        return f"Failed to generate structured notes: {str(e)}"
