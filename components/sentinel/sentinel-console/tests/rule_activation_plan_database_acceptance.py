"""Disposable PostgreSQL/MySQL acceptance for competing plan schedulers."""

from __future__ import annotations

import asyncio
import hashlib
import multiprocessing
import queue as queue_module
import unittest
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.mutate_rule_set import (
    CancelRuleActivationPlan,
    RuleMutationCommand,
    RuleOperationRejection,
    RuleOperationStatus,
)
from atlas_richie.sentinel_console.application.rule_activation_plan_ports import (
    RuleActivationPlanClaimConflict,
)
from atlas_richie.sentinel_console.application.run_rule_activation_plan_worker import (
    RuleActivationPlanWorkerOutcome,
    RunRuleActivationPlanWorker,
)
from atlas_richie.sentinel_console.domain.rule_bindings import RuleBinding, RuleKind
from atlas_richie.sentinel_console.domain.rule_publication_targets import (
    NacosRulePublicationTarget,
    VersionedRulePublicationTarget,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    AccountRecord,
    AuditEventRecord,
    AuthenticationSessionRecord,
    RuleActivationPlanRecord,
    RuleMutationOperationRecord,
    RulePublicationRecord,
    RuleSetVersionRecord,
    RuleValidationReceiptRecord,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_activation_plan_work_queue import (
    SqlAlchemyRuleActivationPlanWorkQueue,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_mutation_store import (
    SqlAlchemyRuleMutationStore,
)

_RULE_COMMAND_KEY = b"synthetic-plan-cancel-acceptance-key-000000000000"
_ADMIN_SESSION = "synthetic-plan-cancel-admin-session"
_ADMIN_CSRF = "synthetic-plan-cancel-admin-csrf"


def _claim_activation_plan_in_child(
    database_url: str,
    plan_id: str,
    now_timestamp: float,
    lease_expiry_timestamp: float,
    start_gate: multiprocessing.synchronize.Event,
    result_queue: multiprocessing.queues.Queue,
) -> None:
    """Claim one exact due plan from a fresh OS process and SQL pool."""

    async def claim() -> None:
        engine = create_async_engine(database_url, pool_size=1)
        try:
            if not await asyncio.to_thread(start_gate.wait, 15):
                raise TimeoutError("activation claim start gate timed out")
            now = datetime.fromtimestamp(now_timestamp, UTC)
            expiry = datetime.fromtimestamp(lease_expiry_timestamp, UTC)
            claims = await SqlAlchemyRuleActivationPlanWorkQueue(engine).claim_due(
                now=now,
                lease_expires_at=expiry,
                limit=10,
            )
            unexpected = [claim.plan.id for claim in claims if claim.plan.id != plan_id]
            if unexpected:
                raise AssertionError("child claimed an unrelated activation plan")
            result_queue.put(
                {
                    "plan_ids": [item.plan.id for item in claims],
                    "claim_tokens": [item.claim_token for item in claims],
                    "attempts": [item.attempt for item in claims],
                }
            )
        except BaseException as error:
            result_queue.put({"error_type": type(error).__name__})
            raise
        finally:
            await engine.dispose()

    asyncio.run(claim())


class _StartGatedWorkQueue:
    """Pause real SQL claims until all test ASGI lifespans are active."""

    def __init__(self, queue, start_gate: multiprocessing.synchronize.Event) -> None:
        self._queue = queue
        self._start_gate = start_gate

    def __getattr__(self, name: str):
        return getattr(self._queue, name)

    async def claim_due(self, **kwargs):
        if not await asyncio.to_thread(self._start_gate.wait, 30):
            raise TimeoutError("ASGI activation worker start gate timed out")
        return await self._queue.claim_due(**kwargs)


class _ProcessPublicationEnqueuer:
    def __init__(self, store: SqlAlchemyRuleMutationStore, worker_id: str, queue) -> None:
        self._store = store
        self._worker_id = worker_id
        self._queue = queue

    async def enqueue_scheduled_publication(self, claim, *, now):
        result = await self._store.enqueue_scheduled_publication(claim, now=now)
        self._queue.put(
            {
                "worker_id": self._worker_id,
                "publication_id": result.publication_id,
                "state": result.state.value,
            }
        )
        return result


def _run_asgi_activation_worker_in_child(
    database_url: str,
    binding_id: str,
    plan_clock_timestamp: float,
    target_revision: str,
    source_revision: str,
    data_id: str,
    worker_id: str,
    start_gate: multiprocessing.synchronize.Event,
    stop_event: multiprocessing.synchronize.Event,
    status_queue: multiprocessing.queues.Queue,
    publication_queue: multiprocessing.queues.Queue,
) -> None:
    """Run the production ASGI scheduler lifecycle in an isolated process."""

    async def run() -> None:
        engine = create_async_engine(database_url, pool_size=1)
        target = VersionedRulePublicationTarget(
            revision=target_revision,
            source_revision=source_revision,
            target=NacosRulePublicationTarget(
                binding_id=binding_id,
                source_id="acceptance-source",
                namespace="acceptance-namespace",
                group="SENTINEL_RULES",
                data_id=data_id,
            ),
        )
        store = SqlAlchemyRuleMutationStore(
            engine,
            fingerprint_keys={"acceptance": _RULE_COMMAND_KEY},
            active_fingerprint_key_id="acceptance",
            binding_reader=_FixedBindingReader(binding_id),
            publication_target_reader=_FixedPublicationTargetReader(target),
        )
        worker = RunRuleActivationPlanWorker(
            work_queue=_StartGatedWorkQueue(
                SqlAlchemyRuleActivationPlanWorkQueue(engine), start_gate
            ),
            publication_enqueuer=_ProcessPublicationEnqueuer(
                store, worker_id, publication_queue
            ),
            clock=lambda: datetime.fromtimestamp(plan_clock_timestamp, UTC),
        )
        app = build_app(
            bootstrap_initialization_reader=object(),
            setup_window_reader=object(),
            bootstrap_operator_verifier=object(),
            current_session_reader=object(),
            current_session_revoker=object(),
            account_directory_reader=object(),
            allowed_browser_origins=frozenset({"https://console.test"}),
            rule_activation_plan_worker=worker,
            activation_plan_worker_poll_interval_seconds=0.025,
            activation_plan_worker_batch_size=1,
        )
        try:
            async with app.router.lifespan_context(app):
                status_queue.put({"worker_id": worker_id, "event": "started"})
                await asyncio.to_thread(stop_event.wait, 30)
        except BaseException as error:
            status_queue.put(
                {
                    "worker_id": worker_id,
                    "event": "error",
                    "error_type": type(error).__name__,
                }
            )
            raise
        finally:
            await engine.dispose()

    asyncio.run(run())


async def _race_process_claims(
    database_url: str,
    *,
    plan_id: str,
    now: datetime,
    lease_expires_at: datetime,
    process_count: int,
) -> list[dict[str, object]]:
    """Run independent scheduler processes against one persisted due plan."""
    context = multiprocessing.get_context("spawn")
    start_gate = context.Event()
    result_queue = context.Queue()
    processes = [
        context.Process(
            target=_claim_activation_plan_in_child,
            args=(
                database_url,
                plan_id,
                now.timestamp(),
                lease_expires_at.timestamp(),
                start_gate,
                result_queue,
            ),
        )
        for _ in range(process_count)
    ]
    try:
        for process in processes:
            process.start()
        start_gate.set()
        results = [result_queue.get(timeout=30) for _ in processes]
        for process in processes:
            process.join(timeout=30)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
                raise AssertionError("activation plan child process did not exit")
            if process.exitcode != 0:
                raise AssertionError(
                    f"activation plan child exited with {process.exitcode}"
                )
        errors = [result for result in results if "error_type" in result]
        if errors:
            raise AssertionError(f"activation plan child failed: {errors}")
        return results
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        result_queue.close()
        result_queue.join_thread()


async def _run_two_asgi_activation_workers(
    engine: AsyncEngine,
    database_url: str,
    *,
    binding_id: str,
    plan_id: str,
    plan_clock: datetime,
    target_revision: str,
    source_revision: str,
    data_id: str,
) -> list[dict[str, object]]:
    """Start two actual ASGI lifespans before racing one shared SQL plan."""
    context = multiprocessing.get_context("spawn")
    start_gate = context.Event()
    stop_event = context.Event()
    status_queue = context.Queue()
    publication_queue = context.Queue()
    processes = [
        context.Process(
            target=_run_asgi_activation_worker_in_child,
            args=(
                database_url,
                binding_id,
                plan_clock.timestamp(),
                target_revision,
                source_revision,
                data_id,
                f"asgi-worker-{index}",
                start_gate,
                stop_event,
                status_queue,
                publication_queue,
            ),
        )
        for index in range(2)
    ]
    try:
        for process in processes:
            process.start()
        started = [
            await asyncio.to_thread(status_queue.get, True, 30)
            for _ in processes
        ]
        errors = [event for event in started if event.get("event") != "started"]
        if errors:
            raise AssertionError(f"ASGI activation child failed to start: {errors}")

        start_gate.set()
        publication_events = [
            await asyncio.to_thread(publication_queue.get, True, 30)
        ]
        expected_publication_id = publication_events[0].get("publication_id")
        deadline = asyncio.get_running_loop().time() + 10
        while True:
            async with engine.connect() as connection:
                associated_publication_id = await connection.scalar(
                    select(RuleActivationPlanRecord.activation_publication_id).where(
                        RuleActivationPlanRecord.plan_id == plan_id
                    )
                )
            if associated_publication_id == expected_publication_id:
                break
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError(
                    "ASGI worker did not persist its scheduled publication association"
                )
            await asyncio.sleep(0.025)
        stop_event.set()
        for process in processes:
            await asyncio.to_thread(process.join, 30)
            if process.is_alive():
                process.terminate()
                await asyncio.to_thread(process.join, 5)
                raise AssertionError("ASGI activation child did not stop")
            if process.exitcode != 0:
                raise AssertionError(
                    f"ASGI activation child exited with {process.exitcode}"
                )
        while True:
            try:
                publication_events.append(publication_queue.get_nowait())
            except queue_module.Empty:
                break
        return publication_events
    finally:
        start_gate.set()
        stop_event.set()
        for process in processes:
            if process.is_alive():
                process.terminate()
                await asyncio.to_thread(process.join, 5)
        status_queue.close()
        publication_queue.close()
        status_queue.join_thread()
        publication_queue.join_thread()


async def assert_independent_plan_workers_fence_and_recover(
    case: unittest.TestCase,
    engine: AsyncEngine,
    database_url: str,
) -> None:
    """Prove one winner and stale-token rejection across separate SQL pools."""
    worker_engine = create_async_engine(database_url, pool_size=2)
    test_id = uuid4().hex
    account_id = str(uuid4())
    binding_id = f"binding-plan-race-{test_id}"
    plan_id = f"plan-race-{test_id}"
    scheduler_loser_plan_id = f"plan-scheduler-loser-{test_id}"
    process_plan_id = f"plan-process-restart-{test_id}"
    asgi_plan_id = f"plan-asgi-lifespans-{test_id}"
    version_ids = (f"version-a-{test_id}", f"version-b-{test_id}")
    validation_ids = (f"validation-a-{test_id}", f"validation-b-{test_id}")
    now = datetime.now(UTC).replace(microsecond=0)
    first_lease_expiry = now + timedelta(seconds=30)
    recovery_now = first_lease_expiry + timedelta(milliseconds=1)
    recovery_lease_expiry = recovery_now + timedelta(seconds=30)
    scheduler_enqueuer: _GatedPublicationEnqueuer | None = None
    scheduler_winner_task: asyncio.Task | None = None
    asgi_publication_id: str | None = None
    queues = (
        SqlAlchemyRuleActivationPlanWorkQueue(engine),
        SqlAlchemyRuleActivationPlanWorkQueue(worker_engine),
    )
    try:
        async with engine.begin() as connection:
            await connection.execute(
                insert(AccountRecord).values(
                    account_id=account_id,
                    username=f"plan-race-{test_id}",
                    username_key=hashlib.sha256(test_id.encode()).hexdigest(),
                    password_hash="$argon2id$synthetic-acceptance-only",
                    role_id="admin",
                    status="active",
                    built_in=False,
                    last_login_at=None,
                    revision=1,
                    created_at=now,
                    updated_at=now,
                )
            )
            for index, (version_id, validation_id) in enumerate(
                zip(version_ids, validation_ids)
            ):
                await connection.execute(
                    insert(RuleValidationReceiptRecord).values(
                        validation_id=validation_id,
                        binding_id=binding_id,
                        profile="sentinel-profile-v1",
                        base_checksum="sha256:empty",
                        candidate_checksum=f"sha256:{index}",
                        is_publishable=True,
                        issues=[],
                        actor_account_id=account_id,
                        request_id=f"plan-race-request-{test_id}-{index}",
                        created_at=now,
                    )
                )
                await connection.execute(
                    insert(RuleSetVersionRecord).values(
                        version_id=version_id,
                        binding_id=binding_id,
                        kind="flow",
                        profile="sentinel-profile-v1",
                        base_version_id=None,
                        checksum=f"sha256:{index}",
                        name=version_id,
                        note="synthetic concurrency acceptance",
                        validation_id=validation_id,
                        records=[
                            {
                                "id": f"record-{index}",
                                "rule": {
                                    "kind": "flow",
                                    "value": {
                                        "resource": "/synthetic",
                                        "grade": 1,
                                        "count": index + 1,
                                    },
                                },
                            }
                        ],
                        created_at=now,
                        created_by_account_id=account_id,
                    )
                )
            await connection.execute(
                insert(RuleActivationPlanRecord).values(
                    plan_id=plan_id,
                    revision=str(uuid4()),
                    binding_id=binding_id,
                    version_id=version_ids[0],
                    restore_version_id=version_ids[1],
                    activate_at=now - timedelta(seconds=1),
                    deactivate_at=now + timedelta(minutes=5),
                    time_zone="UTC",
                    state="pending",
                    activation_publication_id=None,
                    restore_publication_id=None,
                    claim_token=None,
                    claim_lease_expires_at=None,
                    claim_attempt_count=0,
                    created_at=now,
                    created_by_account_id=account_id,
                )
            )

        first_results = await asyncio.gather(
            *(
                queue.claim_due(
                    now=now,
                    lease_expires_at=first_lease_expiry,
                )
                for queue in queues
            )
        )
        first_claims = [claim for result in first_results for claim in result]
        case.assertEqual(len(first_claims), 1, "competing workers must produce one claim")
        first_claim = first_claims[0]
        case.assertEqual(first_claim.plan.id, plan_id)
        case.assertEqual(first_claim.attempt, 1)

        recovery_results = await asyncio.gather(
            *(
                queue.claim_due(
                    now=recovery_now,
                    lease_expires_at=recovery_lease_expiry,
                )
                for queue in queues
            )
        )
        recovery_claims = [claim for result in recovery_results for claim in result]
        case.assertEqual(len(recovery_claims), 1, "expired claim must have one new owner")
        recovery_claim = recovery_claims[0]
        case.assertEqual(recovery_claim.plan.id, plan_id)
        case.assertEqual(recovery_claim.attempt, 2)
        case.assertNotEqual(recovery_claim.claim_token, first_claim.claim_token)

        with case.assertRaises(RuleActivationPlanClaimConflict):
            await queues[0].renew_claim(
                first_claim,
                now=recovery_now,
                lease_expires_at=recovery_lease_expiry,
            )

        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    select(RuleActivationPlanRecord.__table__).where(
                        RuleActivationPlanRecord.plan_id == plan_id
                    )
                )
            ).mappings().one()
        stored_expiry = row["claim_lease_expires_at"]
        if stored_expiry.tzinfo is None:
            stored_expiry = stored_expiry.replace(tzinfo=UTC)
        case.assertEqual(row["state"], "activating")
        case.assertEqual(row["claim_attempt_count"], 2)
        case.assertEqual(row["claim_token"], recovery_claim.claim_token)
        case.assertEqual(stored_expiry, recovery_lease_expiry)

        blocked_at = recovery_now + timedelta(milliseconds=1)
        await queues[0].block_claim(recovery_claim, now=blocked_at)
        restoration_due = now + timedelta(minutes=6)
        restoration_results = await asyncio.gather(
            *(
                queue.claim_due(
                    now=restoration_due,
                    lease_expires_at=restoration_due + timedelta(seconds=30),
                )
                for queue in queues
            )
        )
        case.assertEqual(
            [claim for result in restoration_results for claim in result],
            [],
            "a blocked plan must not be claimable in its restoration window",
        )
        async with engine.connect() as connection:
            blocked_row = (
                await connection.execute(
                    select(RuleActivationPlanRecord.__table__).where(
                        RuleActivationPlanRecord.plan_id == plan_id
                    )
                )
            ).mappings().one()
        case.assertEqual(blocked_row["state"], "blocked")
        case.assertIsNone(blocked_row["claim_token"])
        case.assertIsNone(blocked_row["claim_lease_expires_at"])

        # A real pair of plan workers must not call the publication port twice.
        # Hold the first winner inside that port while the independent second
        # worker polls the same database-backed queue.
        scheduler_now = recovery_now + timedelta(milliseconds=1)
        async with engine.begin() as connection:
            await connection.execute(
                insert(RuleActivationPlanRecord).values(
                    plan_id=scheduler_loser_plan_id,
                    revision=f"revision-{test_id}",
                    binding_id=binding_id,
                    version_id=version_ids[0],
                    restore_version_id=version_ids[1],
                    activate_at=scheduler_now - timedelta(seconds=1),
                    deactivate_at=scheduler_now + timedelta(minutes=5),
                    time_zone="UTC",
                    state="pending",
                    activation_publication_id=None,
                    restore_publication_id=None,
                    claim_token=None,
                    claim_lease_expires_at=None,
                    claim_attempt_count=0,
                    created_at=now,
                    created_by_account_id=account_id,
                )
            )
        scheduler_publication_target = VersionedRulePublicationTarget(
            revision=f"scheduler-target-rev-{test_id}",
            source_revision=f"scheduler-source-rev-{test_id}",
            target=NacosRulePublicationTarget(
                binding_id=binding_id,
                source_id="acceptance-source",
                namespace="acceptance-namespace",
                group="SENTINEL_RULES",
                data_id="scheduler-loser.flow.json",
            ),
        )
        scheduler_store = SqlAlchemyRuleMutationStore(
            engine,
            fingerprint_keys={"acceptance": _RULE_COMMAND_KEY},
            active_fingerprint_key_id="acceptance",
            binding_reader=_FixedBindingReader(binding_id),
            publication_target_reader=_FixedPublicationTargetReader(
                scheduler_publication_target
            ),
        )
        scheduler_enqueuer = _GatedPublicationEnqueuer(scheduler_store)
        schedulers = tuple(
            RunRuleActivationPlanWorker(
                work_queue=queue,
                publication_enqueuer=scheduler_enqueuer,
                clock=lambda: scheduler_now,
            )
            for queue in queues
        )
        scheduler_winner_task = asyncio.create_task(schedulers[0].run_once())
        await asyncio.wait_for(scheduler_enqueuer.started.wait(), timeout=10)
        loser_outcome = await asyncio.wait_for(schedulers[1].run_once(), timeout=10)
        case.assertEqual(loser_outcome, (), "losing scheduler must emit no publication command")
        scheduler_enqueuer.resume.set()
        winner_outcome = await asyncio.wait_for(scheduler_winner_task, timeout=10)
        case.assertEqual(
            winner_outcome,
            (RuleActivationPlanWorkerOutcome.ENQUEUED,),
        )
        case.assertEqual(scheduler_enqueuer.calls, 1)
        async with engine.connect() as connection:
            scheduler_plan = (
                await connection.execute(
                    select(RuleActivationPlanRecord.__table__).where(
                        RuleActivationPlanRecord.plan_id == scheduler_loser_plan_id
                    )
                )
            ).mappings().one()
        case.assertEqual(scheduler_plan["state"], "activating")
        case.assertEqual(scheduler_plan["claim_attempt_count"], 1)
        case.assertEqual(
            scheduler_plan["activation_publication_id"],
            scheduler_enqueuer.publication_id,
        )
        async with engine.connect() as connection:
            scheduler_publication = (
                await connection.execute(
                    select(RulePublicationRecord.__table__).where(
                        RulePublicationRecord.publication_id
                        == scheduler_enqueuer.publication_id
                    )
                )
            ).mappings().one()
        case.assertEqual(scheduler_publication["validation_state"], "awaiting")
        case.assertEqual(scheduler_publication["write_state"], "awaiting")
        case.assertEqual(scheduler_publication["read_back_state"], "awaiting")

        # Prove the claim itself survives an OS-process exit, and that newly
        # started workers recover its expired lease without double ownership.
        process_now = scheduler_now + timedelta(seconds=1)
        process_lease = process_now + timedelta(seconds=3)
        async with engine.begin() as connection:
            await connection.execute(
                insert(RuleActivationPlanRecord).values(
                    plan_id=process_plan_id,
                    revision=f"revision-{test_id}",
                    binding_id=binding_id,
                    version_id=version_ids[0],
                    restore_version_id=version_ids[1],
                    activate_at=process_now - timedelta(seconds=1),
                    deactivate_at=process_now + timedelta(minutes=5),
                    time_zone="UTC",
                    state="pending",
                    activation_publication_id=None,
                    restore_publication_id=None,
                    claim_token=None,
                    claim_lease_expires_at=None,
                    claim_attempt_count=0,
                    created_at=now,
                    created_by_account_id=account_id,
                )
            )
        first_process_results = await _race_process_claims(
            database_url,
            plan_id=process_plan_id,
            now=process_now,
            lease_expires_at=process_lease,
            process_count=1,
        )
        first_process_claims = [
            item
            for result in first_process_results
            for item in zip(
                result["plan_ids"], result["claim_tokens"], result["attempts"]
            )
        ]
        case.assertEqual(len(first_process_claims), 1)
        case.assertEqual(first_process_claims[0][0], process_plan_id)
        first_process_token = first_process_claims[0][1]

        process_recovery_now = process_lease + timedelta(milliseconds=1)
        process_recovery_lease = process_recovery_now + timedelta(seconds=3)
        recovery_process_results = await _race_process_claims(
            database_url,
            plan_id=process_plan_id,
            now=process_recovery_now,
            lease_expires_at=process_recovery_lease,
            process_count=2,
        )
        recovered_claims = [
            item
            for result in recovery_process_results
            for item in zip(
                result["plan_ids"], result["claim_tokens"], result["attempts"]
            )
        ]
        case.assertEqual(len(recovered_claims), 1)
        case.assertEqual(recovered_claims[0][0], process_plan_id)
        case.assertNotEqual(recovered_claims[0][1], first_process_token)
        case.assertEqual(recovered_claims[0][2], 2)

        # Start two real app lifespans in separate processes. Their SQL claims
        # are held until both worker loops are alive, then released together.
        asgi_now = scheduler_now + timedelta(seconds=2)
        asgi_target = VersionedRulePublicationTarget(
            revision=f"asgi-target-rev-{test_id}",
            source_revision=f"asgi-source-rev-{test_id}",
            target=NacosRulePublicationTarget(
                binding_id=binding_id,
                source_id="acceptance-source",
                namespace="acceptance-namespace",
                group="SENTINEL_RULES",
                data_id="asgi-lifespans.flow.json",
            ),
        )
        async with engine.begin() as connection:
            await connection.execute(
                insert(RuleActivationPlanRecord).values(
                    plan_id=asgi_plan_id,
                    revision=f"asgi-revision-{test_id}",
                    binding_id=binding_id,
                    version_id=version_ids[0],
                    restore_version_id=version_ids[1],
                    activate_at=asgi_now - timedelta(seconds=1),
                    deactivate_at=asgi_now + timedelta(minutes=5),
                    time_zone="UTC",
                    state="pending",
                    activation_publication_id=None,
                    restore_publication_id=None,
                    claim_token=None,
                    claim_lease_expires_at=None,
                    claim_attempt_count=0,
                    created_at=now,
                    created_by_account_id=account_id,
                )
            )
        asgi_events = await _run_two_asgi_activation_workers(
            engine,
            database_url,
            binding_id=binding_id,
            plan_id=asgi_plan_id,
            plan_clock=asgi_now,
            target_revision=asgi_target.revision,
            source_revision=asgi_target.source_revision,
            data_id=asgi_target.target.data_id,
        )
        case.assertEqual(len(asgi_events), 1)
        case.assertEqual(asgi_events[0]["state"], "pending")
        asgi_publication_id = str(asgi_events[0]["publication_id"])
        async with engine.connect() as connection:
            asgi_plan = (
                await connection.execute(
                    select(RuleActivationPlanRecord.__table__).where(
                        RuleActivationPlanRecord.plan_id == asgi_plan_id
                    )
                )
            ).mappings().one()
            asgi_operations = (
                await connection.execute(
                    select(RuleMutationOperationRecord.operation_id).where(
                    RuleMutationOperationRecord.origin_plan_id == asgi_plan_id
                    )
                )
            ).scalars().all()
            asgi_publications = await connection.scalar(
                select(RulePublicationRecord.publication_id).where(
                    RulePublicationRecord.publication_id == asgi_publication_id
                )
            )
        case.assertEqual(asgi_plan["state"], "activating")
        case.assertEqual(asgi_plan["claim_attempt_count"], 1)
        case.assertEqual(
            asgi_plan["activation_publication_id"], asgi_publication_id
        )
        case.assertEqual(len(asgi_operations), 1)
        case.assertEqual(asgi_publications, asgi_publication_id)
    finally:
        if scheduler_enqueuer is not None:
            scheduler_enqueuer.resume.set()
        if scheduler_winner_task is not None and not scheduler_winner_task.done():
            await asyncio.gather(scheduler_winner_task, return_exceptions=True)
        async with engine.begin() as connection:
            await connection.execute(
                delete(RuleMutationOperationRecord).where(
                    RuleMutationOperationRecord.origin_plan_id.in_(
                        [plan_id, scheduler_loser_plan_id, asgi_plan_id]
                    )
                )
            )
            if scheduler_enqueuer is not None and scheduler_enqueuer.publication_id:
                await connection.execute(
                    delete(RulePublicationRecord).where(
                        RulePublicationRecord.publication_id
                        == scheduler_enqueuer.publication_id
                    )
                )
            if asgi_publication_id is not None:
                await connection.execute(
                    delete(RulePublicationRecord).where(
                        RulePublicationRecord.publication_id == asgi_publication_id
                    )
                )
            await connection.execute(
                delete(AuditEventRecord).where(
                    AuditEventRecord.target_id.in_(
                        [plan_id, scheduler_loser_plan_id, asgi_plan_id]
                    )
                )
            )
            await connection.execute(
                delete(RuleActivationPlanRecord).where(
                    RuleActivationPlanRecord.plan_id.in_(
                        [
                            plan_id,
                            scheduler_loser_plan_id,
                            process_plan_id,
                            asgi_plan_id,
                        ]
                    )
                )
            )
            await connection.execute(
                delete(RuleSetVersionRecord).where(
                    RuleSetVersionRecord.version_id.in_(version_ids)
                )
            )
            await connection.execute(
                delete(RuleValidationReceiptRecord).where(
                    RuleValidationReceiptRecord.validation_id.in_(validation_ids)
                )
            )
            await connection.execute(
                delete(AccountRecord).where(AccountRecord.account_id == account_id)
            )
        await worker_engine.dispose()


