"""
Cache and Redis Integration

Provides Redis client and caching utilities.

Note: this uses `redis.asyncio` (the asyncio API shipped inside redis-py
>=4.2), not the standalone `aioredis` package. `aioredis` is deprecated
and unmaintained upstream, and on Python 3.11+ it fails at import time
with `TypeError: duplicate base class TimeoutError` (it defines its own
exception class that inherits from both `asyncio.TimeoutError` and the
builtin `TimeoutError`, which became the same class in 3.11).
"""

import json
from typing import Any, Optional

import redis.asyncio as redis

from app.core.config import settings

# Global Redis client
redis_client: Optional[redis.Redis] = None


async def init_redis() -> None:
    """Initialize Redis client."""
    global redis_client
    if redis_client is None:
        redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)


async def close_redis() -> None:
    """Close Redis client."""
    global redis_client
    if redis_client:
        await redis_client.close()
        redis_client = None


async def get_cache(key: str) -> Optional[Any]:
    """Get value from cache."""
    if not redis_client:
        return None

    value = await redis_client.get(key)
    if value is None:
        return None

    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


async def set_cache(key: str, value: Any, ttl: Optional[int] = None) -> bool:
    """Set value in cache."""
    if not redis_client:
        return False

    if ttl is None:
        ttl = settings.REDIS_CACHE_DEFAULT_TTL

    # Always store as JSON so any JSON-serializable value (dict, list,
    # bool, int, str, None) round-trips correctly through get_cache().
    await redis_client.setex(key, ttl, json.dumps(value))
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
        return int(await redis_client.delete(*keys))
    return 0
