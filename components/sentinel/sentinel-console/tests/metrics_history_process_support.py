"""Spawn-safe workers for real Metrics V2 persistence fault tests."""

from __future__ import annotations

import asyncio
import hashlib
import multiprocessing
import time
from datetime import UTC, datetime

from atlas_richie.contracts.reporting.v2 import decode_metrics_snapshot
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine

from atlas_richie.sentinel_console.application.metrics_ingest_ports import (
    MetricsReporterBinding,
)
from atlas_richie.sentinel_console.infrastructure.persistence.metrics_history_store import (
    SQLAlchemyMetricsHistoryAdapter,
)
from atlas_richie.sentinel_console.infrastructure.persistence.metrics_reporter_admin_adapter import (
    SqlAlchemyMetricsReporterAdminAdapter,
)


def accept_snapshot_in_process(
    database_url: str,
    binding: MetricsReporterBinding,
    body: bytes,
    received_at: datetime,
    result_pipe,
    pause_after_commit,
    start_event,
    snapshot_inserted=None,
    continue_after_insert=None,
) -> None:
    """Write one real receipt and optionally pause inside its transaction."""

    async def accept():
        engine = create_async_engine(database_url, pool_size=1)

        async def resolve_engine():
            return engine

        listener = None
        if snapshot_inserted is not None and continue_after_insert is not None:

            def pause_after_snapshot_insert(
                connection, cursor, statement, parameters, context, executemany
            ) -> None:
                if "insert into console_metrics_snapshot" in statement.lower():
                    snapshot_inserted.set()
                    continue_after_insert.wait()

            listener = pause_after_snapshot_insert
            event.listen(engine.sync_engine, "after_cursor_execute", listener)
        try:
            store = SQLAlchemyMetricsHistoryAdapter(resolve_engine)
            receipt = await store.accept_snapshot(
                binding=binding,
                snapshot=decode_metrics_snapshot(body),
                body=body,
                body_sha256=hashlib.sha256(body).hexdigest(),
                received_at=received_at,
            )
            return receipt
        finally:
            if listener is not None:
                event.remove(engine.sync_engine, "after_cursor_execute", listener)
            await engine.dispose()

    try:
        if start_event is not None and not start_event.wait(timeout=30):
            raise TimeoutError("concurrent acceptance start barrier timed out")
        receipt = asyncio.run(accept())
        result_pipe.send(
            (
                receipt.reporter_id,
                str(receipt.startup_epoch),
                receipt.sequence,
                receipt.body_sha256,
                receipt.received_at.isoformat(),
            )
        )
        if pause_after_commit is not None:
            pause_after_commit.wait()
    except Exception as error:  # noqa: BLE001 - report only the child failure type.
        result_pipe.send(("worker_error", type(error).__name__))
    finally:
        result_pipe.close()


def terminate_after_uncommitted_snapshot_insert(
    *,
    database_url: str,
    binding: MetricsReporterBinding,
    body: bytes,
    received_at: datetime,
) -> None:
    """Kill a spawned writer after INSERT and prove no receipt escaped."""
    context = multiprocessing.get_context("spawn")
    parent_pipe, child_pipe = context.Pipe(duplex=False)
    snapshot_inserted = context.Event()
    continue_after_insert = context.Event()
    process = context.Process(
        target=accept_snapshot_in_process,
        args=(
            database_url,
            binding,
            body,
            received_at,
            child_pipe,
            None,
            None,
            snapshot_inserted,
            continue_after_insert,
        ),
    )
    process.start()
    child_pipe.close()
    try:
        if not snapshot_inserted.wait(timeout=30):
            if parent_pipe.poll():
                raise AssertionError(
                    f"writer exited before uncommitted INSERT: {parent_pipe.recv()!r}"
                )
            raise AssertionError("writer did not reach snapshot INSERT")
        if not process.is_alive():
            raise AssertionError("writer exited before the transaction was killed")
        if parent_pipe.poll(timeout=0.2):
            raise AssertionError("writer returned a receipt before transaction commit")
        process.terminate()
        process.join(timeout=10)
        if process.is_alive():
            process.kill()
            process.join(timeout=10)
            raise AssertionError("writer did not terminate at the transaction boundary")
        if parent_pipe.poll(timeout=0.1):
            try:
                message = parent_pipe.recv()
            except EOFError:
                message = None
            if message is not None:
                raise AssertionError(
                    f"writer produced data before termination: {message!r}"
                )
    finally:
        parent_pipe.close()
        if process.is_alive():
            process.terminate()
            process.join(timeout=10)


