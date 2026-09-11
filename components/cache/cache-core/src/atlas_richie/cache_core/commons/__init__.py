"""Framework-shared value types (key utilities + geo result)."""

from __future__ import annotations

from .cache_key_utils import CacheKeyUtils
from .geo_point_result import GeoPointResult

__all__ = ["CacheKeyUtils", "GeoPointResult"]
