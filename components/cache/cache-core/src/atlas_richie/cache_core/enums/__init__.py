"""Framework-shared enums (provider / key type / L2 region)."""

from __future__ import annotations

from .cache_provider import CacheProvider
from .key_type_enum import KeyTypeEnum
from .l2_caching_region import L2CachingRegion

__all__ = ["CacheProvider", "KeyTypeEnum", "L2CachingRegion"]
