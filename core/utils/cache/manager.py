"""全局缓存管理器（精简版）"""

import time
import threading
from typing import Any, Optional

from .strategies import CacheEntry
from .config import CacheType


class GlobalCacheManager:
    """全局缓存管理器 — 仅保留 CONFIG 类型的基本缓存"""

    def __init__(self):
        self._cache: dict = {}
        self._lock = threading.RLock()

    def set(
        self,
        cache_type: CacheType,
        key: str,
        value: Any,
        ttl: Optional[float] = None,
        **__,
    ) -> None:
        with self._lock:
            self._cache[(cache_type, key)] = CacheEntry(
                value=value, timestamp=time.time(), ttl=ttl
            )

    def get(
        self, cache_type: CacheType, key: str, **__
    ) -> Optional[Any]:
        with self._lock:
            entry = self._cache.get((cache_type, key))
            if entry is None:
                return None
            if entry.is_expired():
                del self._cache[(cache_type, key)]
                return None
            return entry.value


cache_manager = GlobalCacheManager()
