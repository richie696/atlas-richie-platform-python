"""Explicit SQL composition for durable rule-command authority."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from ...application.mutate_rule_set import (
    RuleMutationAuthority,
    RuleMutationBindingReader,
)
from ...application.rule_publication_ports import RulePublicationTargetWriter
from ..security.rule_command_keys import RuleCommandKeyConfiguration
from .rule_mutation_store import SqlAlchemyRuleMutationStore
from .rule_publication_target_reader import SqlAlchemyRulePublicationTargetReader
from .rule_publication_target_writer import SqlAlchemyRulePublicationTargetWriter


def compose_sql_rule_mutation_authority(
    engine: AsyncEngine,
    key_configuration: RuleCommandKeyConfiguration,
    *,
    binding_reader: RuleMutationBindingReader,
) -> RuleMutationAuthority:
    """Compose SQL command storage with independent keys and exact binding facts.

    Binding ownership remains outside the SQL identity database; callers must
    provide its authoritative reader rather than relying on a synthetic copy.
    """
    return SqlAlchemyRuleMutationStore(
        engine,
        fingerprint_keys=key_configuration.fingerprint_keys,
        active_fingerprint_key_id=key_configuration.active_fingerprint_key_id,
        binding_reader=binding_reader,
        publication_target_reader=SqlAlchemyRulePublicationTargetReader(engine),
    )


def compose_sql_rule_publication_target_writer(
    engine: AsyncEngine,
) -> RulePublicationTargetWriter:
    """Compose the trusted server-side target registry writer.

    The returned port is not an HTTP authorization boundary; a future API must
    add admin/session/CSRF/idempotency and audit semantics before exposing it.
    """
    return SqlAlchemyRulePublicationTargetWriter(engine)
