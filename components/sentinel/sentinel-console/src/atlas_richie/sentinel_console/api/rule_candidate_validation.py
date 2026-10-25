"""Authenticated endpoint for exact-profile rule candidate validation."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..application.errors import SessionAuthorityUnavailable
from ..application.read_session import ReadSession
from ..application.rule_binding_errors import InvalidRuleIdentifier
from ..application.rule_snapshot_ports import (
    RuleSetSnapshotAuthorityUnavailable,
    RuleSetSnapshotNotFound,
    RuleSetSnapshotRateLimited,
)
from ..application.rule_validation_ports import (
    RuleCandidateConflict,
    RuleValidationAuthorityUnavailable,
)
from ..application.validate_rule_candidate import ValidateRuleCandidate
from ..domain.rule_bindings import is_rule_binding_identifier
from ..domain.rule_validation import RuleCandidateValidationReceipt
from ..domain.session import SessionCapability
from .browser_origin import normalize_browser_origin
from .browser_security import SESSION_COOKIE_NAME, browser_write_proof
from .http_support import error_response, read_json_object, request_id
from .rule_candidate_parsing import InvalidCandidateShape, parse_rule_candidate
from .system_observation_access import system_read_headers

_MAX_BODY_BYTES = 1_048_576


def rule_candidate_validation_route(
    read_session: ReadSession,
    validator: ValidateRuleCandidate | None,
    allowed_browser_origins: frozenset[str],
) -> Route:
    """Create the admin-only validate endpoint; unconfigured authority fails closed."""
    allowed_origins = frozenset(
        normalize_browser_origin(origin) for origin in allowed_browser_origins
    )
    if not allowed_origins:
        raise ValueError("at least one browser origin must be configured")

    async def validate(request: Request) -> Response:
        request_id_value, valid_request_id = request_id(request)
        if not valid_request_id:
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
        if validator is None:
            return error_response(request_id_value, "service_unavailable", 503)
        try:
            receipt = await validator.execute(
                binding_id,
                candidate,
                actor_id=identity.account_id,
                request_id=request_id_value,
            )
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
        except (
            RuleValidationAuthorityUnavailable,
            RuleSetSnapshotAuthorityUnavailable,
        ):
            return error_response(request_id_value, "service_unavailable", 503)
        except ValueError:
            return error_response(request_id_value, "service_unavailable", 503)

        return JSONResponse(
            rule_validation_body(receipt),
            headers=system_read_headers(request_id_value),
        )

    return Route(
        "/api/v1/rulesets/{bindingId:str}/validate",
        validate,
        methods=["POST"],
    )


def rule_validation_body(
    receipt: RuleCandidateValidationReceipt,
) -> dict[str, object]:
    """Serialize only bounded receipt identities and safe field issue paths."""
    return {
        "bindingId": receipt.binding_id,
        "profile": receipt.profile,
        "baseChecksum": receipt.base_checksum,
        "candidateChecksum": receipt.candidate_checksum,
        "validationId": receipt.validation_id,
        "isPublishable": receipt.is_publishable,
        "issues": [
            {
                "code": issue.code.value,
                "recordIndex": issue.record_index,
                "path": issue.path,
            }
            for issue in receipt.issues
        ],
    }


__all__ = ["rule_candidate_validation_route", "rule_validation_body"]
