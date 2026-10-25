from atlas_richie.sentinel_console.infrastructure.persistence.rule_load_observation_reader import (
    _snapshot_view,
)
from atlas_richie.sentinel_console.infrastructure.rule_profile_capabilities import (
    SUPPORTED_RULE_CATALOG_CAPABILITIES,
    SUPPORTED_RULE_CATALOG_PROFILES,
    SUPPORTED_RULE_LOAD_PROFILES,
)


def test_java_go_and_rust_profiles_enable_flow_catalog_and_membership_separately() -> (
    None
):
    assert "sentinel-java-v1" in SUPPORTED_RULE_LOAD_PROFILES
    assert "sentinel-go-v1" in SUPPORTED_RULE_LOAD_PROFILES
    assert "sentinel-rust-v1" in SUPPORTED_RULE_LOAD_PROFILES
    assert "sentinel-java-v1" in SUPPORTED_RULE_CATALOG_PROFILES
    assert "sentinel-go-v1" in SUPPORTED_RULE_CATALOG_PROFILES
    assert "sentinel-rust-v1" in SUPPORTED_RULE_CATALOG_PROFILES
    assert SUPPORTED_RULE_CATALOG_CAPABILITIES["sentinel-java-v1"] == frozenset(
        {"flow"}
    )
    assert SUPPORTED_RULE_CATALOG_CAPABILITIES["sentinel-go-v1"] == frozenset({"flow"})
    assert SUPPORTED_RULE_CATALOG_CAPABILITIES["sentinel-rust-v1"] == frozenset({"flow"})

    snapshot = {
        "source_revision": None,
        "canonical_rules_sha256": "3f83eb929e9a20a9028da7f372aa1e012ceeb6cadf78f8f81763b8f7e53cbb82",
        "membership_complete": True,
        "members": [
            {
                "rule_kind": "flow",
                "fingerprint_sha256": "9c11dd44491ed7625dad136d1238c8a23dcbb39c65b3db7d1e3220c65589047d",
            }
        ],
    }

    for profile in ("sentinel-java-v1", "sentinel-go-v1", "sentinel-rust-v1"):
        view = _snapshot_view(snapshot, profile)
        assert view is not None
        assert view.membership_complete is True
        assert len(view.members) == 1

    unknown = _snapshot_view(snapshot, "sentinel-unknown-v1")
    assert unknown is not None
    assert unknown.membership_complete is False
    assert unknown.members == ()
