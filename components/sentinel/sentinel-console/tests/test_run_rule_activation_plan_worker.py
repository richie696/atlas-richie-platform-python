"""Application contracts for scheduling durable rule publications."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import unittest

from atlas_richie.sentinel_console.application.mutate_rule_set import (
    RuleOperationRejection,
)
from atlas_richie.sentinel_console.application.rule_activation_plan_ports import (
    RuleActivationPlanClaim,
    ScheduledPublicationEnqueue,
    ScheduledPublicationState,
)
from atlas_richie.sentinel_console.application.run_rule_activation_plan_worker import (
    RuleActivationPlanWorkerOutcome,
    RunRuleActivationPlanWorker,
)
from atlas_richie.sentinel_console.domain.rule_activation_plans import (
    RuleActivationPlan,
    RuleActivationPlanState,
)

_NOW = datetime(2026, 10, 9, 8, 0, 0, 123456, tzinfo=UTC)


def _claim(state: RuleActivationPlanState) -> RuleActivationPlanClaim:
    plan = RuleActivationPlan(
        id="plan-001",
        revision="revision-001",
        binding_id="binding-001",
        version_id="version-001",
        restore_version_id="version-002",
        activate_at=datetime(2026, 10, 9, 7, 0, tzinfo=UTC),
        deactivate_at=datetime(2026, 10, 9, 9, 0, tzinfo=UTC),
        time_zone="UTC",
        state=state,
        activation_publication_id=None,
        restore_publication_id=None,
    )
    return RuleActivationPlanClaim(
        plan=plan,
        claim_token="claim-001",
        lease_expires_at=_NOW.replace(microsecond=123000) + timedelta(seconds=30),
        attempt=1,
    )


class _WorkQueue:
    def __init__(self, claims: tuple[RuleActivationPlanClaim, ...]) -> None:
        self.claims = claims
        self.calls: list[tuple[str, object]] = []

    async def claim_due(self, *, now, lease_expires_at, limit=1):
        self.calls.append(("claim", (now, lease_expires_at, limit)))
        return self.claims

    async def renew_claim(self, claim, *, now, lease_expires_at):
        self.calls.append(("renew", (claim, now, lease_expires_at)))
        return replace(claim, lease_expires_at=lease_expires_at)

    async def associate_publication(self, claim, publication_id, *, now):
        self.calls.append(("associate", (claim, publication_id, now)))
        return claim

    async def complete_phase(self, claim, *, now):
        self.calls.append(("complete", (claim, now)))
        return claim.plan

    async def block_claim(self, claim, *, now):
        self.calls.append(("block", (claim, now)))
        return claim.plan


class _PublicationEnqueuer:
    def __init__(self, result: ScheduledPublicationEnqueue) -> None:
        self.result = result
        self.calls: list[tuple[RuleActivationPlanClaim, datetime]] = []

    async def enqueue_scheduled_publication(self, claim, *, now):
        self.calls.append((claim, now))
        return self.result


class RunRuleActivationPlanWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_claim_batch_does_not_touch_enqueuer(self) -> None:
        queue = _WorkQueue(())
        enqueuer = _PublicationEnqueuer(
            ScheduledPublicationEnqueue(
                ScheduledPublicationState.PENDING, "publication-001"
            )
        )
        worker = RunRuleActivationPlanWorker(
            work_queue=queue,
            publication_enqueuer=enqueuer,
            clock=lambda: _NOW,
        )

        result = await worker.run_once()

        self.assertEqual(result, ())
        self.assertEqual(enqueuer.calls, [])

    async def test_pending_operation_is_associated_without_completing_plan(self) -> None:
        claim = _claim(RuleActivationPlanState.ACTIVATING)
        queue = _WorkQueue((claim,))
        enqueuer = _PublicationEnqueuer(
            ScheduledPublicationEnqueue(
                ScheduledPublicationState.PENDING, "publication-001"
            )
        )
        worker = RunRuleActivationPlanWorker(
            work_queue=queue,
            publication_enqueuer=enqueuer,
            clock=lambda: _NOW,
        )

        result = await worker.run_once(limit=3)

        self.assertEqual(result, (RuleActivationPlanWorkerOutcome.ENQUEUED,))
        self.assertEqual(
            [name for name, _ in queue.calls], ["claim", "renew", "associate"]
        )
        renewed_claim = enqueuer.calls[0][0]
        self.assertEqual(renewed_claim.claim_token, claim.claim_token)
        self.assertEqual(renewed_claim.plan, claim.plan)
        self.assertEqual(
            renewed_claim.lease_expires_at,
            _NOW.replace(microsecond=123000) + timedelta(seconds=60),
        )
        self.assertEqual(enqueuer.calls[0][1].microsecond, 123000)

    async def test_rejected_operation_blocks_claim_without_publication_link(self) -> None:
        claim = _claim(RuleActivationPlanState.RESTORING)
        queue = _WorkQueue((claim,))
        enqueuer = _PublicationEnqueuer(
            ScheduledPublicationEnqueue(
                ScheduledPublicationState.REJECTED,
                None,
                RuleOperationRejection.CONFLICT,
            )
        )
        worker = RunRuleActivationPlanWorker(
            work_queue=queue,
            publication_enqueuer=enqueuer,
            clock=lambda: _NOW,
        )

        result = await worker.run_once()

        self.assertEqual(result, (RuleActivationPlanWorkerOutcome.BLOCKED,))
        self.assertEqual([name for name, _ in queue.calls], ["claim", "renew", "block"])

    async def test_completed_operation_links_publication_then_finishes_phase(self) -> None:
        claim = _claim(RuleActivationPlanState.ACTIVATING)
        queue = _WorkQueue((claim,))
        enqueuer = _PublicationEnqueuer(
            ScheduledPublicationEnqueue(
                ScheduledPublicationState.COMPLETED, "publication-001"
            )
        )
        worker = RunRuleActivationPlanWorker(
            work_queue=queue,
            publication_enqueuer=enqueuer,
            clock=lambda: _NOW,
        )

        result = await worker.run_once()

        self.assertEqual(result, (RuleActivationPlanWorkerOutcome.COMPLETED,))
        self.assertEqual(
            [name for name, _ in queue.calls],
            ["claim", "renew", "associate", "complete"],
        )

    async def test_invalid_batch_size_is_rejected_before_claim(self) -> None:
        queue = _WorkQueue(())
        worker = RunRuleActivationPlanWorker(
            work_queue=queue,
            publication_enqueuer=_PublicationEnqueuer(
                ScheduledPublicationEnqueue(
                    ScheduledPublicationState.PENDING, "publication-001"
                )
            ),
            clock=lambda: _NOW,
        )

        with self.assertRaises(ValueError):
            await worker.run_once(limit=0)

        self.assertEqual(queue.calls, [])


if __name__ == "__main__":
    unittest.main()
