import os
import asyncio
import time
import base64
from typing import Dict, Any, Optional
from groq import AsyncGroq
import google.genai as genai
from google.genai import types as genai_types
from services.profile import get_master_prompt

# Circuit breaker state
class CircuitBreaker:
    def __init__(self, failure_threshold: int = 3, cooldown_sec: int = 60):
        self.failure_threshold = failure_threshold
        self.cooldown_sec = cooldown_sec
        self.failures = 0
        self.last_failure_time = 0.0

    def record_failure(self):
        self.failures += 1
        self.last_failure_time = time.time()

    def record_success(self):
        self.failures = 0

    def is_open(self) -> bool:
        if self.failures >= self.failure_threshold:
            if time.time() - self.last_failure_time < self.cooldown_sec:
                return True
            else:
                # Half-open state
                return False
        return False

groq_breaker = CircuitBreaker()
# Isolated semaphore for Groq calls (since user chose to keep it isolated)
vision_groq_semaphore = asyncio.Semaphore(int(os.getenv("GROQ_VISION_CONCURRENCY", "5")))

def encode_image(image_path: str) -> str:
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

async def explain_frame_with_vision(image_path: str, user_id: str, dynamic_extra: str = "") -> Dict[str, Any]:
    """
    Explains a video frame using Groq Vision with fallback to Gemini.
    """
    system_prompt = get_master_prompt(user_id, dynamic_extra)
    base64_image = encode_image(image_path)
    
    # 1. Try Groq Vision
    if not groq_breaker.is_open():
        try:
            async with vision_groq_semaphore:
                client = AsyncGroq(api_key=os.environ.get("GROQ_API_KEY"))
                response = await asyncio.wait_for(client.chat.completions.create(
                    model="llama-3.2-11b-vision-preview",
                    messages=[
                        {
                            "role": "system",
                            "content": system_prompt
                        },
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "Explain this frame in detail. What is being shown? (e.g. diagram, code, slide, chart)"},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/jpeg;base64,{base64_image}",
                                    }
                                }
                            ]
                        }
                    ],
                    temperature=0.2,
                    max_tokens=1024,
                ), timeout=8.0)
                
                explanation = response.choices[0].message.content
                groq_breaker.record_success()
                return {"explanation": explanation, "provider": "groq"}
        except Exception as e:
            print(f"[vision_client] Groq Vision failed: {e}")
            groq_breaker.record_failure()
    else:
        print("[vision_client] Groq Vision circuit breaker is open, skipping to Gemini fallback.")

    # 2. Fallback to Gemini 2.0 Flash
    try:
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise Exception("No GOOGLE_API_KEY available for Gemini fallback.")
            
        client = genai.Client(api_key=api_key)
        
        def _call_gemini():
            return client.models.generate_content(
                model="gemini-2.0-flash",
                contents=[
                    system_prompt,
                    "Explain this frame in detail. What is being shown? (e.g. diagram, code, slide, chart)",
                    genai_types.Part(
                        inline_data=genai_types.Blob(
                            mime_type="image/jpeg",
                            data=base64.b64decode(base64_image)
                        )
                    )
                ]
            )
            
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, _call_gemini)
        explanation = response.text.strip()
        return {"explanation": explanation, "provider": "gemini"}
    except Exception as e:
        print(f"[vision_client] Gemini Vision fallback failed: {e}")
        raise Exception("All vision providers failed.")
