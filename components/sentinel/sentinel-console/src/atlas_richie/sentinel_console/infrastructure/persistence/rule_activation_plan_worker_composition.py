"""Explicit assembly for SQL-backed activation-plan scheduling."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable

from sqlalchemy.ext.asyncio import AsyncEngine

from ...application.rule_activation_plan_ports import (
    RuleActivationPlanPublicationEnqueuer,
)
from ...application.run_rule_activation_plan_worker import RunRuleActivationPlanWorker
from .rule_activation_plan_work_queue import SqlAlchemyRuleActivationPlanWorkQueue


def create_rule_activation_plan_worker(
    engine: AsyncEngine,
    *,
    publication_enqueuer: RuleActivationPlanPublicationEnqueuer,
    clock: Callable[[], datetime],
    lease_duration: timedelta = timedelta(seconds=60),
) -> RunRuleActivationPlanWorker:
    """Compose the durable SQL claim queue with an explicit publish authority."""
    return RunRuleActivationPlanWorker(
        work_queue=SqlAlchemyRuleActivationPlanWorkQueue(engine),
        publication_enqueuer=publication_enqueuer,
        clock=clock,
        lease_duration=lease_duration,
    )


__all__ = ["create_rule_activation_plan_worker"]
