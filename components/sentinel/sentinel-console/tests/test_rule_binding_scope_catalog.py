"""Domain boundaries for rule scopes independent from observation reporters."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime

from atlas_richie.sentinel_console.domain.rule_bindings import (
    RuleBindingScopeApplication,
    RuleBindingScopeCatalog,
    RuleBindingScopeEnvironment,
)


class RuleBindingScopeCatalogTests(unittest.TestCase):
    def test_empty_scope_catalog_is_a_valid_authoritative_snapshot(self) -> None:
        snapshot = RuleBindingScopeCatalog(datetime(2026, 10, 15, tzinfo=UTC), (), ())

        self.assertEqual(snapshot.environments, ())
        self.assertEqual(snapshot.applications, ())

    def test_scope_catalog_requires_unique_scoped_ids_and_known_environment(
        self,
    ) -> None:
        environment = RuleBindingScopeEnvironment("prod", "prod")
        application = RuleBindingScopeApplication("checkout", "prod", "checkout")

        with self.assertRaises(ValueError):
            RuleBindingScopeCatalog(
                datetime(2026, 10, 15, tzinfo=UTC),
                (environment, environment),
                (application,),
            )
        with self.assertRaises(ValueError):
            RuleBindingScopeCatalog(
                datetime(2026, 10, 15, tzinfo=UTC),
                (environment,),
                (application, application),
            )
        with self.assertRaises(ValueError):
            RuleBindingScopeCatalog(
                datetime(2026, 10, 15, tzinfo=UTC),
                (environment,),
                (RuleBindingScopeApplication("checkout", "missing", "checkout"),),
            )


if __name__ == "__main__":
    unittest.main()