def revoke_reporter_in_process(
    database_url: str,
    certificate_principal: str,
    result_pipe,
    start_event=None,
    row_locked=None,
    continue_after_lock=None,
) -> None:
    """Revoke a reporter in a fresh process, optionally holding its row lock."""

    async def revoke() -> bool:
        engine = create_async_engine(database_url, pool_size=1)

        async def resolve_engine():
            return engine

        listener = None
        if row_locked is not None and continue_after_lock is not None:

            def pause_after_binding_update(
                connection, cursor, statement, parameters, context, executemany
            ) -> None:
                normalized = statement.lower()
                if (
                    normalized.startswith("update ")
                    and "console_metrics_reporter_binding" in normalized
                ):
                    row_locked.set()
                    continue_after_lock.wait()

            listener = pause_after_binding_update
            event.listen(engine.sync_engine, "after_cursor_execute", listener)
        try:
            return await SqlAlchemyMetricsReporterAdminAdapter(
                resolve_engine
            ).revoke_reporter(certificate_principal, datetime.now(UTC))
        finally:
            if listener is not None:
                event.remove(engine.sync_engine, "after_cursor_execute", listener)
            await engine.dispose()

    try:
        if start_event is not None and not start_event.wait(timeout=30):
            raise TimeoutError("reporter revocation start barrier timed out")
        result_pipe.send(("revoke_result", asyncio.run(revoke())))
    except Exception as error:  # noqa: BLE001 - report only the child failure type.
        result_pipe.send(("worker_error", type(error).__name__))
    finally:
        result_pipe.close()


def revoke_then_ingest_race(
    *,
    database_url: str,
    binding: MetricsReporterBinding,
    body: bytes,
    received_at: datetime,
) -> tuple[tuple, tuple]:
    """Hold revocation's real DB write lock while a second process ingests."""
    context = multiprocessing.get_context("spawn")
    revoke_receiver, revoke_sender = context.Pipe(duplex=False)
    ingest_receiver, ingest_sender = context.Pipe(duplex=False)
    lock_acquired = context.Event()
    release_revoke = context.Event()
    start_ingest = context.Event()
    revoke_process = context.Process(
        target=revoke_reporter_in_process,
        args=(
            database_url,
            binding.certificate_principal,
            revoke_sender,
            None,
            lock_acquired,
            release_revoke,
        ),
    )
    ingest_process = context.Process(
        target=accept_snapshot_in_process,
        args=(
            database_url,
            binding,
            body,
            received_at,
            ingest_sender,
            None,
            start_ingest,
        ),
    )
    revoke_process.start()
    revoke_sender.close()
    try:
        if not lock_acquired.wait(timeout=30):
            raise AssertionError("revocation did not acquire its database write lock")
        ingest_process.start()
        ingest_sender.close()
        start_ingest.set()
        # The revocation lock remains held while the independent writer reaches
        # its binding update. The DB, not an in-process mutex, decides ordering.
        time.sleep(0.25)
        release_revoke.set()
        revoke_message = _receive_process_result(revoke_receiver, revoke_process)
        ingest_message = _receive_process_result(ingest_receiver, ingest_process)
        return revoke_message, ingest_message
    finally:
        release_revoke.set()
        for process in (revoke_process, ingest_process):
            if process.pid is not None and process.is_alive():
                process.terminate()
                process.join(timeout=10)
            if process.pid is not None and process.is_alive():
                process.kill()
                process.join(timeout=10)
        revoke_receiver.close()
        ingest_receiver.close()


def _receive_process_result(receiver, process) -> tuple:
    if not receiver.poll(timeout=30):
        process.join(timeout=10)
        raise AssertionError("database race participant returned no outcome")
    return receiver.recv()