async def assert_cancel_racing_activation_claim_preserves_started_publication(
    case: unittest.TestCase,
    engine: AsyncEngine,
    database_url: str,
) -> None:
    """Prove a cancel command cannot hide a concurrently claimed activation."""
    command_engine = create_async_engine(database_url, pool_size=2)
    test_id = uuid4().hex
    account_id = str(uuid4())
    binding_id = f"binding-plan-cancel-{test_id}"
    plan_id = f"plan-cancel-race-{test_id}"
    cancel_wins_plan_id = f"plan-cancel-wins-{test_id}"
    session_digest = hashlib.sha256(_ADMIN_SESSION.encode()).hexdigest()
    csrf_digest = hashlib.sha256(_ADMIN_CSRF.encode()).hexdigest()
    version_ids = (f"version-plan-cancel-a-{test_id}", f"version-plan-cancel-b-{test_id}")
    validation_ids = (f"validation-plan-cancel-a-{test_id}", f"validation-plan-cancel-b-{test_id}")
    request_key = f"cancel-plan-race-{test_id}"
    now = datetime.now(UTC).replace(microsecond=0)
    binding_reader = _GatedBindingReader(binding_id)
    publication_target = VersionedRulePublicationTarget(
        revision=f"target-rev-{test_id}",
        source_revision=f"source-rev-{test_id}",
        target=NacosRulePublicationTarget(
            binding_id=binding_id,
            source_id="acceptance-source",
            namespace="acceptance-namespace",
            group="SENTINEL_RULES",
            data_id="acceptance.flow.json",
        ),
    )
    store = SqlAlchemyRuleMutationStore(
        command_engine,
        fingerprint_keys={"acceptance": _RULE_COMMAND_KEY},
        active_fingerprint_key_id="acceptance",
        binding_reader=binding_reader,
        publication_target_reader=_FixedPublicationTargetReader(publication_target),
    )
    queue = SqlAlchemyRuleActivationPlanWorkQueue(engine)
    scheduled_publication_id: str | None = None
    cancel_task: asyncio.Task | None = None
    cancel_wins_task: asyncio.Task | None = None
    try:
        async with engine.begin() as connection:
            await connection.execute(
                insert(AccountRecord).values(
                    account_id=account_id,
                    username=f"plan-cancel-{test_id}",
                    username_key=hashlib.sha256(test_id.encode()).hexdigest(),
                    password_hash="$argon2id$synthetic-acceptance-only",
                    role_id="admin",
                    status="active",
                    built_in=False,
                    last_login_at=None,
                    revision=1,
                    created_at=now,
                    updated_at=now,
                )
            )
            await connection.execute(
                insert(AuthenticationSessionRecord).values(
                    session_hash=session_digest,
                    account_id=account_id,
                    session_epoch=f"epoch-{test_id[:24]}",
                    csrf_hash=csrf_digest,
                    created_at=now,
                    expires_at=now + timedelta(days=1),
                    revoked_at=None,
                )
            )
            for index, (version_id, validation_id) in enumerate(
                zip(version_ids, validation_ids)
            ):
                checksum = f"sha256:cancel-race-{index}-{test_id}"
                await connection.execute(
                    insert(RuleValidationReceiptRecord).values(
                        validation_id=validation_id,
                        binding_id=binding_id,
                        profile="sentinel-profile-v1",
                        base_checksum="sha256:empty",
                        candidate_checksum=checksum,
                        is_publishable=True,
                        issues=[],
                        actor_account_id=account_id,
                        request_id=f"cancel-race-validation-{test_id}-{index}",
                        created_at=now,
                    )
                )
                await connection.execute(
                    insert(RuleSetVersionRecord).values(
                        version_id=version_id,
                        binding_id=binding_id,
                        kind="flow",
                        profile="sentinel-profile-v1",
                        base_version_id=None,
                        checksum=checksum,
                        name=version_id,
                        note="synthetic cancellation race acceptance",
                        validation_id=validation_id,
                        records=[
                            {
                                "id": f"cancel-race-record-{index}",
                                "rule": {
                                    "kind": "flow",
                                    "value": {
                                        "resource": "/acceptance",
                                        "limitApp": "default",
                                        "grade": 1,
                                        "count": index + 1,
                                    },
                                },
                            }
                        ],
                        created_at=now,
                        created_by_account_id=account_id,
                    )
                )
            await connection.execute(
                insert(RuleActivationPlanRecord).values(
                    plan_id=plan_id,
                    revision=f"revision-{test_id}",
                    binding_id=binding_id,
                    version_id=version_ids[0],
                    restore_version_id=version_ids[1],
                    activate_at=now - timedelta(seconds=1),
                    deactivate_at=now + timedelta(minutes=5),
                    time_zone="UTC",
                    state="pending",
                    activation_publication_id=None,
                    restore_publication_id=None,
                    claim_token=None,
                    claim_lease_expires_at=None,
                    claim_attempt_count=0,
                    created_at=now,
                    created_by_account_id=account_id,
                )
            )

        command = RuleMutationCommand(
            binding_id=binding_id,
            request_key=request_key,
            mutation=CancelRuleActivationPlan(
                plan_id=plan_id,
                expected_revision=f"revision-{test_id}",
                reason="acceptance race",
            ),
        )
        cancel_task = asyncio.create_task(
            store.mutate(
                command,
                actor_id=account_id,
                session_digest=session_digest,
                csrf_digest=csrf_digest,
                request_id=f"cancel-race-request-{test_id}",
                now=now,
            )
        )
        await asyncio.wait_for(binding_reader.started.wait(), timeout=10)
        claims = await queue.claim_due(
            now=now,
            lease_expires_at=now + timedelta(seconds=45),
        )
        case.assertEqual(len(claims), 1, "scheduler must claim while cancellation is between reads")
        claim = claims[0]
        binding_reader.resume.set()
        cancelled = await asyncio.wait_for(cancel_task, timeout=10)

        case.assertEqual(cancelled.status, RuleOperationStatus.REJECTED)
        case.assertEqual(cancelled.reason, RuleOperationRejection.CONFLICT)
        case.assertEqual(claim.plan.state.value, "activating")

        # Drive the already-claimed phase through durable publication acceptance
        # before associating it, matching the scheduler's recoverable crash window.
        scheduled = await store.enqueue_scheduled_publication(claim, now=now)
        case.assertEqual(scheduled.state.value, "pending")
        case.assertIsNotNone(scheduled.publication_id)
        scheduled_publication_id = scheduled.publication_id
        associated = await queue.associate_publication(
            claim, scheduled_publication_id, now=now
        )

        async with engine.connect() as connection:
            plan = (
                await connection.execute(
                    select(RuleActivationPlanRecord.__table__).where(
                        RuleActivationPlanRecord.plan_id == plan_id
                    )
                )
            ).mappings().one()
            operation = (
                await connection.execute(
                    select(RuleMutationOperationRecord.__table__).where(
                        RuleMutationOperationRecord.request_key == request_key
                    )
                )
            ).mappings().one()
            publication_count = await connection.scalar(
                select(RulePublicationRecord.publication_id).where(
                    RulePublicationRecord.publication_id == scheduled_publication_id
                )
            )
        case.assertEqual(plan["state"], "activating")
        case.assertEqual(plan["claim_token"], associated.claim_token)
        case.assertEqual(
            plan["activation_publication_id"], scheduled_publication_id
        )
        case.assertEqual(operation["status"], "rejected")
        case.assertEqual(operation["reason"], "conflict")
        case.assertEqual(publication_count, scheduled_publication_id)

        cancel_wins_revision = f"cancel-wins-revision-{test_id}"
        async with engine.begin() as connection:
            await connection.execute(
                insert(RuleActivationPlanRecord).values(
                    plan_id=cancel_wins_plan_id,
                    revision=cancel_wins_revision,
                    binding_id=binding_id,
                    version_id=version_ids[0],
                    restore_version_id=version_ids[1],
                    activate_at=now - timedelta(seconds=1),
                    deactivate_at=now + timedelta(minutes=5),
                    time_zone="UTC",
                    state="pending",
                    activation_publication_id=None,
                    restore_publication_id=None,
                    claim_token=None,
                    claim_lease_expires_at=None,
                    claim_attempt_count=0,
                    created_at=now,
                    created_by_account_id=account_id,
                )
            )

        cancel_wins_request_key = f"cancel-wins-plan-{test_id}"
        cancel_wins_command = RuleMutationCommand(
            binding_id=binding_id,
            request_key=cancel_wins_request_key,
            mutation=CancelRuleActivationPlan(
                plan_id=cancel_wins_plan_id,
                expected_revision=cancel_wins_revision,
                reason="acceptance cancellation-first race",
            ),
        )
        binding_reader.pause()
        async with engine.connect() as lock_connection:
            await lock_connection.begin()
            await lock_connection.execute(
                select(RuleActivationPlanRecord.plan_id)
                .where(RuleActivationPlanRecord.plan_id == cancel_wins_plan_id)
                .with_for_update()
            )
            cancel_wins_task = asyncio.create_task(
                store.mutate(
                    cancel_wins_command,
                    actor_id=account_id,
                    session_digest=session_digest,
                    csrf_digest=csrf_digest,
                    request_id=f"cancel-wins-request-{test_id}",
                    now=now,
                )
            )
            await asyncio.wait_for(binding_reader.started.wait(), timeout=10)
            binding_reader.resume.set()
            losing_claims = await queue.claim_due(
                now=now,
                lease_expires_at=now + timedelta(seconds=45),
            )
            case.assertEqual(
                losing_claims,
                (),
                "scheduler must skip a plan locked by the in-flight cancellation",
            )
            case.assertFalse(
                cancel_wins_task.done(),
                "cancellation should still be waiting for its locked plan row",
            )
            await lock_connection.commit()
        cancelled_first = await asyncio.wait_for(cancel_wins_task, timeout=10)
        case.assertEqual(cancelled_first.status, RuleOperationStatus.COMPLETED)
        case.assertEqual(cancelled_first.result.state.value, "cancelled")
        case.assertEqual(
            await queue.claim_due(
                now=now,
                lease_expires_at=now + timedelta(seconds=45),
            ),
            (),
            "a committed cancellation must not become an activation claim",
        )
    finally:
        if not binding_reader.resume.is_set():
            binding_reader.resume.set()
        if cancel_task is not None and not cancel_task.done():
            await asyncio.gather(cancel_task, return_exceptions=True)
        if cancel_wins_task is not None and not cancel_wins_task.done():
            await asyncio.gather(cancel_wins_task, return_exceptions=True)
        async with engine.begin() as connection:
            if scheduled_publication_id is not None:
                await connection.execute(
                    delete(RulePublicationRecord).where(
                        RulePublicationRecord.publication_id == scheduled_publication_id
                    )
                )
            await connection.execute(
                delete(AuditEventRecord).where(
                    (AuditEventRecord.request_id == f"cancel-race-request-{test_id}")
                    | (AuditEventRecord.request_id == f"cancel-wins-request-{test_id}")
                    | (AuditEventRecord.target_id.in_([plan_id, cancel_wins_plan_id]))
                )
            )
            await connection.execute(
                delete(RuleMutationOperationRecord).where(
                    RuleMutationOperationRecord.request_key.in_(
                        [request_key, f"cancel-wins-plan-{test_id}"]
                    )
                    | (RuleMutationOperationRecord.origin_plan_id.in_([plan_id, cancel_wins_plan_id]))
                )
            )
            await connection.execute(
                delete(RuleActivationPlanRecord).where(
                    RuleActivationPlanRecord.plan_id.in_([plan_id, cancel_wins_plan_id])
                )
            )
            await connection.execute(
                delete(RuleSetVersionRecord).where(
                    RuleSetVersionRecord.version_id.in_(version_ids)
                )
            )
            await connection.execute(
                delete(RuleValidationReceiptRecord).where(
                    RuleValidationReceiptRecord.validation_id.in_(validation_ids)
                )
            )
            await connection.execute(
                delete(AuthenticationSessionRecord).where(
                    AuthenticationSessionRecord.session_hash == session_digest
                )
            )
            await connection.execute(
                delete(AccountRecord).where(AccountRecord.account_id == account_id)
            )
        await command_engine.dispose()


