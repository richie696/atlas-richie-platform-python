"""降级判定器（对位 Java `DegradeInterceptor` 的判定部分）。

`4.7.6 **为什么不是一个拦截器**：Java 的 `DegradeInterceptor` 是链上的一个元素，
因为 Java 的链尾就是业务执行——降级发生在「业务跑完、响应还没写出」的窗口里。
Python 的拦截器链在 app **之前**就跑完了，链内拦截器**看不到业务结果**，因此
降级判定被拆成**框架无关的 evaluator**：`detect trigger → select strategy →
build result`，由适配层在「包住 app 调用的位置」接入。

`4.7.7 Java 的 Bean 反射降级（`fallbackBean` / `fallbackMethod`）未移植；
`4.7.8 Java 的响应体用 `ApiResult.error(code, msg).toJson()` 序列化，本移植
按同样的 JSON 形状输出（`{"success":false,"code":...,"msg":...}`），但不依赖
`ApiResult` 契约类。
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from ..rate_limit import ant_pattern_to_regex
from ..spi import WebRequestContext
from .config import DegradeConfig, Fallback, RouteFallback
from .model import DegradeResult, DegradeStrategy, Trigger
from .registry import DegradeStrategyRegistry

# 业务写入：跳过本次降级（`true`）。
ATTR_SKIP = "degrade.skip"

# 业务写入：触发 `Trigger.EXCEPTION`（异常对象）。
ATTR_EXCEPTION = "degrade.exception"

# 业务写入：触发 `Trigger.CUSTOM`（`true`）。
ATTR_MANUAL = "degrade.manual"

# 业务写入：触发 `Trigger.HIGH_LATENCY` 的耗时（毫秒）。
ATTR_LATENCY_MS = "degrade.latencyMs"

# 命中策略的 attribute key。
ATTR_HIT_STRATEGY = "degrade.hit_strategy"

# 高延迟阈值（毫秒），超此值视为 `Trigger.HIGH_LATENCY`。
DEFAULT_LATENCY_THRESHOLD_MS = 3000

# 全局兜底命中时的策略名标记。
STRATEGY_NAME_FALLBACK = "<fallback>"

# path 路由命中时的策略名标记。
STRATEGY_NAME_ROUTE = "<route>"


def _is_ant_pattern(pattern: str | None) -> bool:
    """是否含 Ant 通配符（对位 Java `pattern.contains("*") || ... || contains("{")`）。"""
    if not pattern:
        return False
    return "*" in pattern or "?" in pattern or "{" in pattern


def ant_match(pattern: str, path: str) -> bool:
    """Ant 风格路径匹配（对位 Java `AntPathMatcher.match`）。

    `4.7.9 复用仓内已有的 `ant_pattern_to_regex`（`**` 跨目录、`*` / `?` 不跨
    `/`、`{var}` 为一段）。**补一条 Java 语义**：`/api/**` 在 Java 里能匹配
    `/api`（零段），正则要求至少一个字符，故这里额外放行「去掉尾部 `/**` 的
    前缀」本身。
    """
    if ant_pattern_to_regex(pattern).match(path):
        return True
    if pattern.endswith("/**"):
        return path == pattern[:-3]
    return False


class DegradeEvaluator:
    """降级判定器（框架无关）。

    `4.7.10 判定流程（与 Java `DegradeInterceptor.evaluate` 逐条对齐）：

    1. 读 `degrade.skip`：为 true 则跳过（业务显式豁免）
    2. 匹配 path 路由；`require_route_match` 为真且**未命中**则不降级
       （Java 的降级是「受保护接口」的业务策略）
    3. 计算 trigger：`degrade.manual` → CUSTOM，`degrade.exception` →
       EXCEPTION，`degrade.latencyMs` 超阈值 → HIGH_LATENCY
    4. 查注册表：命中则调策略 `build`，并写 `degrade.hit_strategy`
    5. 未命中策略 → 用路由配置生成响应（策略名 `<route>`）
    6. 路由也没有 → 用全局兜底生成响应（策略名 `<fallback>`）
    """

    def __init__(
        self,
        registry: DegradeStrategyRegistry,
        config: DegradeConfig | None = None,
        latency_threshold_ms: int = DEFAULT_LATENCY_THRESHOLD_MS,
        *,
        require_route_match: bool = True,
    ) -> None:
        if registry is None:
            raise ValueError("registry must not be None")
        self._registry = registry
        self._config = config if config is not None else DegradeConfig()
        self._latency_threshold_ms = latency_threshold_ms
        self._require_route_match = require_route_match

    @property
    def registry(self) -> DegradeStrategyRegistry:
        return self._registry

    @property
    def config(self) -> DegradeConfig:
        return self._config

    @property
    def latency_threshold_ms(self) -> int:
        return self._latency_threshold_ms

    def evaluate(self, ctx: WebRequestContext) -> DegradeResult | None:
        """执行降级判定；命中则写短路并返回结果，未命中返回 None。"""
        if ctx.attribute(ATTR_SKIP) is True:
            return None

        route = self.match_route(ctx.path)
        if route is None and self._require_route_match:
            return None

        trigger = self.detect_trigger(ctx)
        if trigger is None:
            return None

        hit = self._registry.select(trigger)
        if hit is not None:
            result = hit.build(trigger, self.ctx_snapshot(ctx, trigger))
            ctx.set_attribute(ATTR_HIT_STRATEGY, hit.name())
        else:
            result = self._route_or_fallback(ctx, trigger, route)
        self._apply(ctx, result)
        return result

    def detect_trigger(self, ctx: WebRequestContext) -> Trigger | None:
        """计算本轮触发条件（对位 Java `detectTrigger`）。"""
        if ctx.attribute(ATTR_MANUAL) is True:
            return Trigger.CUSTOM
        exception = ctx.attribute(ATTR_EXCEPTION)
        if isinstance(exception, BaseException):
            return Trigger.EXCEPTION
        latency = ctx.attribute(ATTR_LATENCY_MS)
        if isinstance(latency, (int, float)) and not isinstance(latency, bool):
            if int(latency) > self._latency_threshold_ms:
                return Trigger.HIGH_LATENCY
        return None

    def match_route(self, path: str | None) -> RouteFallback | None:
        """匹配 path 对应的路由降级配置。

        优先级：`route_rules` 列表（精确 → Ant）→ `routes` 映射（精确 → Ant）。
        与 Java `matchRoute` 一致。
        """
        if not path:
            return None
        for rule in self._config.route_rules:
            if path == rule.pattern:
                return rule
        for rule in self._config.route_rules:
            if _is_ant_pattern(rule.pattern) and ant_match(rule.pattern, path):
                return rule
        routes = self._config.routes
        exact = routes.get(path)
        if exact is not None:
            return exact
        for pattern, rule in routes.items():
            if _is_ant_pattern(pattern) and ant_match(pattern, path):
                return rule
        return None

    def ctx_snapshot(self, ctx: WebRequestContext, trigger: Trigger) -> dict[str, Any]:
        """给策略的上下文快照（对位 Java `ctxSnapshot`）。"""
        snapshot: dict[str, Any] = {"path": ctx.path}
        exception = ctx.attribute(ATTR_EXCEPTION)
        if isinstance(exception, BaseException):
            snapshot["exception"] = exception
            snapshot["exceptionType"] = (
                f"{type(exception).__module__}.{type(exception).__qualname__}"
            )
            snapshot["exceptionMessage"] = str(exception)
        latency = ctx.attribute(ATTR_LATENCY_MS)
        if isinstance(latency, (int, float)) and not isinstance(latency, bool):
            snapshot["latencyMs"] = int(latency)
        snapshot["trigger"] = trigger
        return snapshot

    def _route_or_fallback(
        self,
        ctx: WebRequestContext,
        trigger: Trigger,
        route: RouteFallback | None,
    ) -> DegradeResult:
        if route is not None:
            ctx.set_attribute(ATTR_HIT_STRATEGY, STRATEGY_NAME_ROUTE)
            return self._build_result(
                route.status,
                route.code,
                route.msg,
                trigger,
                route.headers,
                STRATEGY_NAME_ROUTE,
            )
        ctx.set_attribute(ATTR_HIT_STRATEGY, STRATEGY_NAME_FALLBACK)
        fallback: Fallback = self._config.fallback
        return self._build_result(
            fallback.status,
            fallback.code,
            fallback.msg,
            trigger,
            fallback.headers,
            STRATEGY_NAME_FALLBACK,
        )

    @staticmethod
    def _build_result(
        status: int,
        code: str,
        msg_template: str,
        trigger: Trigger,
        headers: Mapping[str, str] | None,
        strategy_name: str,
    ) -> DegradeResult:
        """按配置生成降级响应体。

        `4.7.11 body 形状与 Java 的 `ApiResult.error(code, msg).toJson()` 一致：
        `{"success":false,"code":...,"msg":...}`。`{reason}` 占位符替换为触发
        条件的小写名（`exception` / `high-latency` / `custom`）。
        """
        message = msg_template.replace("{reason}", trigger.reason)
        body = json.dumps(
            {"success": False, "code": code, "msg": message},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return DegradeResult(
            status=status,
            body=body,
            strategy_name=strategy_name,
            headers=dict(headers or {}),
        )

    @staticmethod
    def _apply(ctx: WebRequestContext, result: DegradeResult) -> None:
        """把降级结果落到 ctx（响应头 + 短路标记）。"""
        for name, value in (result.headers or {}).items():
            ctx.add_response_header(name, value)
        ctx.mark_short_circuit(result.status, result.body)


__all__ = [
    "ATTR_EXCEPTION",
    "ATTR_HIT_STRATEGY",
    "ATTR_LATENCY_MS",
    "ATTR_MANUAL",
    "ATTR_SKIP",
    "DEFAULT_LATENCY_THRESHOLD_MS",
    "DegradeEvaluator",
    "STRATEGY_NAME_FALLBACK",
    "STRATEGY_NAME_ROUTE",
    "ant_match",
]
