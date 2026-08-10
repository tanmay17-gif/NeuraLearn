import os
import json
import redis.asyncio as redis
from typing import Optional, Any
from dotenv import load_dotenv

load_dotenv()

UPSTASH_URL = os.getenv("UPSTASH_REDIS_URL", "").replace("https://", "rediss://")
UPSTASH_TOKEN = os.getenv("UPSTASH_REDIS_TOKEN", "")

# Depending on how Upstash URL is configured, we construct the redis connection string
if UPSTASH_URL and UPSTASH_TOKEN and "your_upstash" not in UPSTASH_TOKEN:
    # Upstash typically provides a connection string like rediss://default:token@endpoint:port
    # If the URL is just an endpoint, we might need to format it. But usually it's ready to go or just needs token.
    if "@" not in UPSTASH_URL:
        # Construct standard URI if token is separate
        clean_url = UPSTASH_URL.replace("rediss://", "")
        redis_uri = f"rediss://default:{UPSTASH_TOKEN}@{clean_url}"
    else:
        redis_uri = UPSTASH_URL
        
    redis_client = redis.from_url(redis_uri, decode_responses=True)
else:
    redis_client = None

async def get_cached_synthesis(cache_key: str) -> Optional[Any]:
    """Retrieves a cached synthesis from Upstash."""
    if not redis_client:
        return None
    try:
        data = await redis_client.get(cache_key)
        if data:
            return json.loads(data)
    except Exception as e:
        print(f"Redis Cache GET Error: {e}")
    return None

async def set_cached_synthesis(cache_key: str, data: Any, ttl: int = 86400):
    """Caches synthesis in Upstash for 24 hours."""
    if not redis_client:
        return
    try:
        await redis_client.setex(cache_key, ttl, json.dumps(data))
    except Exception as e:
        print(f"Redis Cache SET Error: {e}")

async def check_rate_limit(user_id: str, limit: int = 5, window: int = 60) -> bool:
    """
    Enforces a strict rate limit for video processing.
    Returns True if allowed, False if limit exceeded.
    """
    if not redis_client:
        return True # Fail open if no redis
        
    key = f"rate_limit:process:{user_id}"
    try:
        current = await redis_client.incr(key)
        if current == 1:
            await redis_client.expire(key, window)
            
        if current > limit:
            return False
            
        return True
    except Exception as e:
        print(f"Redis Rate Limit Error: {e}")
        return True # Fail open
