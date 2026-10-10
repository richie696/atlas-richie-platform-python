"""Register one exact ruleset binding through its durable authority."""

from __future__ import annotations

from datetime import datetime

from ..domain.rule_bindings import RuleBinding
from .rule_binding_ports import RegisterRuleBinding, RuleBindingRegistrationAuthority


class RegisterRuleBindingUseCase:
    """Delegate a validated binding registration to its transactional owner."""

    def __init__(self, authority: RuleBindingRegistrationAuthority) -> None:
        self._authority = authority

    async def execute(
        self,
        command: RegisterRuleBinding,
        *,
        actor_id: str,
        session_digest: str,
        csrf_digest: str,
        request_id: str,
        now: datetime,
    ) -> RuleBinding:
        """Register or recover the same idempotent binding command."""
        if not isinstance(command, RegisterRuleBinding):
            raise ValueError("rule binding registration command is invalid")
        binding = await self._authority.register_rule_binding(
            command,
            actor_id=actor_id,
            session_digest=session_digest,
            csrf_digest=csrf_digest,
            request_id=request_id,
            now=now,
        )
        if (
            not isinstance(binding, RuleBinding)
            or binding.id != command.binding_id
            or binding.environment_id != command.environment_id
            or binding.app_id != command.app_id
            or binding.kind is not command.kind
            or binding.profile != command.profile
            or binding.source_id != command.target.source_id
        ):
            raise ValueError("rule binding registration result does not match")
        return binding


__all__ = ["RegisterRuleBindingUseCase"]
