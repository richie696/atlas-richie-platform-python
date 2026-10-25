"""Read one original rule-binding registration result without replaying its command."""

from __future__ import annotations

from datetime import datetime

from .rule_binding_ports import (
    RuleBindingRegistrationReceipt,
    RuleBindingRegistrationReceiptReader,
    RuleBindingRegistrationReceiptStatus,
)


class ReadRuleBindingRegistration:
    """Resolve one actor-authorized binding creation request to a safe receipt."""

    def __init__(self, reader: RuleBindingRegistrationReceiptReader) -> None:
        self._reader = reader

    async def execute(
        self,
        binding_id: str,
        request_key: str,
        *,
        actor_id: str,
        session_digest: str,
        now: datetime,
    ) -> RuleBindingRegistrationReceipt:
        """Return completed only for the exact original actor, binding, and key."""
        if not all(
            isinstance(value, str) and value.strip()
            for value in (binding_id, request_key, actor_id, session_digest)
        ):
            raise ValueError("binding registration lookup identity is invalid")
        binding = await self._reader.read_rule_binding_registration(
            binding_id,
            request_key,
            actor_id=actor_id,
            session_digest=session_digest,
            now=now,
        )
        if binding is None:
            return RuleBindingRegistrationReceipt(
                request_key,
                binding_id,
                RuleBindingRegistrationReceiptStatus.NOT_FOUND,
                None,
            )
        if binding.id != binding_id:
            raise ValueError("binding registration reader returned another binding")
        return RuleBindingRegistrationReceipt(
            request_key,
            binding_id,
            RuleBindingRegistrationReceiptStatus.COMPLETED,
            binding,
        )


__all__ = ["ReadRuleBindingRegistration"]
