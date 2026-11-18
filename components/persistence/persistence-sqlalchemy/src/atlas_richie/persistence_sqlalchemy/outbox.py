"""事务性 outbox：业务写入与事件记录同事务落库，中继异步投递。

解决「写库成功但发消息失败」的双写不一致：事件先作为业务事务的一部分写入
outbox 表（同连接、同事务——业务回滚则事件也回滚），再由中继轮询未发布
事件投递到消息总线并标记已发布。投递失败只记 attempts/last_error，事件
保持未发布等待重试，因此至少一次投递；消费方需幂等（redis-streammq 的
IdempotencyGuard 正是为此）。

`OutboxStore.append` 接收**调用方的连接**而非自开事务——这是事务性保证的
关键：调用方在同一个事务里写业务表和 outbox，要么都提交要么都回滚。

中继可选 leader 门控（coordination 的 LeaderLease）：多实例部署时只有一个
实例投递，避免重复；未注入 lease 时单进程直接投递。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping

from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    insert,
    select,
    update,
    delete,
)
from sqlalchemy.engine import Connection, Engine

_log = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class OutboxEvent:
    id: int | None
    aggregate_type: str
    aggregate_id: str
    event_type: str
    payload: Mapping[str, Any]
    created_at: datetime
    published_at: datetime | None = None
    attempts: int = 0
    last_error: str | None = None


@dataclass(frozen=True, slots=True)
class RelayReport:
    fetched: int = 0
    published: int = 0
    failed: int = 0
    skipped: bool = False


class OutboxStore:
    def __init__(
        self,
        engine: Engine | str,
        *,
        create_table: bool = True,
        table_name: str = "outbox_events",
    ) -> None:
        self._engine = create_engine(engine) if isinstance(engine, str) else engine
        self._metadata = MetaData()
        self._table = Table(
            table_name,
            self._metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("aggregate_type", String(128), nullable=False),
            Column("aggregate_id", String(128), nullable=False),
            Column("event_type", String(128), nullable=False),
            Column("payload", JSON, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column("published_at", DateTime(timezone=True)),
            Column("attempts", Integer, nullable=False, default=0),
            Column("last_error", Text),
        )
        if create_table:
            self._metadata.create_all(self._engine)

    @property
    def engine(self) -> Engine:
        return self._engine

    @property
    def table(self) -> Table:
        return self._table

    def append(
        self,
        connection: Connection,
        *,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        payload: Mapping[str, Any],
    ) -> int:
        """Insert an event on the CALLER's connection/transaction.

        This is the transactional guarantee: the business write and the event
        insert share one transaction, so a business rollback also rolls back
        the event. Do not pass a fresh connection here.
        """
        if not aggregate_type or not aggregate_id or not event_type:
            raise ValueError("aggregate_type, aggregate_id and event_type are required")
        result = connection.execute(
            insert(self._table).values(
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                event_type=event_type,
                payload=dict(payload),
                created_at=_now(),
                attempts=0,
            )
        )
        return int(result.inserted_primary_key[0])

    def fetch_unpublished(self, limit: int = 100) -> list[OutboxEvent]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        stmt = (
            select(self._table)
            .where(self._table.c.published_at.is_(None))
            .order_by(self._table.c.id)
            .limit(limit)
        )
        with self._engine.connect() as connection:
            rows = connection.execute(stmt).mappings().all()
        return [self._to_event(row) for row in rows]

    def mark_published(self, event_id: int) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                update(self._table)
                .where(self._table.c.id == event_id)
                .values(published_at=_now(), last_error=None)
            )

    def mark_failed(self, event_id: int, error: str) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                update(self._table)
                .where(self._table.c.id == event_id)
                .values(
                    attempts=self._table.c.attempts + 1,
                    last_error=error[:2000],
                )
            )

    def purge_published(self, older_than: timedelta) -> int:
        cutoff = _now() - older_than
        with self._engine.begin() as connection:
            result = connection.execute(
                delete(self._table).where(
                    self._table.c.published_at.is_not(None),
                    self._table.c.published_at < cutoff,
                )
            )
            return int(result.rowcount or 0)

    def pending_count(self) -> int:
        with self._engine.connect() as connection:
            row = connection.execute(
                select(self._table.c.id).where(self._table.c.published_at.is_(None))
            ).all()
        return len(row)

    def _to_event(self, row) -> OutboxEvent:
        return OutboxEvent(
            id=row["id"],
            aggregate_type=row["aggregate_type"],
            aggregate_id=row["aggregate_id"],
            event_type=row["event_type"],
            payload=dict(row["payload"] or {}),
            created_at=row["created_at"],
            published_at=row["published_at"],
            attempts=row["attempts"],
            last_error=row["last_error"],
        )

    def close(self) -> None:
        self._engine.dispose()


class OutboxRelay:
    """Polls unpublished events and delivers them via an injected publisher."""

    def __init__(
        self,
        store: OutboxStore,
        publisher: Callable[[OutboxEvent], None],
        *,
        batch_size: int = 100,
        lease: Any = None,
    ) -> None:
        if not callable(publisher):
            raise ValueError("publisher must be callable")
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        self._store = store
        self._publisher = publisher
        self._batch_size = batch_size
        self._lease = lease
        self._scheduler: Any = None

    def relay_once(self) -> RelayReport:
        if self._lease is not None and not self._lease.is_leader:
            return RelayReport(skipped=True)
        events = self._store.fetch_unpublished(self._batch_size)
        published = failed = 0
        for event in events:
            try:
                self._publisher(event)
            except Exception as error:  # noqa: BLE001 — 投递失败留待重试，不中断批次
                failed += 1
                self._store.mark_failed(event.id, f"{type(error).__name__}: {error}")
                _log.warning(
                    "outbox publish failed; id=%s type=%s", event.id, event.event_type
                )
                continue
            self._store.mark_published(event.id)
            published += 1
        return RelayReport(fetched=len(events), published=published, failed=failed)

    def start(self, *, interval_seconds: float = 1.0) -> None:
        from atlas_richie.scheduling_core import Scheduler

        if self._scheduler is not None:
            return
        if self._lease is not None:
            self._lease.start()
        scheduler = Scheduler(name="outbox-relay")
        scheduler.schedule_fixed_delay(interval_seconds, self._relay_safely, name="relay")
        scheduler.start()
        self._scheduler = scheduler

    def stop(self, timeout: float | None = 5.0) -> None:
        scheduler = self._scheduler
        self._scheduler = None
        if scheduler is not None:
            scheduler.stop(timeout)
        if self._lease is not None:
            self._lease.stop(timeout)

    def _relay_safely(self) -> None:
        try:
            self.relay_once()
        except Exception:  # noqa: BLE001 — 一次中继失败不得杀死常驻循环
            _log.exception("outbox relay tick failed")

    def __enter__(self) -> OutboxRelay:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()


__all__ = ["OutboxEvent", "OutboxStore", "OutboxRelay", "RelayReport"]