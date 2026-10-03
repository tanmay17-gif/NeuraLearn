import os
from google import genai
from typing import List
from dotenv import load_dotenv

load_dotenv()

# Configure Gemini
api_key = os.getenv("GOOGLE_API_KEY")
client = None
if api_key:
    client = genai.Client(api_key=api_key)

async def generate_quick_digest(transcript: str, level: str = "intermediate") -> List[str]:
    if not api_key or not client:
        return ["Error: GOOGLE_API_KEY not set in backend/.env", "Please add your API key to test summarization."]

    level_instructions = {
        "beginner": "Use simple language, explain analogies, and avoid technical jargon. Focus on 'What' and 'Why'.",
        "intermediate": "Maintain a balanced tone. Explain core concepts but assume basic familiarity with the topic.",
        "expert": "Use high-level technical terminology, focus on advanced insights, edge cases, and 'How' it works at a granular level. Do not over-explain basics."
    }

    instruction = level_instructions.get(level.lower(), level_instructions["intermediate"])

    prompt = f"""
    You are System X, a research-grade knowledge assistant.
    Provide a 5-bullet TLDR summary of the following video transcript.
    
    TARGET AUDIENCE LEVEL: {level.upper()}
    INSTRUCTIONS: {instruction}
    
    Focus on key insights, core arguments, and actionable takeaways relevant to this level.
    
    TRANSCRIPT:
    {transcript[:15000]}
    
    OUTPUT FORMAT:
    - Bullet 1
    - Bullet 2
    - Bullet 3
    - Bullet 4
    - Bullet 5
    """
    
    try:
        response = client.models.generate_content(
            model='gemini-3.8-flash',
            contents=prompt
        )
        
        # Parse bullets
        text = response.text
        bullets = [line.strip("- ").strip() for line in text.split('\n') if line.strip().startswith("-")]
        if not bullets:
            # Fallback if parsing fails
            return [line.strip() for line in text.split('\n') if line.strip()][:5]
        return bullets[:5]
    except Exception as e:
        return [f"Failed to generate summary: {str(e)}"]
