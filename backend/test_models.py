import asyncio
import os
from dotenv import load_dotenv
load_dotenv()

import google.genai as genai

async def main():
    api_key = os.getenv("GOOGLE_API_KEY")
    client = genai.Client(api_key=api_key)
    
    for m in client.models.list():
        if "flash" in m.name:
            print(m.name)

if __name__ == "__main__":
    asyncio.run(main())
