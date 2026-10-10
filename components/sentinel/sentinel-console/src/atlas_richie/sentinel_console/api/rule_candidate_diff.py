"""Authenticated, read-only rule candidate comparison endpoint."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..application.compare_rule_candidate import (
    CompareRuleCandidate,
    RuleCandidateConflict,
)
from ..application.errors import SessionAuthorityUnavailable
from ..application.read_session import ReadSession
from ..application.rule_binding_errors import InvalidRuleIdentifier
from ..application.rule_snapshot_ports import (
    RuleSetSnapshotAuthorityUnavailable,
    RuleSetSnapshotNotFound,
    RuleSetSnapshotRateLimited,
)
from ..domain.rule_bindings import is_rule_binding_identifier
from ..domain.session import SessionCapability
from ..domain.rule_candidates import RuleChange, RuleSetDiff
from .browser_origin import normalize_browser_origin
from .browser_security import SESSION_COOKIE_NAME, browser_write_proof
from .http_support import error_response, read_json_object, request_id
from .rule_candidate_parsing import InvalidCandidateShape, parse_rule_candidate
from .rule_snapshot_serializers import rule_value_body
from .system_observation_access import system_read_headers

_MAX_BODY_BYTES = 1_048_576


def rule_candidate_diff_route(
    read_session: ReadSession,
    compare_candidate: CompareRuleCandidate | None,
    allowed_browser_origins: frozenset[str],
) -> Route:
    """Create the admin-only exact-baseline comparison endpoint."""
    allowed_origins = frozenset(
        normalize_browser_origin(origin) for origin in allowed_browser_origins
    )
    if not allowed_origins:
        raise ValueError("at least one browser origin must be configured")

    async def compare(request: Request) -> Response:
        request_ids = request.headers.getlist("x-request-id")
        request_id_value, valid_request_id = request_id(request)
        if len(request_ids) != 1 or not valid_request_id:
            return error_response(request_id_value, "invalid_request", 400)
        proof, failure = browser_write_proof(request, allowed_origins)
        if failure is not None:
            return error_response(request_id_value, failure[0], failure[1])
        assert proof is not None

        binding_id = request.path_params["bindingId"]
        if not is_rule_binding_identifier(binding_id):
            return error_response(request_id_value, "invalid_request", 400)
        try:
            identity = await read_session.execute(
                request.cookies.get(SESSION_COOKIE_NAME)
            )
        except SessionAuthorityUnavailable:
            return error_response(request_id_value, "service_unavailable", 503)
        if identity is None:
            return error_response(request_id_value, "unauthenticated", 401)
        if SessionCapability.RULES_WRITE not in identity.capabilities:
            return error_response(request_id_value, "forbidden", 403)

        candidate_body = await read_json_object(request, _MAX_BODY_BYTES)
        try:
            candidate = parse_rule_candidate(candidate_body)
        except InvalidCandidateShape:
            return error_response(request_id_value, "invalid_request", 400)
        except (TypeError, ValueError):
            return error_response(request_id_value, "validation_failed", 422)
        if compare_candidate is None:
            return error_response(request_id_value, "service_unavailable", 503)
        try:
            result = await compare_candidate.execute(binding_id, candidate)
        except InvalidRuleIdentifier:
            return error_response(request_id_value, "invalid_request", 400)
        except RuleCandidateConflict:
            return error_response(request_id_value, "conflict", 409)
        except RuleSetSnapshotNotFound:
            return error_response(request_id_value, "not_found", 404)
        except RuleSetSnapshotRateLimited as exc:
            return error_response(
                request_id_value,
                "rate_limited",
                429,
                retry_after_ms=exc.retry_after_ms,
            )
        except (RuleSetSnapshotAuthorityUnavailable, SessionAuthorityUnavailable):
            return error_response(request_id_value, "service_unavailable", 503)
        except ValueError:
            return error_response(request_id_value, "service_unavailable", 503)

        return JSONResponse(
            rule_set_diff_body(result),
            headers=system_read_headers(request_id_value),
        )

    return Route(
        "/api/v1/rulesets/{bindingId:str}/diff",
        compare,
        methods=["POST"],
    )


def rule_set_diff_body(diff: RuleSetDiff) -> dict[str, object]:
    """Project domain changes into the bounded public API response shape."""
    return {
        "bindingId": diff.binding_id,
        "baseChecksum": diff.base_checksum,
        "candidateChecksum": diff.candidate_checksum,
        "changes": [_rule_change_body(change) for change in diff.changes],
    }


def _rule_change_body(change: RuleChange) -> dict[str, object]:
    body: dict[str, object] = {"operation": change.operation.value}
    if change.record_id is not None:
        body["recordId"] = change.record_id
    if change.before is not None:
        body["before"] = rule_value_body(change.before)
    if change.after is not None:
        body["after"] = rule_value_body(change.after)
    return body
