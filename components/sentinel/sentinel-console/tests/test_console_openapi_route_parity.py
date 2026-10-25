"""Keep the executable Console route table aligned with its OpenAPI paths."""

from __future__ import annotations

import asyncio
import copy
import json
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from atlas_richie.sentinel_console.api.account_commands import (
    _REQUEST_KEY_PATTERN as _ACCOUNT_REQUEST_KEY_PATTERN,
)
from atlas_richie.sentinel_console.api.accounts import (
    _PAGE_KEYS as _ACCOUNT_QUERY_FIELDS,
)
from atlas_richie.sentinel_console.api.bootstrap_initialization import (
    _REQUEST_KEY_PATTERN as _BOOTSTRAP_REQUEST_KEY_PATTERN,
)
from atlas_richie.sentinel_console.api.fleet_overview import (
    _OPTIONAL_QUERY_FIELDS as _FLEET_OPTIONAL_QUERY_FIELDS,
)
from atlas_richie.sentinel_console.api.fleet_overview import (
    _REQUIRED_QUERY_FIELDS as _FLEET_REQUIRED_QUERY_FIELDS,
)
from atlas_richie.sentinel_console.api.http_support import (
    ERROR_STATUS_BY_CODE,
    error_response,
)
from atlas_richie.sentinel_console.api.incident_query_parsing import (
    _EVIDENCE_OPTIONAL as _INCIDENT_EVIDENCE_OPTIONAL,
)
from atlas_richie.sentinel_console.api.incident_query_parsing import (
    _EVIDENCE_REQUIRED as _INCIDENT_EVIDENCE_REQUIRED,
)
from atlas_richie.sentinel_console.api.incident_query_parsing import (
    _TIMELINE_OPTIONAL as _INCIDENT_TIMELINE_OPTIONAL,
)
from atlas_richie.sentinel_console.api.incident_query_parsing import (
    _TIMELINE_REQUIRED as _INCIDENT_TIMELINE_REQUIRED,
)
from atlas_richie.sentinel_console.api.instance_catalog import (
    _OPTIONAL_QUERY_FIELDS as _INSTANCE_CATALOG_OPTIONAL_QUERY_FIELDS,
)
from atlas_richie.sentinel_console.api.instance_catalog import (
    _REQUIRED_QUERY_FIELDS as _INSTANCE_CATALOG_REQUIRED_QUERY_FIELDS,
)
from atlas_richie.sentinel_console.api.instance_observation import (
    _OPTIONAL_QUERY_FIELDS as _INSTANCE_OBSERVATION_OPTIONAL_QUERY_FIELDS,
)
from atlas_richie.sentinel_console.api.instance_observation import (
    _REQUIRED_QUERY_FIELDS as _INSTANCE_OBSERVATION_REQUIRED_QUERY_FIELDS,
)
from atlas_richie.sentinel_console.api.metrics import (
    _OPTIONAL_QUERY_FIELDS as _METRICS_OPTIONAL_QUERY_FIELDS,
)
from atlas_richie.sentinel_console.api.metrics import (
    _REQUIRED_QUERY_FIELDS as _METRICS_REQUIRED_QUERY_FIELDS,
)
from atlas_richie.sentinel_console.api.query_parsing import (
    MAX_QUERY_PAGE_NUMBER,
    MAX_QUERY_PAGE_SIZE,
    MAX_QUERY_STEP_MS,
    MIN_QUERY_INTEGER,
)
from atlas_richie.sentinel_console.api.registered_source_commands import (
    _REQUEST_KEY_PATTERN as _SOURCE_REQUEST_KEY_PATTERN,
)
from atlas_richie.sentinel_console.api.rule_binding_parsing import (
    _OPTIONAL as _RULE_BINDING_OPTIONAL,
)
from atlas_richie.sentinel_console.api.rule_binding_parsing import (
    _REQUIRED as _RULE_BINDING_REQUIRED,
)
from atlas_richie.sentinel_console.api.rule_commands import (
    _REQUEST_KEY as _RULE_REQUEST_KEY_PATTERN,
)
from atlas_richie.sentinel_console.api.rule_binding_states import (
    _QUERY_KEYS as _RULE_BINDING_STATES_QUERY_FIELDS,
)
from atlas_richie.sentinel_console.api.rule_load_observations import (
    _QUERY_KEYS as _RULE_LOAD_OBSERVATIONS_QUERY_FIELDS,
)
from atlas_richie.sentinel_console.api.system_audit import (
    _ALLOWED_QUERY_KEYS as _SYSTEM_AUDIT_ALLOWED_QUERY_KEYS,
)
from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.account_directory_ports import (
    MAX_ACCOUNT_DIRECTORY_PAGE,
    MAX_ACCOUNT_DIRECTORY_PAGE_SIZE,
)
from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)
from atlas_richie.sentinel_console.domain.incidents import (
    MAX_INCIDENT_CURSOR_LENGTH,
    MAX_INCIDENT_PAGE_SIZE,
)
from atlas_richie.sentinel_console.domain.instance_catalog import (
    METRIC_DENOMINATORS,
    METRIC_UNITS,
)
from atlas_richie.sentinel_console.domain.protocol_negotiations import (
    MAX_PROTOCOL_OBSERVATIONS_PAGE,
)
from atlas_richie.sentinel_console.domain.rule_bindings import (
    is_rule_binding_identifier,
)
from atlas_richie.sentinel_console.domain.rule_publications import (
    MAX_PUBLICATION_RECEIPT_PAGE,
    MAX_PUBLICATION_RECEIPT_PAGE_SIZE,
    PublicationReason,
    PublicationStage,
)
from atlas_richie.sentinel_console.domain.system_connections import (
    ConnectionCapability,
    ConnectionFailureReason,
    ConnectionKind,
    ConnectionState,
)
from atlas_richie.sentinel_console.domain.system_protocols import (
    _MAX_SUPPORTED_VERSIONS,
    ProtocolBoundary,
    ProtocolCompatibility,
)

_HTTP_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})
_OPENAPI_PATH = Path(__file__).resolve().parents[2] / "docs" / "protocol"
_OPENAPI_PATH /= "console-api.openapi.json"
_OPENAPI_08_PATH = _OPENAPI_PATH.with_name("console-api-0.8.0.openapi.json")
_OPENAPI_12_PATH = _OPENAPI_PATH.with_name("console-api-0.12.0.openapi.json")
_OPENAPI_11_PATH = _OPENAPI_PATH.with_name("console-api-0.11.0.openapi.json")
_OPENAPI_10_PATH = _OPENAPI_PATH.with_name("console-api-0.10.0.openapi.json")
_CONTRACT_DOC_PATH = _OPENAPI_PATH.parents[1] / "CONSOLE_API_CONTRACT.md"


def test_openapi_freeze_metadata_matches_console_contract_approval() -> None:
    document = json.loads(_OPENAPI_PATH.read_text(encoding="utf-8"))
    contract = _CONTRACT_DOC_PATH.read_text(encoding="utf-8")

    assert document["info"]["version"] == "0.18.0"
    assert document["x-contract-status"] == "frozen"
    assert "0.18.0 baseline (2026-10-17)" in document["info"]["description"]
    assert "冻结版本 0.18.0" in contract
    assert "0.18.0" in contract
    assert "authorize-local" in contract


def test_console_api_10_operations_remain_wire_identical() -> None:
    previous = json.loads(_OPENAPI_10_PATH.read_text(encoding="utf-8"))
    current = json.loads(_OPENAPI_PATH.read_text(encoding="utf-8"))
    assert previous["info"]["version"] == "0.10.0"
    assert set(previous["paths"]).issubset(current["paths"])
    for path, operations in previous["paths"].items():
        for method, operation in operations.items():
            _assert_historical_operation_compatible(
                operation, current["paths"][path][method], path, method
            )


