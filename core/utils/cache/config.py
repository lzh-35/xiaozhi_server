"""缓存配置"""

from enum import Enum


class CacheType(Enum):
    """缓存类型"""
    CONFIG = "config"
    WEATHER = "weather"
    LUNAR = "lunar"