class _GatedBindingReader:
    def __init__(self, binding_id: str) -> None:
        self._binding_id = binding_id
        self.started = asyncio.Event()
        self.resume = asyncio.Event()

    def pause(self) -> None:
        self.started.clear()
        self.resume.clear()

    async def read_rule_binding(self, binding_id: str) -> RuleBinding | None:
        self.started.set()
        await self.resume.wait()
        if binding_id != self._binding_id:
            return None
        return RuleBinding(
            id=binding_id,
            environment_id="acceptance",
            app_id="acceptance-app",
            kind=RuleKind.FLOW,
            profile="sentinel-profile-v1",
            source_id="acceptance-source",
            source_label="Acceptance Source",
            location="https://config.example.test/namespace",
        )


class _FixedPublicationTargetReader:
    def __init__(self, target: VersionedRulePublicationTarget) -> None:
        self._target = target

    async def read_rule_publication_target(self, binding_id: str):
        if self._target.target.binding_id != binding_id:
            return None
        return self._target


class _FixedBindingReader:
    def __init__(self, binding_id: str) -> None:
        self._binding_id = binding_id

    async def read_rule_binding(self, binding_id: str) -> RuleBinding | None:
        if binding_id != self._binding_id:
            return None
        return RuleBinding(
            id=binding_id,
            environment_id="acceptance",
            app_id="acceptance-app",
            kind=RuleKind.FLOW,
            profile="sentinel-profile-v1",
            source_id="acceptance-source",
            source_label="Acceptance Source",
            location="https://config.example.test/namespace",
        )


class _GatedPublicationEnqueuer:
    def __init__(self, store: SqlAlchemyRuleMutationStore) -> None:
        self._store = store
        self.started = asyncio.Event()
        self.resume = asyncio.Event()
        self.calls = 0
        self.publication_id: str | None = None

    async def enqueue_scheduled_publication(self, claim, *, now):
        self.calls += 1
        self.started.set()
        await self.resume.wait()
        result = await self._store.enqueue_scheduled_publication(claim, now=now)
        self.publication_id = result.publication_id
        return result