def test_console_api_11_snapshot_remains_the_candidate_check_only_release() -> None:
    frozen_11 = json.loads(_OPENAPI_11_PATH.read_text(encoding="utf-8"))
    assert frozen_11["info"]["version"] == "0.11.0"
    assert "/api/v2/monitoring/sources/check" in frozen_11["paths"]
    assert "/api/v2/monitoring/sources/checks/{checkId}" in frozen_11["paths"]
    assert "/api/v2/monitoring/sources" not in frozen_11["paths"]


def test_console_api_12_snapshot_remains_safe_reads_only() -> None:
    frozen_12 = json.loads(_OPENAPI_12_PATH.read_text(encoding="utf-8"))
    assert frozen_12["info"]["version"] == "0.12.0"
    assert "/api/v2/monitoring/sources" in frozen_12["paths"]
    assert "/api/v2/monitoring/sources/commands" not in frozen_12["paths"]
    current = json.loads(_OPENAPI_PATH.read_text(encoding="utf-8"))
    for path, operations in frozen_12["paths"].items():
        for method, operation in operations.items():
            _assert_historical_operation_compatible(
                operation, current["paths"][path][method], path, method
            )


def test_console_api_08_operations_remain_wire_identical() -> None:
    previous = json.loads(_OPENAPI_08_PATH.read_text(encoding="utf-8"))
    current = json.loads(_OPENAPI_PATH.read_text(encoding="utf-8"))
    assert previous["info"]["version"] == "0.8.0"
    assert set(previous["paths"]).issubset(current["paths"])
    for path, operations in previous["paths"].items():
        for method, operation in operations.items():
            _assert_historical_operation_compatible(
                operation, current["paths"][path][method], path, method
            )


def _assert_historical_operation_compatible(
    previous: dict[str, object],
    current: dict[str, object],
    path: str,
    method: str,
) -> None:
    """Permit only documented additive audit-action enum values in old reads."""
    comparable = copy.deepcopy(current)
    if previous.get("operationId") == "readSystemAudit":
        previous_parameters = previous["parameters"]
        current_parameters = comparable["parameters"]
        old_action = next(item for item in previous_parameters if item["name"] == "action")
        new_action = next(item for item in current_parameters if item["name"] == "action")
        assert set(old_action["schema"]["enum"]).issubset(new_action["schema"]["enum"])
        new_action["schema"]["enum"] = old_action["schema"]["enum"]

        old_response_schema = previous["responses"]["200"]["content"]["application/json"]["schema"]
        new_response_schema = comparable["responses"]["200"]["content"]["application/json"]["schema"]
        old_query_actions = old_response_schema["properties"]["query"]["properties"]["action"]["anyOf"][0]["enum"]
        new_query_actions = new_response_schema["properties"]["query"]["properties"]["action"]["anyOf"][0]["enum"]
        assert set(old_query_actions).issubset(new_query_actions)
        new_response_schema["properties"]["query"]["properties"]["action"]["anyOf"][0]["enum"] = old_query_actions
        old_record_actions = old_response_schema["properties"]["items"]["items"]["properties"]["action"]["enum"]
        new_record_actions = new_response_schema["properties"]["items"]["items"]["properties"]["action"]["enum"]
        assert set(old_record_actions).issubset(new_record_actions)
        new_response_schema["properties"]["items"]["items"]["properties"]["action"]["enum"] = old_record_actions
    assert comparable == previous, (path, method)


def test_registered_console_routes_match_openapi_paths_and_methods() -> None:
    """Optional identity write routes are included in the production route shape."""
    app = build_app(
        bootstrap_initialization_reader=object(),
        setup_window_reader=object(),
        bootstrap_operator_verifier=object(),
        current_session_reader=object(),
        current_session_revoker=object(),
        account_directory_reader=object(),
        allowed_browser_origins=frozenset({"https://console.example.test"}),
        login_service=object(),
        client_identity_hmac_key=b"contract-test-key" * 2,
        account_command_service=object(),
        own_password_service=object(),
    )

    actual = {
        (_normalize_path(route.path), method)
        for route in app.routes
        if (
            route.path.startswith(("/api/v1/", "/api/v2/"))
            and route.methods is not None
        )
        for method in route.methods
        if method in _HTTP_METHODS
    }
    document = json.loads(_OPENAPI_PATH.read_text(encoding="utf-8"))
    expected = {
        (_normalize_path(path), method.upper())
        for path, operations in document["paths"].items()
        for method in operations
        if method.upper() in _HTTP_METHODS
    }

    assert actual == expected, _route_diff(actual, expected)


def test_publication_receipt_api_remains_read_only_until_trusted_write_contract() -> (
    None
):
    """Option A approval does not authorize an unauthenticated runtime ingress."""
    document = json.loads(_OPENAPI_PATH.read_text(encoding="utf-8"))
    receipt_path = "/api/v1/rulesets/{bindingId}/publications/{publicationId}/receipts"

    assert set(document["paths"][receipt_path]) == {"get"}


def test_openapi_metric_examples_cover_backend_metric_registry() -> None:
    """Examples cover every metric and match its backend unit and aggregation basis."""
    document = json.loads(_OPENAPI_PATH.read_text(encoding="utf-8"))
    definitions = frozenset(_metric_definitions(document))
    expected = frozenset(
        (metric, unit, METRIC_DENOMINATORS[metric].value)
        for metric, unit in METRIC_UNITS.items()
    )

    assert definitions == expected
    operation = document["paths"]["/api/v1/metrics/query"]["get"]
    metrics_parameter = next(
        parameter
        for parameter in operation["parameters"]
        if parameter["name"] == "metrics"
    )
    metric_alternation = "|".join(re.escape(metric) for metric in sorted(METRIC_UNITS))
    expected_pattern = f"^(?:{metric_alternation})(?:,(?:{metric_alternation}))*$"
    assert expected_pattern in {
        constraint["pattern"]
        for constraint in metrics_parameter["schema"]["allOf"]
        if "pattern" in constraint
    }


def test_openapi_publication_stage_and_reason_match_backend_enums() -> None:
    """Read-back mismatch is a failure reason, not a publication lifecycle state."""
    document = json.loads(_OPENAPI_PATH.read_text(encoding="utf-8"))
    operation = document["paths"]["/api/v1/rulesets/{bindingId}/publications"]["get"]
    response = operation["responses"]["200"]["content"]["application/json"]["schema"]
    phase = response["properties"]["items"]["items"]["properties"]["validation"][
        "properties"
    ]
    reason_schema = phase["reason"]
    reason_values = next(
        branch["enum"]
        for branch in reason_schema["anyOf"]
        if branch.get("type") == "string" and isinstance(branch.get("enum"), list)
    )

    assert phase["state"]["enum"] == [state.value for state in PublicationStage]
    assert reason_values == [reason.value for reason in PublicationReason]
    assert "readback_mismatch" not in phase["state"]["enum"]
    assert "readback_mismatch" in reason_values


