"""Mutation tests ensure the archive gate cannot conceal contract regressions."""

import copy
import json
from pathlib import Path

import pytest
from test_console_openapi_route_parity import (
    _assert_historical_operation_compatible,
    _normalize_new_password_sample_values,
)

_DIRECTORY = Path(__file__).resolve().parents[2] / "docs" / "protocol"
_PATH = "/api/v1/accounts/commands"


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
    "archive",
    sorted(_DIRECTORY.glob("console-api-*.openapi.json")),
    ids=lambda p: p.name,
)
def test_every_available_archive_preserves_its_declared_operations(archive):
    previous = json.loads(archive.read_text())
    current = json.loads((_DIRECTORY / "console-api.openapi.json").read_text())
    for path, methods in previous["paths"].items():
        for method, operation in methods.items():
            _assert_historical_operation_compatible(
                operation, current["paths"][path][method], path, method
            )


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
