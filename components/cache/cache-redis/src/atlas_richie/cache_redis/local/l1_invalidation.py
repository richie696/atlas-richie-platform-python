"""Cross-process L1 invalidation over the existing namespaced pub/sub.

`L2DistributedCache` keeps an in-process L1. Without a broadcast, a write on
instance A leaves instance B serving a stale L1 value until that entry's TTL
expires. This module fans out eviction notices so peers drop the affected L1
entry immediately.

Opt-in by design: subscribing opens a Redis connection and a daemon thread, so
the cache only builds a broadcaster when `notification_ops` is supplied.

Known limitation: `RedisNotificationListener` stops pumping when its connection
dies, so a Redis blip silently ends invalidation for that process. Coherence
then falls back to the L1 TTL (fail-open). Reconnect is a separate concern.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Callable

from atlas_richie.cache_core.ops.notification_ops import NotificationOps

_log = logging.getLogger(__name__)


class L1InvalidationBroadcaster:
    """Publishes local writes and evicts L1 on peer writes.

    Messages carry the publisher's instance id so a process ignores its own
    notice — its L1 is already correct, and evicting it would defeat the cache.
    """

    def __init__(
        self,
        notification_ops: NotificationOps,
        topic: str,
        on_evict: Callable[[str], None],
    ) -> None:
        self._ops = notification_ops
        self._topic = topic
        self._on_evict = on_evict
        self._instance_id = uuid.uuid4().hex
        self._listener = notification_ops.subscribe(topic, self._handle)

    @property
    def instance_id(self) -> str:
        return self._instance_id

    def publish_evict(self, key: str) -> None:
        """Best-effort fan-out; a failed broadcast must not fail the write."""
        try:
            self._ops.publish(self._topic, {"i": self._instance_id, "k": key})
        except Exception:  # noqa: BLE001 — coherence degrades to TTL, write stands
            _log.warning(
                "l1 invalidation publish failed for key=%r; peers fall back to TTL",
                key,
                exc_info=True,
            )

    def _handle(self, topic: str, message: Any) -> None:
        if not isinstance(message, dict):
            return
        if message.get("i") == self._instance_id:
            return
        key = message.get("k")
        if isinstance(key, str):
            self._on_evict(key)

    def close(self) -> None:
        self._listener.close()


__all__ = ["L1InvalidationBroadcaster"]