def _metric_definitions(value: object) -> Iterator[tuple[str, str, str]]:
    if isinstance(value, dict):
        metric = value.get("metric")
        unit = value.get("unit")
        denominator = value.get("denominator")
        if (
            isinstance(metric, str)
            and metric in METRIC_UNITS
            and isinstance(unit, str)
            and isinstance(denominator, str)
        ):
            yield metric, unit, denominator
        for nested in value.values():
            yield from _metric_definitions(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _metric_definitions(nested)


def test_openapi_operations_have_complete_wire_contract_metadata() -> None:
    """Every documented operation exposes its stable request/response boundary."""
    document = json.loads(_OPENAPI_PATH.read_text(encoding="utf-8"))
    security_schemes = document["components"]["securitySchemes"]
    operation_ids: set[str] = set()

    for path, path_item in document["paths"].items():
        for method, operation in path_item.items():
            operation_id = operation["operationId"]
            assert isinstance(operation_id, str) and operation_id.strip(), (
                path,
                method,
            )
            assert operation_id not in operation_ids, operation_id
            operation_ids.add(operation_id)

            assert (
                isinstance(operation.get("summary"), str)
                and operation["summary"].strip()
            )
            assert len(operation.get("tags", [])) == 1
            semantic_rules = operation.get("x-semantic-rules")
            assert isinstance(semantic_rules, list) and semantic_rules
            assert all(
                isinstance(rule, str) and rule.strip() for rule in semantic_rules
            )
            assert isinstance(operation.get("x-unknown-outcome"), bool)

            security = operation.get("security")
            assert isinstance(security, list), (
                operation_id,
                "security must be explicit",
            )
            for requirement in security:
                assert isinstance(requirement, dict)
                assert set(requirement).issubset(security_schemes), (
                    operation_id,
                    requirement,
                )
            csrf_header_required = any(
                parameter.get("name") == "x-sentinel-csrf"
                and parameter.get("in") == "header"
                and parameter.get("required") is True
                for parameter in operation.get("parameters", [])
            )
            if csrf_header_required:
                assert security and all(
                    "CsrfCookie" in requirement for requirement in security
                ), operation_id

            parameters = operation.get("parameters", [])
            query_parameters = [
                parameter for parameter in parameters if parameter.get("in") == "query"
            ]
            if query_parameters:
                assert operation.get("x-query-policy") == {
                    "unknownParameters": "reject",
                    "duplicateParameters": "reject",
                    "rejection": {
                        "status": ERROR_STATUS_BY_CODE["invalid_request"],
                        "code": "invalid_request",
                    },
                }, operation_id
                for parameter in query_parameters:
                    expected_encoding = (
                        "canonical-decimal"
                        if parameter.get("schema", {}).get("type") == "integer"
                        else None
                    )
                    assert (
                        parameter.get("x-query-integer-encoding") == expected_encoding
                    ), (
                        operation_id,
                        parameter.get("name"),
                    )
            else:
                assert "x-query-policy" not in operation, operation_id
            request_id = next(
                (
                    parameter
                    for parameter in parameters
                    if parameter.get("name") == "x-request-id"
                    and parameter.get("in") == "header"
                ),
                None,
            )
            assert request_id is not None and request_id["required"] is True, (
                operation_id
            )

            responses = operation["responses"]
            success_responses = [
                (status, response)
                for status, response in responses.items()
                if status.startswith("2")
            ]
            assert success_responses, operation_id
            for status, response in success_responses:
                if status == "204":
                    assert "content" not in response, operation_id
                else:
                    assert "application/json" in response.get("content", {}), (
                        operation_id
                    )

            error_responses = [
                (status, response)
                for status, response in responses.items()
                if status.startswith(("4", "5"))
            ]
            assert error_responses, operation_id
            for status, response in error_responses:
                allowed_codes = response.get("x-allowed-error-codes")
                assert isinstance(allowed_codes, list) and allowed_codes, (
                    operation_id,
                    status,
                )
                error_schema = response["content"]["application/json"]["schema"]
                error_property = error_schema["properties"]["error"]
                assert "code" in error_property["required"], (operation_id, status)
                if status == "429":
                    assert "rate_limited" in allowed_codes, (operation_id, status)
                    assert "retryAfterMs" in error_property["required"], (
                        operation_id,
                        status,
                    )
                    retry_after_schema = error_property["properties"]["retryAfterMs"]
                    assert retry_after_schema["type"] == "integer", (
                        operation_id,
                        status,
                    )
                    assert retry_after_schema["minimum"] == 0, (operation_id, status)
                    assert retry_after_schema["maximum"] == 300_000, (
                        operation_id,
                        status,
                    )

            if method in {"post", "put", "patch"} and operation_id != "logout":
                body = operation.get("requestBody")
                assert body is not None and body["required"] is True, operation_id
                assert "application/json" in body.get("content", {}), operation_id
                _assert_closed_request_objects(
                    body["content"]["application/json"]["schema"], operation_id
                )


def _assert_closed_request_objects(schema: object, operation_id: str) -> None:
    """Keep generated request DTOs closed so unknown fields are never silently ignored."""
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            assert schema.get("additionalProperties") is False, operation_id
        for nested in schema.values():
            _assert_closed_request_objects(nested, operation_id)
    elif isinstance(schema, list):
        for nested in schema:
            _assert_closed_request_objects(nested, operation_id)


def test_openapi_declares_the_complete_operation_permission_matrix() -> None:
    """Role/capability requirements are machine-readable, explicit and exhaustive."""
    document = json.loads(_OPENAPI_PATH.read_text(encoding="utf-8"))
    expected: dict[str, tuple[str | None, tuple[str, ...]]] = {
        "listAccounts": ("admin", ()),
        "readAccount": ("admin", ()),
        "mutateAccount": ("admin", ()),
        "readAccountOperation": ("admin", ()),
        "readMetrics": (None, ("metrics:view",)),
        "readFleet": (None, ("metrics:view",)),
        "readInstanceCatalog": (None, ("metrics:view",)),
        "readInstanceObservation": (None, ("metrics:view",)),
        "readIncidentTimeline": (None, ("metrics:view",)),
        "readIncidentEvidence": (None, ("metrics:view",)),
        "readAgentReportingProtocolObservations": (None, ()),
        "readIncidentEventProtocolObservations": (None, ()),
        "readSystemAudit": ("admin", ()),
        "readSystemDeploymentGuides": (None, ()),
        "readHostMetrics": (None, ("metrics:view",)),
        "readHostAssociations": (None, ()),
        "putHostAssociation": ("admin", ()),
        "deleteHostAssociation": ("admin", ()),
        "readHostAssociationOperation": ("admin", ()),
        "readRuleLoadObservationHistory": (None, ()),
        "readRegisteredSources": ("admin", ()),
        "checkRegisteredSource": ("admin", ()),
        "mutateRegisteredSource": ("admin", ()),
        "readRegisteredSourceOperation": ("admin", ()),
        "checkMonitoringSource": ("admin", ()),
            "mutateMonitoringSource": ("admin", ()),
            "readMonitoringSourceOperation": ("admin", ()),
        "readMonitoringSources": (None, ()),
        "readMonitoringSource": ("admin", ()),
        "createRuleBinding": ("admin", ("rules:write",)),
        "readBindingRegistration": ("admin", ("rules:write",)),
        "readRuleDrafts": (None, ("rules:write",)),
        "readRuleDraft": (None, ("rules:write",)),
        "validateRuleCandidate": (None, ("rules:write",)),
        "compareRuleCandidate": (None, ("rules:write",)),
        "mutateRuleSet": ("admin", ("rules:write",)),
        "readRuleOperation": ("admin", ()),
    }
    actual: dict[str, tuple[str | None, tuple[str, ...]]] = {}
    for path, path_item in document["paths"].items():
        for method, operation in path_item.items():
            operation_id = operation["operationId"]
            access = operation.get("x-required-access")
            assert isinstance(access, dict), (path, method, "missing x-required-access")
            assert set(access) == {"role", "capabilities"}, (operation_id, access)
            role = access["role"]
            capabilities = access["capabilities"]
            assert role is None or role == "admin", (operation_id, role)
            assert isinstance(capabilities, list), (operation_id, capabilities)
            assert set(capabilities).issubset({"metrics:view", "rules:write"}), (
                operation_id
            )
            actual[operation_id] = (role, tuple(capabilities))

    complete_expected = {
        operation["operationId"]: expected.get(operation["operationId"], (None, ()))
        for item in document["paths"].values()
        for operation in item.values()
    }
    assert actual == complete_expected


def test_console_contract_document_matches_current_access_and_error_summary() -> None:
    """Keep human contract summaries aligned with current role and error facts."""
    contract = _CONTRACT_DOC_PATH.read_text(encoding="utf-8")
    access_summary = contract.split("## 1. 最小权限", maxsplit=1)[1].split(
        "## 2. 配置键映射", maxsplit=1
    )[0]
    error_summary = contract.split("## 7. 错误约定", maxsplit=1)[1].split(
        "## 8. 五项决策", maxsplit=1
    )[0]

    assert "capability_denied" not in contract
    assert "不提供独立授予 capability" in access_summary
    assert "version_conflict" not in error_summary
    assert "readback_mismatch" not in error_summary

    documented_statuses: dict[str, int] = {}
    for status_text, codes_text in re.findall(
        r"\|\s*(\d{3})\s*\|\s*([^|]+)\|", error_summary
    ):
        status = int(status_text)
        codes = re.findall(r"`([^`]+)`", codes_text)
        assert codes, (status, codes_text)
        for code in codes:
            assert code not in documented_statuses, code
            documented_statuses[code] = status

    assert documented_statuses == dict(ERROR_STATUS_BY_CODE)


def test_openapi_declares_request_id_rejection_for_every_operation() -> None:
    """Every required request ID can be rejected as invalid_request / 400."""
    document = json.loads(_OPENAPI_PATH.read_text(encoding="utf-8"))
    for path_item in document["paths"].values():
        for operation in path_item.values():
            operation_id = operation["operationId"]
            request_id = next(
                (
                    parameter
                    for parameter in operation.get("parameters", [])
                    if parameter.get("name") == "x-request-id"
                    and parameter.get("in") == "header"
                ),
                None,
            )
            assert request_id is not None and request_id["required"] is True, (
                operation_id
            )
            assert "duplicate" in request_id.get("description", "").lower(), (
                operation_id,
                "request ID multiplicity must be explicit in OpenAPI",
            )
            bad_request_codes = (
                operation["responses"].get("400", {}).get("x-allowed-error-codes", [])
            )
            assert "invalid_request" in bad_request_codes, operation_id


def test_every_runtime_operation_rejects_missing_invalid_or_duplicate_request_id() -> (
    None
):
    """The executable routes reject malformed correlation IDs consistently."""

    async def verify_runtime_contract() -> None:
        app = build_app(
            bootstrap_initialization_reader=object(),
            setup_window_reader=object(),
            bootstrap_operator_verifier=object(),
            current_session_reader=object(),
            current_session_revoker=object(),
            account_directory_reader=object(),
            allowed_browser_origins=frozenset({"https://console.example.test"}),
            login_service=object(),
            client_identity_hmac_key=b"contract-test-key" * 2,
            account_command_service=object(),
            own_password_service=object(),
        )
        document = json.loads(_OPENAPI_PATH.read_text(encoding="utf-8"))
        invalid_request_id = "not a valid request id"

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://console.example.test"
        ) as client:
            for path, path_item in document["paths"].items():
                runtime_path = re.sub(r"\{[^}]+\}", "contract-probe", path)
                for method, operation in path_item.items():
                    if method.upper() not in _HTTP_METHODS:
                        continue
                    response = await client.request(
                        method.upper(),
                        runtime_path,
                        headers={"x-request-id": invalid_request_id},
                    )
                    operation_id = operation["operationId"]
                    assert response.status_code == 400, operation_id
                    assert response.json()["error"]["code"] == "invalid_request", (
                        operation_id,
                        response.text,
                    )
                    assert response.headers["x-request-id"] != invalid_request_id
                    assert (
                        response.json()["error"]["requestId"]
                        == response.headers["x-request-id"]
                    )

                    missing_response = await client.request(
                        method.upper(),
                        runtime_path,
                    )
                    assert missing_response.status_code == 400, operation_id
                    assert missing_response.json()["error"]["code"] == (
                        "invalid_request"
                    ), (operation_id, missing_response.text)
                    assert missing_response.headers.get("x-request-id")
                    assert (
                        missing_response.json()["error"]["requestId"]
                        == (missing_response.headers["x-request-id"])
                    )

                    duplicate_request_ids = [
                        ("x-request-id", "contract-first"),
                        ("x-request-id", "contract-second"),
                    ]
                    duplicate_response = await client.request(
                        method.upper(),
                        runtime_path,
                        headers=duplicate_request_ids,
                    )
                    assert duplicate_response.status_code == 400, operation_id
                    assert duplicate_response.json()["error"]["code"] == (
                        "invalid_request"
                    ), (operation_id, duplicate_response.text)
                    assert duplicate_response.headers["x-request-id"] not in {
                        "contract-first",
                        "contract-second",
                    }
                    assert (
                        duplicate_response.json()["error"]["requestId"]
                        == (duplicate_response.headers["x-request-id"])
                    )

    asyncio.run(verify_runtime_contract())


