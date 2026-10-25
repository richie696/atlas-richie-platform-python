"""Mutation tests ensure the archive gate cannot conceal contract regressions."""

import copy
import json
import re
from pathlib import Path

import pytest
from test_console_openapi_route_parity import (
    _assert_historical_operation_compatible,
    _normalize_new_password_sample_values,
)

_DIRECTORY = Path(__file__).resolve().parents[2] / "docs" / "protocol"
_INDEX_PATH = _DIRECTORY / "README.md"
_PATH = "/api/v1/accounts/commands"

# 归档清单以协议索引声明为唯一事实源：门禁按索引逐个校验，索引与磁盘必须完全一致。
# 归档缺失时门禁必须立即失败，不得因为 glob 结果变少而静默降低兼容保证。
_DECLARED_ARCHIVES_PATTERN = re.compile(r"现有归档版本：([0-9.、]+)。")


def _declared_archive_versions() -> tuple[str, ...]:
    """Read the frozen archive list declared by the protocol index."""
    match = _DECLARED_ARCHIVES_PATTERN.search(_INDEX_PATH.read_text(encoding="utf-8"))
    assert match is not None, "协议索引未声明归档版本清单，兼容门禁无法确定基准"
    versions = tuple(part for part in match.group(1).split("、") if part)
    assert versions, "协议索引声明的归档清单为空"
    return versions


def _archive_path(version: str) -> Path:
    return _DIRECTORY / f"console-api-{version}.openapi.json"


def _archive_versions_on_disk() -> set[str]:
    return {
        path.name.removeprefix("console-api-").removesuffix(".openapi.json")
        for path in _DIRECTORY.glob("console-api-*.openapi.json")
    }


def _operations():
    previous = json.loads((_DIRECTORY / "console-api-0.8.0.openapi.json").read_text())
    current = json.loads((_DIRECTORY / "console-api.openapi.json").read_text())
    return previous["paths"][_PATH]["post"], current["paths"][_PATH]["post"]


def test_approved_account_lifecycle_delta_is_accepted_without_mutation():
    previous, current = _operations()
    before = copy.deepcopy(current)
    _assert_historical_operation_compatible(previous, current, _PATH, "post")
    assert current == before


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_schema_field",
        "missing_variant",
        "missing_response",
        "missing_parameter",
        "missing_semantic_rule",
        "missing_enum_value",
        "unknown_variant",
        "unknown_enum_value",
        "unknown_semantic_rule",
        "new_required_field",
        "duplicate_variant",
        "changed_password_pattern",
    ],
)
def test_unapproved_contract_mutations_are_rejected(mutation):
    previous, current = _operations()
    variants = current["requestBody"]["content"]["application/json"]["schema"]["oneOf"]
    reason = current["responses"]["200"]["content"]["application/json"]["schema"][
        "oneOf"
    ][1]["properties"]["reason"]["enum"]
    if mutation == "missing_schema_field":
        del variants[0]["properties"]["input"]["properties"]["username"]
    elif mutation == "missing_variant":
        del variants[0]
    elif mutation == "missing_response":
        del current["responses"]["403"]
    elif mutation == "missing_parameter":
        current["parameters"].pop()
    elif mutation == "missing_semantic_rule":
        current["x-semantic-rules"].pop(0)
    elif mutation == "missing_enum_value":
        reason.remove("validation")
    elif mutation == "unknown_variant":
        variant = copy.deepcopy(variants[-1])
        variant["properties"]["kind"]["const"] = "grant_superuser"
        variants.append(variant)
    elif mutation == "unknown_enum_value":
        reason.append("unapproved_rejection")
    elif mutation == "unknown_semantic_rule":
        current["x-semantic-rules"].append(
            "Unauthenticated callers may reset accounts."
        )
    elif mutation == "new_required_field":
        variants[0]["required"].append("unapproved_requirement")
    elif mutation == "duplicate_variant":
        variants.append(copy.deepcopy(variants[0]))
    elif mutation == "changed_password_pattern":
        variants[0]["properties"]["input"]["properties"]["password"]["pattern"] = (
            "^.{8,16}$"
        )
    with pytest.raises(AssertionError):
        _assert_historical_operation_compatible(previous, current, _PATH, "post")


@pytest.mark.parametrize(
    "version",
    _declared_archive_versions(),
    ids=lambda version: version,
)
def test_every_available_archive_preserves_its_declared_operations(version):
    archive = _archive_path(version)
    assert archive.exists(), (
        f"协议索引声明的归档 {archive.name} 在磁盘上缺失；"
        "兼容门禁必须因归档缺失而失败，不得静默降低兼容保证"
    )
    previous = json.loads(archive.read_text())
    current = json.loads((_DIRECTORY / "console-api.openapi.json").read_text())
    for path, methods in previous["paths"].items():
        for method, operation in methods.items():
            _assert_historical_operation_compatible(
                operation, current["paths"][path][method], path, method
            )


def test_every_declared_archive_is_present_on_disk():
    """归档缺失即失败：索引声明的每个版本都必须有实际快照文件。"""
    missing = [
        version
        for version in _declared_archive_versions()
        if not _archive_path(version).exists()
    ]
    assert not missing, f"协议索引声明但磁盘缺失的历史归档：{missing}"


def test_archive_directory_contains_exactly_the_declared_archives():
    """索引与磁盘必须双向一致：既不缺，也不允许多出未声明的快照。"""
    declared = set(_declared_archive_versions())
    on_disk = _archive_versions_on_disk()
    assert on_disk == declared, (
        f"历史归档集合与协议索引声明不一致："
        f"仅磁盘有={sorted(on_disk - declared)}，仅索引有={sorted(declared - on_disk)}"
    )


def test_protocol_index_declares_a_non_empty_archive_list():
    """索引清单本身的可解析性：格式被改动时门禁必须报出明确原因。"""
    versions = _declared_archive_versions()
    assert versions == tuple(sorted(versions, key=lambda item: [int(part) for part in item.split(".")]))
    assert all(re.fullmatch(r"\d+\.\d+\.\d+", version) for version in versions)


@pytest.mark.parametrize(
    "sample", ["media_success", "media_failure", "exchange_success", "exchange_failure"]
)
def test_unapproved_new_password_sample_values_are_not_normalized(sample):
    path = "/api/v1/auth/password"
    previous = json.loads((_DIRECTORY / "console-api-0.8.0.openapi.json").read_text())[
        "paths"
    ][path]["post"]
    current = json.loads((_DIRECTORY / "console-api.openapi.json").read_text())[
        "paths"
    ][path]["post"]
    if sample.startswith("media"):
        name = (
            "change_own_password_and_reauthenticate"
            if sample.endswith("success")
            else "change_own_password_rejects_wrong_current_password"
        )
        body = current["requestBody"]["content"]["application/json"]["examples"][name][
            "value"
        ]
    else:
        body = current["x-contract-examples"][0 if sample.endswith("success") else 1][
            "request"
        ]["body"]
    body["newPassword"] = "Unreviewed-Example-123"
    with pytest.raises(AssertionError):
        _assert_historical_operation_compatible(previous, current, path, "post")


def test_sample_normalization_does_not_rewrite_same_named_fields_elsewhere():
    value = {"responses": {"newPassword": "synthetic-new-password-0123"}}
    before = copy.deepcopy(value)
    assert _normalize_new_password_sample_values(value) == before
