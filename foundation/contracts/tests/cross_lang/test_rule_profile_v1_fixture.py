import hashlib
import json
from decimal import Decimal
from pathlib import Path


FIXTURE = Path(__file__).parent / "rule_profile_v1/fixtures/equivalent_flow_snapshots.json"


def _canonical_member(resource: str, threshold: str) -> str:
    return (
        "sentinel-flow-member-v1\n"
        f"{len(resource.encode('utf-8'))}:{resource}\n"
        f"{len(threshold.encode('ascii'))}:{threshold}\n"
    )


def test_java_and_go_native_json_map_to_the_same_frozen_flow_profile_vector() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    java = json.loads(fixture["javaSnapshot"])[0]
    go = json.loads(fixture["goSnapshot"])[0]

    assert java["grade"] == 1
    assert java.get("strategy", 0) == 0
    assert java.get("controlBehavior", 0) == 0
    assert java.get("limitApp", "default") == "default"
    assert go["statIntervalInMs"] == 1000
    assert go.get("tokenCalculateStrategy", 0) == 0
    assert go.get("controlBehavior", 0) == 0
    assert go.get("relationStrategy", 0) == 0
    assert go.get("refResource", "") == ""

    java_semantics = (java["resource"], format(Decimal(str(java["count"])).normalize(), "f"))
    go_semantics = (go["resource"], format(Decimal(str(go["threshold"])).normalize(), "f"))
    assert java_semantics == go_semantics == ("GET /api/hello", "3")

    member = hashlib.sha256(_canonical_member(*java_semantics).encode("utf-8")).hexdigest()
    snapshot = hashlib.sha256(
        f"sentinel-flow-snapshot-v1\n{member}\n".encode("utf-8")
    ).hexdigest()
    assert member == fixture["memberFingerprint"]
    assert snapshot == fixture["canonicalRulesSha256"]
