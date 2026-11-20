"""降级策略 SPI（对位 Java `web.core.degrade` 包）。"""

from .config import DegradeConfig, Fallback, RouteFallback
from .evaluator import (
    ATTR_EXCEPTION,
    ATTR_HIT_STRATEGY,
    ATTR_LATENCY_MS,
    ATTR_MANUAL,
    ATTR_SKIP,
    DEFAULT_LATENCY_THRESHOLD_MS,
    STRATEGY_NAME_FALLBACK,
    STRATEGY_NAME_ROUTE,
    DegradeEvaluator,
    ant_match,
)
from .model import DegradeResult, DegradeStrategy, Trigger
from .registry import DefaultDegradeStrategyRegistry, DegradeStrategyRegistry

__all__ = [
    "ATTR_EXCEPTION",
    "ATTR_HIT_STRATEGY",
    "ATTR_LATENCY_MS",
    "ATTR_MANUAL",
    "ATTR_SKIP",
    "DEFAULT_LATENCY_THRESHOLD_MS",
    "STRATEGY_NAME_FALLBACK",
    "STRATEGY_NAME_ROUTE",
    "DegradeConfig",
    "DegradeEvaluator",
    "DegradeResult",
    "DegradeStrategy",
    "DegradeStrategyRegistry",
    "DefaultDegradeStrategyRegistry",
    "Fallback",
    "RouteFallback",
    "Trigger",
    "ant_match",
]
