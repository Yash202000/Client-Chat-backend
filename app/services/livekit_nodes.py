"""
Which LiveKit node to use (high availability).

LIVEKIT_URLS lists the cluster's nodes (they share Redis, so a room on one node can be joined and
controlled through any node). The backend uses the first node that answers its health check, and gives
agents' browsers the matching public address (LIVEKIT_PUBLIC_URLS, same order). With only LIVEKIT_URL /
LIVEKIT_PUBLIC_URL set this is a single node, as before. Health results are cached for a few seconds.
"""
import logging
import threading
import time
import urllib.request
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

_CACHE_SECONDS = 5.0
_cache: dict[str, tuple[float, bool]] = {}
_lock = threading.Lock()


def _split(value: str) -> list[str]:
    return [u.strip() for u in (value or "").split(",") if u.strip()]


def nodes() -> list[str]:
    return _split(settings.LIVEKIT_URLS) or _split(settings.LIVEKIT_URL)


def public_nodes() -> list[str]:
    public = _split(settings.LIVEKIT_PUBLIC_URLS) or _split(settings.LIVEKIT_PUBLIC_URL)
    return public if len(public) == len(nodes()) else nodes()


def http_url(ws_url: str) -> str:
    return ws_url.replace("wss://", "https://").replace("ws://", "http://")


def healthy(ws_url: str) -> bool:
    now = time.monotonic()
    with _lock:
        hit = _cache.get(ws_url)
    if hit and now - hit[0] < _CACHE_SECONDS:
        return hit[1]
    ok = False
    try:
        with urllib.request.urlopen(http_url(ws_url).rstrip("/") + "/", timeout=1.0) as r:
            ok = r.status == 200
    except Exception:
        ok = False
    with _lock:
        before = _cache.get(ws_url)
        _cache[ws_url] = (now, ok)
    if before is not None and before[1] != ok:
        logger.warning(f"[livekit] node {ws_url} is {'up' if ok else 'DOWN'}")
    return ok


def _pick() -> int:
    all_nodes = nodes()
    if len(all_nodes) <= 1:
        return 0
    for i, url in enumerate(all_nodes):
        if healthy(url):
            return i
    return 0  # none answers: try the first anyway


def api_url() -> Optional[str]:
    """Server-side API address (http/https) of a healthy node."""
    all_nodes = nodes()
    return http_url(all_nodes[_pick()]) if all_nodes else None


def public_url() -> Optional[str]:
    """The address browsers should connect to (a healthy node)."""
    all_nodes = public_nodes()
    return all_nodes[_pick()] if all_nodes else None


def status() -> list[dict]:
    return [{"url": u, "healthy": healthy(u)} for u in nodes()]
