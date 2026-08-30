"""
Cache and Redis Integration

Provides Redis client and caching utilities.
"""

import json
from typing import Any, Optional

import aioredis
from app.core.config import settings

# Global Redis client
redis_client: Optional[aioredis.Redis] = None


async def init_redis():
    """Initialize Redis client."""
    global redis_client
    if redis_client is None:
        redis_client = await aioredis.from_url(settings.REDIS_URL, decode_responses=True)


async def close_redis():
    """Close Redis client."""
    global redis_client
    if redis_client:
        await redis_client.close()


async def get_cache(key: str) -> Optional[Any]:
    """Get value from cache."""
    if not redis_client:
        return None

    value = await redis_client.get(key)
    if value:
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return None


async def set_cache(key: str, value: Any, ttl: Optional[int] = None) -> bool:
    """Set value in cache."""
    if not redis_client:
        return False

    if ttl is None:
        ttl = settings.REDIS_CACHE_DEFAULT_TTL

    if isinstance(value, dict) or isinstance(value, list):
        value = json.dumps(value)

    await redis_client.setex(key, ttl, str(value))
    return True


async def delete_cache(key: str) -> bool:
    """Delete value from cache."""
    if not redis_client:
        return False

    await redis_client.delete(key)
    return True


async def clear_cache_pattern(pattern: str) -> int:
    """Clear all keys matching pattern."""
    if not redis_client:
        return 0

    keys = await redis_client.keys(pattern)
    if keys:
        return await redis_client.delete(*keys)
    return 0
