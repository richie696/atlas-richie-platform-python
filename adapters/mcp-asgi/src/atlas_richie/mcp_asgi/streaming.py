"""In-process Streamable HTTP state owned by the ASGI transport adapter."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from threading import RLock
from typing import Any, cast

from atlas_richie.mcp import ProgressUpdate

JSON_RPC_VERSION = "2.0"
PROGRESS_NOTIFICATION_METHOD = "notifications/progress"
TOOLS_CHANGED_NOTIFICATION_METHOD = "notifications/tools/list_changed"
PROMPTS_CHANGED_NOTIFICATION_METHOD = "notifications/prompts/list_changed"
RESOURCES_CHANGED_NOTIFICATION_METHOD = "notifications/resources/list_changed"
RESOURCE_UPDATED_NOTIFICATION_METHOD = "notifications/resources/updated"
SUBSCRIPTION_ACKNOWLEDGED_NOTIFICATION_METHOD = "notifications/subscriptions/acknowledged"
SUBSCRIPTION_ID_META_KEY = "io.modelcontextprotocol/subscriptionId"
DEFAULT_EVENT_BUFFER_CAPACITY = 100
_CLOSE_EVENT = object()


@dataclass(frozen=True, slots=True)
class SubscriptionSpec:
    tools_list_changed: bool = False
    prompts_list_changed: bool = False
    resources_list_changed: bool = False
    resource_subscriptions: frozenset[str] = frozenset()


class ProgressEventReporter:
    """Validates and converts handler progress into MCP JSON-RPC notifications."""

    def __init__(self, token: str | int, publish: Callable[[Mapping[str, Any]], None]) -> None:
        self._token = token
        self._publish = publish
        self._last_progress = float("-inf")

    def report(self, update: ProgressUpdate) -> None:
        if update.progress < self._last_progress:
            raise ValueError("MCP progress must be monotonic")
        self._last_progress = update.progress
        params: dict[str, Any] = {"progressToken": self._token, "progress": update.progress}
        if update.total is not None:
            params["total"] = update.total
        if update.message:
            params["message"] = update.message
        self._publish(_notification(PROGRESS_NOTIFICATION_METHOD, params))


class Subscription:
    """A bounded, one-consumer notification channel tied to one SSE connection."""

    def __init__(self, identifier: str, spec: SubscriptionSpec, *, event_buffer_capacity: int) -> None:
        self.identifier = identifier
        self.spec = spec
        self._events: asyncio.Queue[Mapping[str, Any] | object] = asyncio.Queue(maxsize=event_buffer_capacity)
        self._closed = False

    def publish(self, event: Mapping[str, Any]) -> None:
        if self._closed:
            return
        try:
            self._events.put_nowait(dict(event))
        except asyncio.QueueFull:
            self.close()

    async def events(self) -> AsyncIterator[Mapping[str, Any]]:
        while not (self._closed and self._events.empty()):
            event = await self._events.get()
            if event is _CLOSE_EVENT:
                return
            yield cast(Mapping[str, Any], event)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._events.put_nowait(_CLOSE_EVENT)
        except asyncio.QueueFull:
            return


class SubscriptionManager:
    """Keeps adapter-local SSE subscriptions and publishes only requested changes."""

    def __init__(self, *, event_buffer_capacity: int = DEFAULT_EVENT_BUFFER_CAPACITY) -> None:
        if event_buffer_capacity <= 0:
            raise ValueError("event_buffer_capacity must be positive")
        self._event_buffer_capacity = event_buffer_capacity
        self._subscriptions: dict[str, Subscription] = {}
        self._lock = RLock()

    def open(self, identifier: str, spec: SubscriptionSpec) -> Subscription:
        with self._lock:
            if identifier in self._subscriptions:
                raise ValueError("MCP subscription identifier is already active")
            subscription = Subscription(identifier, spec, event_buffer_capacity=self._event_buffer_capacity)
            self._subscriptions[identifier] = subscription
            return subscription

    def close(self, identifier: str) -> None:
        with self._lock:
            subscription = self._subscriptions.pop(identifier, None)
        if subscription is not None:
            subscription.close()

    def tools_changed(self) -> None:
        self._publish_matching(lambda spec: spec.tools_list_changed, TOOLS_CHANGED_NOTIFICATION_METHOD)

    def prompts_changed(self) -> None:
        self._publish_matching(lambda spec: spec.prompts_list_changed, PROMPTS_CHANGED_NOTIFICATION_METHOD)

    def resources_changed(self) -> None:
        self._publish_matching(lambda spec: spec.resources_list_changed, RESOURCES_CHANGED_NOTIFICATION_METHOD)

    def resource_updated(self, uri: str) -> None:
        self._publish_matching(
            lambda spec: uri in spec.resource_subscriptions,
            RESOURCE_UPDATED_NOTIFICATION_METHOD,
            {"uri": uri},
        )

    def close_all(self) -> None:
        with self._lock:
            identifiers = tuple(self._subscriptions)
        for identifier in identifiers:
            self.close(identifier)

    def _publish_matching(
        self,
        matches: Callable[[SubscriptionSpec], bool],
        method: str,
        params: Mapping[str, Any] | None = None,
    ) -> None:
        with self._lock:
            subscriptions = tuple(self._subscriptions.values())
        for subscription in subscriptions:
            if matches(subscription.spec):
                subscription.publish(_subscription_notification(method, subscription.identifier, params or {}))


def parse_subscription_spec(value: object) -> SubscriptionSpec:
    if not isinstance(value, Mapping):
        raise ValueError("subscriptions/listen requires params.notifications")
    raw_resources = value.get("resourceSubscriptions", ())
    if not isinstance(raw_resources, list) or any(not isinstance(uri, str) or not uri for uri in raw_resources):
        raise ValueError("notifications.resourceSubscriptions must be an array of non-empty strings")
    return SubscriptionSpec(
        tools_list_changed=value.get("toolsListChanged") is True,
        prompts_list_changed=value.get("promptsListChanged") is True,
        resources_list_changed=value.get("resourcesListChanged") is True,
        resource_subscriptions=frozenset(raw_resources),
    )


def progress_token(params: Mapping[str, Any]) -> str | int | None:
    value = params.get("progressToken")
    if value is None and isinstance(params.get("_meta"), Mapping):
        value = params["_meta"].get("progressToken")
    if isinstance(value, bool) or not isinstance(value, str | int):
        return None
    return value


def subscription_acknowledged(identifier: str, notifications: Mapping[str, Any]) -> Mapping[str, Any]:
    return _subscription_notification(
        SUBSCRIPTION_ACKNOWLEDGED_NOTIFICATION_METHOD,
        identifier,
        {"notifications": dict(notifications)},
    )


def _notification(method: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
    return {"jsonrpc": JSON_RPC_VERSION, "method": method, "params": dict(params)}


def _subscription_notification(method: str, identifier: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
    return _notification(method, {**dict(params), "_meta": {SUBSCRIPTION_ID_META_KEY: identifier}})
