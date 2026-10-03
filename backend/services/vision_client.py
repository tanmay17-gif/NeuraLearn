import os
import asyncio
import time
import base64
import logging
from typing import Dict, Any, Optional
from groq import AsyncGroq
import google.genai as genai
from google.genai import types as genai_types
from services.profile import get_master_prompt

logger = logging.getLogger(__name__)

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

async def explain_frame_with_vision(
    image_path: str,
    user_id: str,
    dynamic_extra: str = "",
    jwt: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Explains a video frame using Gemini with Groq Vision as a fallback.
    """
    system_prompt = get_master_prompt(user_id, dynamic_extra, jwt=jwt)
    base64_image = encode_image(image_path)

    provider_errors = []
    api_key = os.getenv("GOOGLE_API_KEY")
    if api_key:
        client = genai.Client(api_key=api_key)

        def _call_gemini():
            return client.models.generate_content(
                model="gemini-3.5-flash-lite",
                contents=[
                    system_prompt,
                    "Explain this frame in detail. What is being shown? "
                    "(e.g. diagram, code, slide, chart)",
                    genai_types.Part(
                        inline_data=genai_types.Blob(
                            mime_type="image/jpeg",
                            data=base64.b64decode(base64_image),
                        )
                    ),
                ],
            )

        for attempt in range(2):
            try:
                response = await asyncio.to_thread(_call_gemini)
                explanation = (response.text or "").strip()
                if explanation:
                    return {"explanation": explanation, "provider": "gemini"}
                raise RuntimeError("Gemini returned an empty frame explanation.")
            except Exception as error:
                provider_errors.append(f"Gemini: {error}")
                status_code = getattr(error, "status_code", None)
                is_transient = status_code in {408, 429, 500, 502, 503, 504} or any(
                    marker in str(error).upper()
                    for marker in ("UNAVAILABLE", "RESOURCE_EXHAUSTED", "429")
                )
                if attempt == 0 and is_transient:
                    logger.warning(
                        "Gemini Vision returned a transient error; retrying once: %s",
                        error,
                    )
                    await asyncio.sleep(1)
                else:
                    logger.warning("Gemini Vision failed: %s", error)
                    break
    else:
        provider_errors.append("Gemini: GOOGLE_API_KEY is not configured")

    # Fall back to Groq Vision.
    if not groq_breaker.is_open():
        try:
            async with vision_groq_semaphore:
                groq_api_key = os.environ.get("GROQ_API_KEY")
                if not groq_api_key:
                    raise RuntimeError("GROQ_API_KEY is not configured")
                client = AsyncGroq(api_key=groq_api_key)
                response = await asyncio.wait_for(client.chat.completions.create(
                    model="qwen/qwen3.8-27b",
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
                ), timeout=30.0)
                
                explanation = response.choices[0].message.content
                if not explanation or not explanation.strip():
                    raise RuntimeError("Groq returned an empty frame explanation.")
                groq_breaker.record_success()
                return {"explanation": explanation.strip(), "provider": "groq"}
        except Exception as error:
            provider_errors.append(f"Groq: {error}")
            logger.exception("Groq Vision failed")
            groq_breaker.record_failure()
    else:
        provider_errors.append("Groq: vision circuit breaker is open")

    raise RuntimeError(
        "All vision providers failed. " + " | ".join(provider_errors)
    )