def test_openapi_candidate_validation_errors_match_non_idempotent_routes() -> None:
    """Validation and diff POSTs declare CSRF failures but not command-only errors."""
    document = json.loads(_OPENAPI_PATH.read_text(encoding="utf-8"))
    operations = {
        operation["operationId"]: operation
        for path_item in document["paths"].values()
        for operation in path_item.values()
    }
    expected_codes = {
        "conflict",
        "csrf_failed",
        "forbidden",
        "invalid_request",
        "not_found",
        "rate_limited",
        "service_unavailable",
        "unauthenticated",
        "validation_failed",
    }

    for operation_id in ("validateRuleCandidate", "compareRuleCandidate"):
        operation = operations[operation_id]
        actual_codes = {
            code
            for response in operation["responses"].values()
            for code in response.get("x-allowed-error-codes", [])
        }
        assert actual_codes == expected_codes, operation_id


def test_openapi_bootstrap_authorization_errors_match_exchange_route() -> None:
    """Operator-code exchange exposes its bootstrap-proof failure, not grant errors."""
    document = json.loads(_OPENAPI_PATH.read_text(encoding="utf-8"))
    operation = next(
        operation
        for path_item in document["paths"].values()
        for operation in path_item.values()
        if operation["operationId"] == "authorizeBootstrap"
    )
    actual_codes = {
        code
        for response in operation["responses"].values()
        for code in response.get("x-allowed-error-codes", [])
    }

    assert actual_codes == {
        "conflict",
        "csrf_failed",
        "forbidden",
        "invalid_request",
        "rate_limited",
        "service_unavailable",
    }
    assert any("CsrfCookie" in requirement for requirement in operation["security"])
    assert any(
        parameter.get("name") == "x-sentinel-csrf"
        and parameter.get("in") == "header"
        and parameter.get("required") is True
        for parameter in operation["parameters"]
    )


