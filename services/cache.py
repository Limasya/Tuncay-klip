"""
Redis caching layer for hot paths.
Wraps redis.asyncio with a simple get/set/delete API and decorator for automatic caching.
"""
import asyncio
import functools
import hashlib
import json
import logging
import os
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

_redis = None
_connected = False


async def _get_redis():
    global _redis, _connected
    if _redis is not None and _connected:
        return _redis
    try:
        import redis.asyncio as aioredis
        url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        _redis = aioredis.from_url(url, decode_responses=True, socket_connect_timeout=3, protocol=2)
        await asyncio.wait_for(_redis.ping(), timeout=3)
        _connected = True
        logger.info("Redis cache connected")
        return _redis
    except Exception as e:
        _connected = False
        _redis = None
        logger.debug("Redis cache unavailable: %s", e)
        return None


async def cache_get(key: str) -> Optional[Any]:
    r = await _get_redis()
    if r is None:
        return None
    try:
        raw = await r.get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as e:
        logger.debug("Cache get failed for key=%s: %s", key, e)
        return None


async def cache_set(key: str, value: Any, ttl: int = 300) -> bool:
    r = await _get_redis()
    if r is None:
        return False
    try:
        serialized = json.dumps(value, default=str)
        await r.setex(key, ttl, serialized)
        return True
    except Exception as e:
        logger.debug("Cache set failed for key=%s: %s", key, e)
        return False


async def cache_delete(pattern: str) -> int:
    r = await _get_redis()
    if r is None:
        return 0
    try:
        keys = []
        async for key in r.scan_iter(match=pattern):
            keys.append(key)
        if keys:
            return await r.delete(*keys)
        return 0
    except Exception as e:
        logger.debug("Cache delete failed for pattern=%s: %s", pattern, e)
        return 0


async def cache_clear_all() -> int:
    return await cache_delete("*")


def _make_cache_key(prefix: str, args: tuple, kwargs: dict) -> str:
    raw = json.dumps({"a": args, "k": kwargs}, default=str, sort_keys=True)
    h = hashlib.md5(raw.encode()).hexdigest()[:12]
    return f"klip:{prefix}:{h}"


def cached(prefix: str, ttl: int = 300):
    """Decorator that caches async function results in Redis."""
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Skip self/cls args for key
            key_args = args
            if args and hasattr(args[0], "__class__") and type(args[0]).__name__ in (
                "LLMEngine", "ClipSimilarityEngine", "ContentQualityScorer"
            ):
                key_args = args[1:]

            cache_key = _make_cache_key(prefix, key_args, kwargs)

            hit = await cache_get(cache_key)
            if hit is not None:
                logger.debug("Cache HIT: %s", cache_key)
                return hit

            result = await func(*args, **kwargs)
            if result is not None:
                await cache_set(cache_key, result, ttl=ttl)
            return result

        wrapper.invalidate = lambda *a, **kw: cache_delete(
            _make_cache_key(prefix, a, kw)
        )
        return wrapper
    return decorator
