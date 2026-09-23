import asyncio
import os
from dotenv import load_dotenv
load_dotenv()

from services.transcription import get_transcript_via_gemini

async def main():
    url = "https://www.youtube.com/watch?v=185XGEMe"
    print(f"Testing Gemini fallback with: {url}")
    result = await get_transcript_via_gemini(url)
    print("----- RESULT -----")
    if result:
        print(f"Success! Length: {len(result)}")
        print(result[:200] + "...")
    else:
        print("Failed (returned None)")

if __name__ == "__main__":
    asyncio.run(main())