def test_openapi_read_observation_errors_match_route_capabilities() -> None:
    """Read-only observation contracts exclude unreachable role/rate failures."""
    document = json.loads(_OPENAPI_PATH.read_text(encoding="utf-8"))
    operations = {
        operation["operationId"]: operation
        for path_item in document["paths"].values()
        for operation in path_item.values()
    }
    expected = {
        "readObservationCatalog": {
            "invalid_request",
            "unauthenticated",
            "service_unavailable",
        },
        "readSystemConnections": {
            "invalid_request",
            "unauthenticated",
            "service_unavailable",
        },
        "readSystemProtocols": {
            "invalid_request",
            "unauthenticated",
            "service_unavailable",
        },
        "readAgentReportingProtocolObservations": {
            "invalid_request",
            "unauthenticated",
            "service_unavailable",
        },
        "readIncidentEventProtocolObservations": {
            "invalid_request",
            "unauthenticated",
            "service_unavailable",
        },
        "readSystemAudit": {
            "invalid_request",
            "unauthenticated",
            "forbidden",
            "service_unavailable",
        },
        "readRegisteredSources": {
            "invalid_request",
            "unauthenticated",
            "forbidden",
            "service_unavailable",
        },
    }

    for operation_id, expected_codes in expected.items():
        actual_codes = {
            code
            for response in operations[operation_id]["responses"].values()
            for code in response.get("x-allowed-error-codes", [])
        }
        assert actual_codes == expected_codes, operation_id


def test_openapi_account_errors_match_read_and_command_routes() -> None:
    """Account reads exclude rate limiting; writes expose their concrete failures."""
    document = json.loads(_OPENAPI_PATH.read_text(encoding="utf-8"))
    operations = {
        operation["operationId"]: operation
        for path_item in document["paths"].values()
        for operation in path_item.values()
    }
    expected = {
        "listAccounts": {
            "invalid_request",
            "unauthenticated",
            "forbidden",
            "service_unavailable",
        },
        "readAccount": {
            "invalid_request",
            "unauthenticated",
            "forbidden",
            "service_unavailable",
        },
        "mutateAccount": {
            "invalid_request",
            "unauthenticated",
            "forbidden",
            "csrf_failed",
            "idempotency_conflict",
            "service_unavailable",
        },
        "readAccountOperation": {
            "invalid_request",
            "unauthenticated",
            "forbidden",
            "service_unavailable",
        },
    }

    for operation_id, expected_codes in expected.items():
        actual_codes = {
            code
            for response in operations[operation_id]["responses"].values()
            for code in response.get("x-allowed-error-codes", [])
        }
        assert actual_codes == expected_codes, operation_id


def test_openapi_own_password_errors_match_current_account_route() -> None:
    """Own-password change has rate limiting but no role-based forbidden path."""
    document = json.loads(_OPENAPI_PATH.read_text(encoding="utf-8"))
    operation = next(
        operation
        for path_item in document["paths"].values()
        for operation in path_item.values()
        if operation["operationId"] == "changeOwnPassword"
    )
    actual_codes = {
        code
        for response in operation["responses"].values()
        for code in response.get("x-allowed-error-codes", [])
    }

    assert actual_codes == {
        "invalid_request",
        "current_password_invalid",
        "unauthenticated",
        "csrf_failed",
        "validation_failed",
        "rate_limited",
        "service_unavailable",
    }
    success_schema = operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ]
    assert (
        success_schema["properties"]["sessionDisposition"]["const"] == "reauthenticate"
    )


def test_openapi_bootstrap_and_session_access_errors_match_routes() -> None:
    """Anonymous bootstrap/session reads and login/logout expose distinct failures."""
    document = json.loads(_OPENAPI_PATH.read_text(encoding="utf-8"))
    operations = {
        operation["operationId"]: operation
        for path_item in document["paths"].values()
        for operation in path_item.values()
    }
    expected = {
        "readBootstrap": {"invalid_request", "service_unavailable"},
        "readSession": {"invalid_request", "service_unavailable"},
        "login": {
            "invalid_request",
            "unauthenticated",
            "csrf_failed",
            "rate_limited",
            "service_unavailable",
        },
        "logout": {
            "invalid_request",
            "unauthenticated",
            "csrf_failed",
            "service_unavailable",
        },
    }

    for operation_id, expected_codes in expected.items():
        operation = operations[operation_id]
        actual_codes = {
            code
            for response in operation["responses"].values()
            for code in response.get("x-allowed-error-codes", [])
        }
        assert actual_codes == expected_codes, operation_id
        if operation_id in {"login", "logout"}:
            assert any(
                parameter.get("name") == "x-sentinel-csrf"
                and parameter.get("in") == "header"
                and parameter.get("required") is True
                for parameter in operation.get("parameters", [])
            ), operation_id


def test_openapi_rule_endpoints_match_individual_route_errors() -> None:
    """Ruleset read, target, mutation and operation routes have distinct errors."""
    document = json.loads(_OPENAPI_PATH.read_text(encoding="utf-8"))
    operations = {
        operation["operationId"]: operation
        for path_item in document["paths"].values()
        for operation in path_item.values()
    }
    session_read = {
        "invalid_request",
        "unauthenticated",
        "not_found",
        "rate_limited",
        "service_unavailable",
    }
    expected = {
        "createRuleBinding": {
            "invalid_request",
            "unauthenticated",
            "forbidden",
            "csrf_failed",
            "idempotency_conflict",
            "validation_failed",
            "conflict",
            "service_unavailable",
        },
        "readRuleBindings": session_read,
        "readRuleSetSnapshot": session_read,
        "readRuleDrafts": session_read | {"forbidden"},
        "readRuleDraft": session_read | {"forbidden"},
        "readRuleVersions": session_read,
        "readRuleVersion": session_read,
        "readRulePublications": session_read,
        "readRulePublication": session_read,
        "readRulePublicationReceipts": session_read,
        "readRuleActivationPlans": session_read,
        "readRulePublicationTarget": {
            "invalid_request",
            "unauthenticated",
            "service_unavailable",
        },
        "mutateRuleSet": {
            "invalid_request",
            "unauthenticated",
            "forbidden",
            "csrf_failed",
            "idempotency_conflict",
            "validation_failed",
            "rate_limited",
            "service_unavailable",
        },
        "readRuleOperation": session_read | {"forbidden"},
    }

    for operation_id, expected_codes in expected.items():
        actual_codes = {
            code
            for response in operations[operation_id]["responses"].values()
            for code in response.get("x-allowed-error-codes", [])
        }
        assert actual_codes == expected_codes, operation_id


def test_openapi_metrics_and_incident_errors_match_individual_routes() -> None:
    """Observation routes declare scope, absence, retirement and throttle errors."""
    document = json.loads(_OPENAPI_PATH.read_text(encoding="utf-8"))
    operations = {
        operation["operationId"]: operation
        for path_item in document["paths"].values()
        for operation in path_item.values()
    }
    scoped_read = {
        "invalid_request",
        "unauthenticated",
        "forbidden",
        "not_found",
        "rate_limited",
        "service_unavailable",
    }
    expected = {
        "readFleet": scoped_read,
        "readInstanceCatalog": scoped_read,
        "readInstanceObservation": scoped_read | {"target_retired"},
        "readMetrics": scoped_read | {"target_retired"},
        "readIncidentTimeline": scoped_read,
        "readIncidentEvidence": scoped_read,
    }

    for operation_id, expected_codes in expected.items():
        actual_codes = {
            code
            for response in operations[operation_id]["responses"].values()
            for code in response.get("x-allowed-error-codes", [])
        }
        assert actual_codes == expected_codes, operation_id


