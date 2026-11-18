"""关系库状态存储（对位 Java `StateDbPersistenceService` 的持久化语义）。

Java 的默认路径是 DB 持久化 + 异步批量落库 + Redis 丢失后从 DB 恢复。这里
交付同步版本：引擎本身是同步 callable 模型，存储随之同步；批量异步化是
吞吐优化，不影响正确性，留待有真实负载时再加。

列名对位 Java Liquibase schema（state_machine / business_id / current_state /
prev_state / curr_state / event_name / occurred_at / seq），另加
operator / remark / attributes 三列承载 Python StateHistory 的完整上下文
（Java 侧这些只存在于 Redis/context，落库会丢）。

`ReplicatingStateStorage` 提供双写 + 读穿恢复：写先主后备（备失败仅记日志，
主是权威）；读先主，主缺失或异常时读备——这就是「Redis 丢失后从 DB 恢复」。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
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
    delete,
    text,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine

from atlas_richie.statemachine_core import StateContext, StateHistory
from atlas_richie.statemachine_core.storage import SequenceAllocator, StateStorage

_log = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SqlAlchemyStateStorage:
    """Durable `StateStorage` + `SequenceAllocator` over a sync SQLAlchemy engine."""

    def __init__(
        self,
        engine: Engine | str,
        *,
        create_tables: bool = True,
        table_prefix: str = "statemachine_",
    ) -> None:
        self._engine = create_engine(engine) if isinstance(engine, str) else engine
        self._metadata = MetaData()
        self._current = Table(
            f"{table_prefix}state_current",
            self._metadata,
            Column("state_machine", String(128), primary_key=True),
            Column("business_id", BigInteger, primary_key=True),
            Column("current_state", String(128), nullable=False),
            Column("seq", BigInteger),
            Column("updated_at", DateTime(timezone=True), nullable=False),
        )
        self._history = Table(
            f"{table_prefix}state_history",
            self._metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("state_machine", String(128), nullable=False),
            Column("business_id", BigInteger, nullable=False),
            Column("prev_state", String(128)),
            Column("curr_state", String(128), nullable=False),
            Column("event_name", String(128)),
            Column("seq", BigInteger),
            Column("operator", String(128)),
            Column("remark", Text),
            Column("attributes", JSON),
            Column("occurred_at", DateTime(timezone=True), nullable=False),
        )
        self._sequence = Table(
            f"{table_prefix}sequence",
            self._metadata,
            Column("state_machine", String(128), primary_key=True),
            Column("business_id", BigInteger, primary_key=True),
            Column("value", BigInteger, nullable=False),
        )
        if create_tables:
            self._metadata.create_all(self._engine)

    @property
    def engine(self) -> Engine:
        return self._engine

    def _upsert(self, table: Table):
        """Dialect-specific insert: on_conflict_do_update is not generic."""
        if self._engine.dialect.name == "postgresql":
            return pg_insert(table)
        if self._engine.dialect.name == "sqlite":
            return sqlite_insert(table)
        raise NotImplementedError(
            f"upsert is not implemented for dialect {self._engine.dialect.name!r}; "
            "use PostgreSQL or SQLite, or extend _upsert"
        )

    # ── StateStorage ────────────────────────────────────────────────

    def save_current_state(
        self, state_machine_name: str, business_id: int, current_state: str, context: StateContext
    ) -> None:
        stmt = self._upsert(self._current).values(
            state_machine=state_machine_name,
            business_id=business_id,
            current_state=current_state,
            seq=context.get_attribute("seq"),
            updated_at=_now(),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["state_machine", "business_id"],
            set_={
                "current_state": stmt.excluded.current_state,
                "seq": stmt.excluded.seq,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        with self._engine.begin() as connection:
            connection.execute(stmt)

    def get_current_state(self, state_machine_name: str, business_id: int) -> str | None:
        stmt = select(self._current.c.current_state).where(
            self._current.c.state_machine == state_machine_name,
            self._current.c.business_id == business_id,
        )
        with self._engine.connect() as connection:
            row = connection.execute(stmt).first()
        return row[0] if row else None

    def save_state_history(
        self,
        state_machine_name: str,
        business_id: int,
        from_state: str | None,
        to_state: str,
        event: str | None,
        context: StateContext,
    ) -> None:
        stmt = insert(self._history).values(
            state_machine=state_machine_name,
            business_id=business_id,
            prev_state=from_state,
            curr_state=to_state,
            event_name=event,
            seq=context.get_attribute("seq"),
            operator=context.get_attribute("operator"),
            remark=context.get_attribute("remark"),
            attributes=dict(context.attributes),
            occurred_at=_now(),
        )
        with self._engine.begin() as connection:
            connection.execute(stmt)

    def get_state_history(self, state_machine_name: str, business_id: int) -> list[StateHistory]:
        stmt = (
            select(self._history)
            .where(
                self._history.c.state_machine == state_machine_name,
                self._history.c.business_id == business_id,
            )
            .order_by(self._history.c.id)
        )
        with self._engine.connect() as connection:
            rows = connection.execute(stmt).mappings().all()
        return [
            StateHistory(
                state_machine_name=row["state_machine"],
                business_id=row["business_id"],
                from_state=row["prev_state"],
                to_state=row["curr_state"],
                event=row["event_name"],
                seq=row["seq"],
                operator=row["operator"],
                remark=row["remark"],
                attributes=dict(row["attributes"] or {}),
                create_time=row["occurred_at"],
                id=row["id"],
            )
            for row in rows
        ]

    def delete_state(self, state_machine_name: str, business_id: int) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                delete(self._current).where(
                    self._current.c.state_machine == state_machine_name,
                    self._current.c.business_id == business_id,
                )
            )
            connection.execute(
                delete(self._history).where(
                    self._history.c.state_machine == state_machine_name,
                    self._history.c.business_id == business_id,
                )
            )

    # ── SequenceAllocator ───────────────────────────────────────────

    def next_seq(self, state_machine_name: str, business_id: int) -> int:
        """Atomic counter via INSERT .. ON CONFLICT DO UPDATE .. RETURNING.

        Works on PostgreSQL and SQLite (3.35+); the upsert is a single
        statement so concurrent allocators cannot observe a torn value.
        """
        table = self._sequence
        stmt = text(
            f"INSERT INTO {table.name} (state_machine, business_id, value) "
            "VALUES (:machine, :business, 1) "
            "ON CONFLICT (state_machine, business_id) "
            f"DO UPDATE SET value = {table.name}.value + 1 "
            "RETURNING value"
        )
        with self._engine.begin() as connection:
            row = connection.execute(
                stmt, {"machine": state_machine_name, "business": business_id}
            ).first()
        return int(row[0])

    def close(self) -> None:
        self._engine.dispose()


class ReplicatingStateStorage:
    """Dual-write primary/replica with read-through recovery.

    Writes go to the primary first; a replica failure is logged, not raised —
    the primary is authoritative and a transition must not fail because the
    backup is down. Reads try the primary and fall back to the replica when
    the primary returns nothing OR raises: that is the Redis-loss recovery
    path (evicted key or dead Redis both heal from the durable replica).
    """

    def __init__(self, primary: StateStorage, replica: StateStorage) -> None:
        self._primary = primary
        self._replica = replica

    def save_current_state(self, state_machine_name, business_id, current_state, context) -> None:
        self._primary.save_current_state(state_machine_name, business_id, current_state, context)
        try:
            self._replica.save_current_state(state_machine_name, business_id, current_state, context)
        except Exception:  # noqa: BLE001 — 备库故障不得让迁移失败
            _log.exception(
                "replica save_current_state failed; machine=%s business=%s",
                state_machine_name, business_id,
            )

    def get_current_state(self, state_machine_name: str, business_id: int) -> str | None:
        try:
            value = self._primary.get_current_state(state_machine_name, business_id)
        except Exception:  # noqa: BLE001 — 主库不可达时从备库恢复
            _log.exception(
                "primary get_current_state failed; machine=%s business=%s",
                state_machine_name, business_id,
            )
            value = None
        if value is not None:
            return value
        return self._replica.get_current_state(state_machine_name, business_id)

    def save_state_history(self, state_machine_name, business_id, from_state, to_state, event, context) -> None:
        self._primary.save_state_history(state_machine_name, business_id, from_state, to_state, event, context)
        try:
            self._replica.save_state_history(state_machine_name, business_id, from_state, to_state, event, context)
        except Exception:  # noqa: BLE001
            _log.exception(
                "replica save_state_history failed; machine=%s business=%s",
                state_machine_name, business_id,
            )

    def get_state_history(self, state_machine_name: str, business_id: int) -> list[StateHistory]:
        try:
            history = self._primary.get_state_history(state_machine_name, business_id)
        except Exception:  # noqa: BLE001
            _log.exception("primary get_state_history failed; machine=%s", state_machine_name)
            history = []
        if history:
            return history
        return self._replica.get_state_history(state_machine_name, business_id)

    def delete_state(self, state_machine_name: str, business_id: int) -> None:
        self._primary.delete_state(state_machine_name, business_id)
        try:
            self._replica.delete_state(state_machine_name, business_id)
        except Exception:  # noqa: BLE001
            _log.exception("replica delete_state failed; machine=%s", state_machine_name)


__all__ = ["SqlAlchemyStateStorage", "ReplicatingStateStorage"]