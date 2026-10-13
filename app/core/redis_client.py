"""
Redis connections for the backend and the voice process (websocket fan-out, ACD dispatcher lock).

Either one Redis (REDIS_URL) or, for high availability, Redis Sentinel (REDIS_SENTINELS +
REDIS_SENTINEL_MASTER): the client asks the sentinels which server is the master and follows a
failover by itself (pub/sub listeners reconnect, see connection_manager).
"""
from app.core.config import settings


def redis_enabled() -> bool:
    return bool(settings.REDIS_SENTINELS or settings.REDIS_URL)


def describe() -> str:
    if settings.REDIS_SENTINELS:
        return f"sentinel {settings.REDIS_SENTINEL_MASTER}@{settings.REDIS_SENTINELS}"
    return settings.REDIS_URL


def async_redis(decode_responses: bool = False):
    import redis.asyncio as aioredis

    if settings.REDIS_SENTINELS:
        from redis.asyncio.sentinel import Sentinel

        nodes = []
        for addr in settings.REDIS_SENTINELS.split(","):
            if addr.strip():
                host, _, port = addr.strip().rpartition(":")
                nodes.append((host, int(port)))
        sentinel = Sentinel(nodes, socket_timeout=2,
                            sentinel_kwargs={"password": settings.REDIS_SENTINEL_PASSWORD or None, "socket_timeout": 2},
                            password=settings.REDIS_PASSWORD or None)
        return sentinel.master_for(settings.REDIS_SENTINEL_MASTER, decode_responses=decode_responses,
                                   socket_timeout=5, socket_connect_timeout=2)
    return aioredis.from_url(settings.REDIS_URL, decode_responses=decode_responses,
                             password=settings.REDIS_PASSWORD or None)