def test_openapi_registered_source_errors_match_check_and_command_routes() -> None:
    """Source check, mutation and receipt lookup separate transport errors."""
    document = json.loads(_OPENAPI_PATH.read_text(encoding="utf-8"))
    operations = {
        operation["operationId"]: operation
        for path_item in document["paths"].values()
        for operation in path_item.values()
    }
    expected = {
        "readRegisteredSources": {
            "invalid_request",
            "unauthenticated",
            "forbidden",
            "service_unavailable",
        },
        "checkRegisteredSource": {
            "invalid_request",
            "unauthenticated",
            "forbidden",
            "csrf_failed",
            "rate_limited",
            "service_unavailable",
        },
        "mutateRegisteredSource": {
            "invalid_request",
            "unauthenticated",
            "forbidden",
            "csrf_failed",
            "idempotency_conflict",
            "validation_failed",
            "rate_limited",
            "service_unavailable",
        },
        "readRegisteredSourceOperation": {
            "invalid_request",
            "unauthenticated",
            "forbidden",
            "not_found",
            "rate_limited",
            "service_unavailable",
        },
    }

    for operation_id, expected_codes in expected.items():
        actual_codes = {
            code
            for response in operations[operation_id]["responses"].values()
            for code in response.get("x-allowed-error-codes", [])
        }
        assert actual_codes == expected_codes, operation_id


def test_openapi_bootstrap_setup_errors_match_each_route() -> None:
    """Setup-check and recovery routes declare only their concrete failure modes."""
    document = json.loads(_OPENAPI_PATH.read_text(encoding="utf-8"))
    operations = {
        operation["operationId"]: operation
        for path_item in document["paths"].values()
        for operation in path_item.values()
    }
    expected = {
        "checkBootstrapDatabase": {
            "bootstrap_unauthorized",
            "csrf_failed",
            "invalid_request",
            "service_unavailable",
        },
        "checkBootstrapSource": {
            "bootstrap_unauthorized",
            "csrf_failed",
            "invalid_request",
            "service_unavailable",
        },
        "initializeConsole": {
            "bootstrap_unauthorized",
            "csrf_failed",
            "idempotency_conflict",
            "invalid_request",
            "service_unavailable",
        },
        "readInitialization": {
            "bootstrap_unauthorized",
            "invalid_request",
            "service_unavailable",
        },
    }

    for operation_id, expected_codes in expected.items():
        actual_codes = {
            code
            for response in operations[operation_id]["responses"].values()
            for code in response.get("x-allowed-error-codes", [])
        }
        assert actual_codes == expected_codes, operation_id


def test_openapi_models_optional_session_and_csrf_cookie_proofs() -> None:
    """OpenAPI distinguishes anonymous access from the CSRF cookie proof."""
    document = json.loads(_OPENAPI_PATH.read_text(encoding="utf-8"))
    schemes = document["components"]["securitySchemes"]
    assert schemes["CsrfCookie"]["in"] == "cookie"
    assert schemes["CsrfCookie"]["name"] == "__Host-sentinel_csrf"

    operations = {
        operation["operationId"]: operation
        for path_item in document["paths"].values()
        for operation in path_item.values()
    }
    for operation_id in ("login", "logout"):
        operation = operations[operation_id]
        assert any(
            "CsrfCookie" in requirement
            and "x-sentinel-csrf"
            in {parameter["name"] for parameter in operation["parameters"]}
            for requirement in operation["security"]
        ), operation_id

    login_security = operations["login"]["security"]
    assert {"CsrfCookie": []} in login_security
    assert {"BrowserSession": [], "CsrfCookie": []} in login_security

    session_security = operations["readSession"]["security"]
    assert {} in session_security
    assert {"BrowserSession": []} in session_security

    logout_security = operations["logout"]["security"]
    assert logout_security == [{"BrowserSession": [], "CsrfCookie": []}]


def test_frontend_openapi_and_python_share_error_code_status_registry() -> None:
    """Every documented error code has one status shared by both runtimes."""
    document = json.loads(_OPENAPI_PATH.read_text(encoding="utf-8"))
    assert document["x-error-status"] == dict(ERROR_STATUS_BY_CODE)

    for path, path_item in document["paths"].items():
        for method, operation in path_item.items():
            for status, response in operation["responses"].items():
                for error_code in response.get("x-allowed-error-codes", []):
                    assert ERROR_STATUS_BY_CODE[error_code] == int(status), (
                        path,
                        method,
                        error_code,
                        status,
                    )


def test_openapi_pagination_bounds_match_console_wire_contract() -> None:
    """The generated UI schema and Python cursor bounds must stay aligned."""
    document = json.loads(_OPENAPI_PATH.read_text(encoding="utf-8"))
    page_parameters = 0
    page_size_parameters = 0

    for path, path_item in document["paths"].items():
        for operation in path_item.values():
            for parameter in operation.get("parameters", []):
                if parameter.get("in") != "query":
                    continue
                schema = parameter["schema"]
                if parameter.get("name") == "page":
                    page_parameters += 1
                    assert schema["minimum"] == 1, path
                    expected_maximum = (
                        10_000
                        if path == "/api/v2/monitoring/host-associations"
                        else MAX_PROTOCOL_OBSERVATIONS_PAGE
                    )
                    assert schema["maximum"] == expected_maximum, path
                elif parameter.get("name") == "pageSize":
                    page_size_parameters += 1
                    assert schema["minimum"] == 1, path
                    assert schema["maximum"] == 100, path

    assert page_parameters > 0
    assert page_size_parameters > 0
    incident_parameters = document["paths"]["/api/v1/incidents"]["get"]["parameters"]
    incident_cursor = next(
        parameter
        for parameter in incident_parameters
        if parameter.get("in") == "query" and parameter.get("name") == "cursor"
    )
    assert incident_cursor["schema"]["maxLength"] == MAX_INCIDENT_CURSOR_LENGTH
    cursor_patterns = [
        constraint["pattern"]
        for constraint in incident_cursor["schema"]["allOf"]
        if "pattern" in constraint
    ]
    non_blank_pattern = next(
        pattern for pattern in cursor_patterns if "\\u001c" in pattern
    )
    assert re.search(non_blank_pattern, "opaque\ufefftoken")
    for blank in ("\x1c", "\x85", "\ufeff", "\u3000"):
        assert not re.search(non_blank_pattern, blank)
    assert MAX_INCIDENT_PAGE_SIZE == 100


def test_openapi_system_protocol_snapshot_limit_matches_known_boundaries() -> None:
    """A snapshot cannot document more protocol facts than the domain can represent."""
    document = json.loads(_OPENAPI_PATH.read_text(encoding="utf-8"))
    schema = document["paths"]["/api/v1/system/protocols"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]
    protocol_schema = schema["properties"]["items"]["items"]

    assert schema["properties"]["items"]["maxItems"] == len(ProtocolBoundary)
    assert set(protocol_schema["properties"]["kind"]["enum"]) == {
        boundary.value for boundary in ProtocolBoundary
    }
    assert set(protocol_schema["properties"]["compatibility"]["enum"]) == {
        value.value for value in ProtocolCompatibility
    }
    assert (
        protocol_schema["properties"]["supported"]["maxItems"]
        == _MAX_SUPPORTED_VERSIONS
    )


def test_openapi_system_connection_enums_match_domain_facts() -> None:
    """Connection labels and provider facts stay aligned across both runtimes."""
    document = json.loads(_OPENAPI_PATH.read_text(encoding="utf-8"))
    item_schema = document["paths"]["/api/v1/system/connections"]["get"]["responses"][
        "200"
    ]["content"]["application/json"]["schema"]["properties"]["items"]["items"]
    properties = item_schema["properties"]
    provider_enum = properties["provider"]["anyOf"][0]["enum"]
    reason_enum = properties["reason"]["anyOf"][0]["enum"]

    assert set(properties["kind"]["enum"]) == {value.value for value in ConnectionKind}
    assert set(properties["state"]["enum"]) == {
        value.value for value in ConnectionState
    }
    assert set(provider_enum) == {value.value for value in ConfigurationSourceProvider}
    assert set(properties["capabilities"]["items"]["enum"]) == {
        value.value for value in ConnectionCapability
    }
    assert set(reason_enum) == {value.value for value in ConnectionFailureReason}


