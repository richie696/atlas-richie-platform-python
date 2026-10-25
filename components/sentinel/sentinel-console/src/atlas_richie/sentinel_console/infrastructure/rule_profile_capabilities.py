"""Explicit Console-owned allowlist for rule-profile semantic claims."""

from __future__ import annotations

# Catalog parsing and runtime membership are separate capabilities. The Python
# profile supports all currently modeled rule families; the Java and Go V1
# adapters support only their explicitly modeled FlowRule subset.
SUPPORTED_RULE_CATALOG_CAPABILITIES = {
    "sentinel-python-v1": frozenset(
        {"flow", "degrade", "system", "authority", "param"}
    ),
    "sentinel-java-v1": frozenset({"flow"}),
    "sentinel-go-v1": frozenset({"flow"}),
    "sentinel-rust-v1": frozenset({"flow"}),
}
SUPPORTED_RULE_CATALOG_PROFILES = frozenset(SUPPORTED_RULE_CATALOG_CAPABILITIES)
SUPPORTED_RULE_LOAD_PROFILES = frozenset(
    {
        "sentinel-python-v1",
        "sentinel-java-v1",
        "sentinel-go-v1",
        "sentinel-rust-v1",
    }
)


__all__ = [
    "SUPPORTED_RULE_CATALOG_CAPABILITIES",
    "SUPPORTED_RULE_CATALOG_PROFILES",
    "SUPPORTED_RULE_LOAD_PROFILES",
]