def test_fleet_openapi_query_parameters_match_runtime_allowlist() -> None:
    """Fleet scope cannot advertise instance/resource filters the route rejects."""
    document = json.loads(_OPENAPI_PATH.read_text(encoding="utf-8"))
    operation = document["paths"]["/api/v1/fleet/overview"]["get"]
    documented = {
        parameter["name"]
        for parameter in operation.get("parameters", [])
        if parameter.get("in") == "query"
    }

    assert documented == _FLEET_REQUIRED_QUERY_FIELDS | _FLEET_OPTIONAL_QUERY_FIELDS
    assert "instanceId" not in documented
    assert "resource" not in documented
    scope = next(
        parameter
        for parameter in operation["parameters"]
        if parameter.get("in") == "query" and parameter.get("name") == "scope"
    )
    assert scope["schema"]["enum"] == ["fleet", "application"]


def test_observation_and_rule_openapi_query_parameters_match_runtime_allowlists() -> (
    None
):
    """Query fields advertised to clients must be accepted by their Python route."""
    document = json.loads(_OPENAPI_PATH.read_text(encoding="utf-8"))
    runtime_fields = {
        "listAccounts": _ACCOUNT_QUERY_FIELDS,
        "readMetrics": _METRICS_REQUIRED_QUERY_FIELDS | _METRICS_OPTIONAL_QUERY_FIELDS,
        "readFleet": _FLEET_REQUIRED_QUERY_FIELDS | _FLEET_OPTIONAL_QUERY_FIELDS,
        "readInstanceCatalog": (
            _INSTANCE_CATALOG_REQUIRED_QUERY_FIELDS
            | _INSTANCE_CATALOG_OPTIONAL_QUERY_FIELDS
        ),
        "readInstanceObservation": (
            _INSTANCE_OBSERVATION_REQUIRED_QUERY_FIELDS
            | _INSTANCE_OBSERVATION_OPTIONAL_QUERY_FIELDS
        ),
        "readIncidentTimeline": (
            _INCIDENT_TIMELINE_REQUIRED | _INCIDENT_TIMELINE_OPTIONAL
        ),
        "readIncidentEvidence": (
            _INCIDENT_EVIDENCE_REQUIRED | _INCIDENT_EVIDENCE_OPTIONAL
        ),
        "readSystemAudit": _SYSTEM_AUDIT_ALLOWED_QUERY_KEYS,
        "readAgentReportingProtocolObservations": {"page", "pageSize"},
        "readIncidentEventProtocolObservations": {"page", "pageSize"},
        "readRuleBindings": _RULE_BINDING_REQUIRED | _RULE_BINDING_OPTIONAL,
        "readRuleCatalog": {"environmentId", "appId", "kind", "search", "page", "pageSize"},
        "readRuleBindingObservedStates": _RULE_BINDING_STATES_QUERY_FIELDS,
        "readRuleLoadObservations": _RULE_LOAD_OBSERVATIONS_QUERY_FIELDS,
        "readRulePublicationReceipts": {"page", "pageSize"},
        "readHostMetrics": {"from", "to", "stepMs"},
        "readHostAssociations": {
            "environmentId", "sourceId", "appId", "instanceId", "page", "pageSize"
        },
        "readRuleLoadObservationHistory": {
            "environmentId", "appId", "bindingId", "instanceId", "page", "pageSize"
        },
    }
    operations = {
        operation["operationId"]: operation
        for path_item in document["paths"].values()
        for operation in path_item.values()
    }

    query_operation_ids = {
        operation["operationId"]
        for operation in operations.values()
        if any(
            parameter.get("in") == "query"
            for parameter in operation.get("parameters", [])
        )
    }
    assert set(runtime_fields) == query_operation_ids
    for operation_id, expected_fields in runtime_fields.items():
        documented_fields = {
            parameter["name"]
            for parameter in operations[operation_id].get("parameters", [])
            if parameter.get("in") == "query"
        }
        assert documented_fields == expected_fields, operation_id

    for operation_id in ("readIncidentTimeline", "readIncidentEvidence"):
        operation = operations[operation_id]
        parameters = operation.get("parameters", [])
        assert "resource" not in {parameter["name"] for parameter in parameters}
        scope = next(
            parameter
            for parameter in parameters
            if parameter.get("in") == "query" and parameter.get("name") == "scope"
        )
        assert scope["schema"]["enum"] == ["fleet", "application", "process"]

    instance_detail = operations["readInstanceObservation"]
    instance_scope = next(
        parameter
        for parameter in instance_detail.get("parameters", [])
        if parameter.get("in") == "query" and parameter.get("name") == "scope"
    )
    assert instance_scope["schema"]["enum"] == ["host", "container", "process"]
    instance_response = instance_detail["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    metric_scope = instance_response["properties"]["metrics"]["anyOf"][0]["properties"][
        "query"
    ]["properties"]["context"]["properties"]["scope"]
    assert metric_scope["enum"] == ["host", "container", "process"]

    instance_catalog = operations["readInstanceCatalog"]
    catalog_parameters = {
        parameter["name"]: parameter
        for parameter in instance_catalog.get("parameters", [])
        if parameter.get("in") == "query"
    }
    assert "instanceId" not in catalog_parameters
    assert "resource" not in catalog_parameters
    assert catalog_parameters["scope"]["schema"]["enum"] == ["fleet", "application"]
    catalog_response = instance_catalog["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    catalog_scope = catalog_response["properties"]["query"]["properties"]["context"][
        "properties"
    ]["scope"]
    assert catalog_scope["enum"] == ["fleet", "application"]


def test_openapi_integer_query_bounds_match_runtime_parser_limits() -> None:
    """Integer wire bounds stay aligned with the Python parser's source values."""
    document = json.loads(_OPENAPI_PATH.read_text(encoding="utf-8"))
    operations = {
        operation["operationId"]: operation
        for path_item in document["paths"].values()
        for operation in path_item.values()
    }
    expected = {
        "listAccounts": {
            "page": (MIN_QUERY_INTEGER, MAX_ACCOUNT_DIRECTORY_PAGE),
            "pageSize": (MIN_QUERY_INTEGER, MAX_ACCOUNT_DIRECTORY_PAGE_SIZE),
        },
        "readMetrics": {
            "stepMs": (MIN_QUERY_INTEGER, MAX_QUERY_STEP_MS),
        },
        "readFleet": {
            "page": (MIN_QUERY_INTEGER, MAX_QUERY_PAGE_NUMBER),
            "pageSize": (MIN_QUERY_INTEGER, MAX_QUERY_PAGE_SIZE),
            "stepMs": (MIN_QUERY_INTEGER, MAX_QUERY_STEP_MS),
        },
        "readInstanceCatalog": {
            "page": (MIN_QUERY_INTEGER, MAX_QUERY_PAGE_NUMBER),
            "pageSize": (MIN_QUERY_INTEGER, MAX_QUERY_PAGE_SIZE),
        },
        "readInstanceObservation": {
            "stepMs": (MIN_QUERY_INTEGER, MAX_QUERY_STEP_MS),
        },
        "readIncidentTimeline": {
            "pageSize": (MIN_QUERY_INTEGER, MAX_INCIDENT_PAGE_SIZE),
        },
        "readIncidentEvidence": {},
        "readSystemAudit": {
            "page": (MIN_QUERY_INTEGER, MAX_QUERY_PAGE_NUMBER),
            "pageSize": (MIN_QUERY_INTEGER, MAX_QUERY_PAGE_SIZE),
        },
        "readRuleBindings": {
            "page": (MIN_QUERY_INTEGER, MAX_QUERY_PAGE_NUMBER),
            "pageSize": (MIN_QUERY_INTEGER, MAX_QUERY_PAGE_SIZE),
        },
        "readRulePublicationReceipts": {
            "page": (MIN_QUERY_INTEGER, MAX_PUBLICATION_RECEIPT_PAGE),
            "pageSize": (MIN_QUERY_INTEGER, MAX_PUBLICATION_RECEIPT_PAGE_SIZE),
        },
    }

    for operation_id, expected_parameters in expected.items():
        operation = operations[operation_id]
        integer_parameters = {
            parameter["name"]: parameter["schema"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "query"
            and parameter.get("schema", {}).get("type") == "integer"
        }
        assert set(integer_parameters) == set(expected_parameters), operation_id
        for name, (minimum, maximum) in expected_parameters.items():
            assert integer_parameters[name]["minimum"] == minimum, (
                operation_id,
                name,
            )
            assert integer_parameters[name]["maximum"] == maximum, (
                operation_id,
                name,
            )


def test_openapi_bounded_strings_declare_utf16_wire_limits() -> None:
    """Python and JavaScript count the same UTF-16 units for bounded strings."""
    document = json.loads(_OPENAPI_PATH.read_text(encoding="utf-8"))
    bounded_strings = list(_bounded_string_schemas(document))
    assert bounded_strings
    for owner, schema in bounded_strings:
        assert schema.get("x-max-utf16-code-units") == schema["maxLength"], owner
    assert is_rule_binding_identifier("a" * 200)
    assert is_rule_binding_identifier("😀" * 100)
    assert not is_rule_binding_identifier("😀" * 101)


def test_idempotent_commands_align_header_body_and_operation_lookup() -> None:
    """Commands carry one request key through header/body and expose safe lookup."""
    document = json.loads(_OPENAPI_PATH.read_text(encoding="utf-8"))
    operations = {
        operation["operationId"]: (path, method, operation)
        for path, path_item in document["paths"].items()
        for method, operation in path_item.items()
    }
    command_ids = {
        "initializeConsole",
        "mutateAccount",
        "mutateRegisteredSource",
        "mutateRuleSet",
    }

    for operation_id in command_ids:
        path, _method, operation = operations[operation_id]
        idempotency_headers = [
            parameter
            for parameter in operation["parameters"]
            if parameter.get("in") == "header"
            and parameter.get("name") == "idempotency-key"
        ]
        assert len(idempotency_headers) == 1
        assert idempotency_headers[0]["required"] is True
        assert operation["x-unknown-outcome"] is True

        body_schema = operation["requestBody"]["content"]["application/json"]["schema"]
        variants = body_schema.get("oneOf", [body_schema])
        assert variants, operation_id
        for variant in variants:
            request_key = variant.get("properties", {}).get("requestKey")
            assert request_key is not None, (operation_id, variant)
            assert "requestKey" in variant.get("required", []), operation_id
            _assert_request_key_schema(request_key, operation_id)

        lookup_path = path.rsplit("/", 1)[0] + "/operations/{requestKey}"
        assert lookup_path in document["paths"], (operation_id, lookup_path)
        lookup = document["paths"][lookup_path]["get"]
        lookup_key = next(
            parameter
            for parameter in lookup["parameters"]
            if parameter.get("in") == "path" and parameter.get("name") == "requestKey"
        )
        _assert_request_key_schema(lookup_key["schema"], operation_id)

        for status, response in operation["responses"].items():
            if not status.startswith("2"):
                continue
            schema = (
                response.get("content", {}).get("application/json", {}).get("schema")
            )
            if schema is not None:
                for request_key_schema in _schemas_named(schema, "requestKey"):
                    _assert_request_key_schema(
                        request_key_schema, (operation_id, status)
                    )

    python_patterns = (
        _ACCOUNT_REQUEST_KEY_PATTERN,
        _BOOTSTRAP_REQUEST_KEY_PATTERN,
        _SOURCE_REQUEST_KEY_PATTERN,
        _RULE_REQUEST_KEY_PATTERN,
    )
    for pattern in python_patterns:
        assert pattern.fullmatch("a"), pattern.pattern
        assert pattern.fullmatch("_-.:"), pattern.pattern
        assert pattern.fullmatch("a" * 128), pattern.pattern
        assert pattern.fullmatch("a" * 129) is None, pattern.pattern
        assert pattern.fullmatch("bad/key") is None, pattern.pattern


def _assert_request_key_schema(schema: dict[str, object], owner: object) -> None:
    assert schema["minLength"] == 1, owner
    assert schema["maxLength"] == 128, owner
    assert "^[A-Za-z0-9._:-]+$" in _schema_patterns(schema), owner


def _schema_patterns(value: object) -> set[str]:
    if isinstance(value, dict):
        patterns = (
            {value["pattern"]} if isinstance(value.get("pattern"), str) else set()
        )
        for nested in value.values():
            patterns.update(_schema_patterns(nested))
        return patterns
    if isinstance(value, list):
        return {pattern for nested in value for pattern in _schema_patterns(nested)}
    return set()


def _schemas_named(value: object, property_name: str) -> list[dict[str, object]]:
    if isinstance(value, dict):
        schemas = []
        properties = value.get("properties")
        if isinstance(properties, dict) and isinstance(
            properties.get(property_name), dict
        ):
            schemas.append(properties[property_name])
        for nested in value.values():
            schemas.extend(_schemas_named(nested, property_name))
        return schemas
    if isinstance(value, list):
        return [
            schema
            for nested in value
            for schema in _schemas_named(nested, property_name)
        ]
    return []


def _bounded_string_schemas(value: object, owner: str = "$root"):
    if isinstance(value, dict):
        if value.get("type") == "string" and isinstance(value.get("maxLength"), int):
            yield owner, value
        for key, nested in value.items():
            yield from _bounded_string_schemas(nested, f"{owner}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            yield from _bounded_string_schemas(nested, f"{owner}[{index}]")


def test_error_response_rejects_unknown_or_mismatched_code_status_pairs() -> None:
    """Route adapters cannot accidentally emit a non-canonical status for a code."""
    response = error_response("request-1", "invalid_request", 400)
    assert response.status_code == 400

    with pytest.raises(ValueError, match="error code/status contract mismatch"):
        error_response("request-1", "invalid_request", 422)
    with pytest.raises(ValueError, match="error code/status contract mismatch"):
        error_response("request-1", "unregistered_error", 500)


def test_rate_limited_error_response_requires_bounded_retry_delay() -> None:
    with pytest.raises(ValueError, match="require an integer retry delay"):
        error_response("request-1", "rate_limited", 429)
    for invalid_retry_after_ms in (True, 1.5):
        with pytest.raises(ValueError, match="require an integer retry delay"):
            error_response(
                "request-1",
                "rate_limited",
                429,
                retry_after_ms=invalid_retry_after_ms,
            )

    response = error_response("request-1", "rate_limited", 429, retry_after_ms=300_001)

    assert response.status_code == 429
    assert json.loads(response.body) == {
        "error": {
            "code": "rate_limited",
            "requestId": "request-1",
            "retryAfterMs": 300_000,
        }
    }


def _normalize_path(path: str) -> str:
    """Ignore framework-specific names/type annotations for path parameters."""
    return re.sub(r"\{[^{}]+\}", "{}", path)


def _route_diff(actual: set[tuple[str, str]], expected: set[tuple[str, str]]) -> str:
    missing_from_openapi = sorted(actual - expected)
    missing_from_app = sorted(expected - actual)
    return (
        f"Runtime-only operations: {missing_from_openapi}; "
        f"OpenAPI-only operations: {missing_from_app}"
    )
