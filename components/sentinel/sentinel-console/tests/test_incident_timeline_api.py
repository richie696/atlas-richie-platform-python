"""Incident timeline API contract against isolated session/event authorities."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime

from httpx import ASGITransport, AsyncClient
from openapi_contract_support import assert_openapi_response
from session_test_doubles import UnusedSessionRevoker

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.errors import SessionAuthorityUnavailable
from atlas_richie.sentinel_console.application.incident_evidence_ports import (
    IncidentEvidenceAuthorityUnavailable,
    IncidentEvidenceNotFound,
    IncidentEvidenceRateLimited,
)
from atlas_richie.sentinel_console.application.incident_timeline_ports import (
    IncidentTimelineAuthorityUnavailable,
    IncidentTimelineRateLimited,
    IncidentTimelineTargetNotFound,
)
from atlas_richie.sentinel_console.domain.incidents import (
    IncidentCategory,
    IncidentDetailQuery,
    IncidentEvidence,
    IncidentEvidenceCompleteness,
    IncidentEvidenceFact,
    IncidentFact,
    IncidentFactCode,
    IncidentPage,
    IncidentQuery,
    IncidentSeverity,
    IncidentStatistics,
    IncidentSuggestedView,
    ObservedIncident,
    RelatedRuleIdentity,
)
from atlas_richie.sentinel_console.domain.instance_catalog import (
    ObservationScope,
    ObservationWindow,
)
from atlas_richie.sentinel_console.domain.instance_observation import ObservationContext
from atlas_richie.sentinel_console.domain.session import ActiveAccountSession

_REQUEST_HEADERS = {"x-request-id": "incident-timeline-read-1"}
_OPAQUE_SESSION = "synthetic-session-token-00000001"
_FROM = datetime(2026, 10, 9, 0, 45, tzinfo=UTC)
_TO = datetime(2026, 10, 9, 1, 0, tzinfo=UTC)
_AS_OF = datetime(2026, 10, 9, 1, 0, 1, 123000, tzinfo=UTC)


class _Initialized:
    async def is_initialized(self) -> bool:
        return True


class _OpenSetupWindow:
    async def is_setup_window_open(self) -> bool:
        return False


class _OperatorVerifier:
    async def is_current_operator(self, opaque_session: str | None) -> bool:
        return False


class _SessionReader:
    def __init__(self, role: str | None) -> None:
        self.role = role

    async def read_active_session(self, session_digest: str):
        if self.role == "unavailable":
            raise SessionAuthorityUnavailable("private session authority detail")
        if self.role is None:
            return None
        return ActiveAccountSession("account-1", "operator", self.role, "epoch-1")


class _IncidentReader:
    def __init__(self, page: IncidentPage | None = None, error=None) -> None:
        self.page = page
        self.error = error
        self.query: IncidentQuery | None = None
        self.calls = 0

    async def read_incident_timeline(self, query: IncidentQuery) -> IncidentPage:
        self.query = query
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.page or _page(query)


class _IncidentEvidenceReader:
    def __init__(self, evidence: IncidentEvidence | None = None, error=None) -> None:
        self.evidence = evidence
        self.error = error
        self.query: IncidentDetailQuery | None = None
        self.calls = 0

    async def read_incident_evidence(
        self, query: IncidentDetailQuery
    ) -> IncidentEvidence:
        self.query = query
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.evidence or _evidence(query)


class _UnusedAccountDirectoryReader:
    async def list_accounts(self, query):
        raise AssertionError("incident timeline must not access account data")

    async def read_account(self, account_id: str):
        raise AssertionError("incident timeline must not access account data")


def _query(
    *,
    app_id: str | None = None,
    instance_id: str | None = None,
    scope: ObservationScope | None = None,
    severity: IncidentSeverity | None = None,
    category: IncidentCategory | None = None,
    cursor: str | None = None,
) -> IncidentQuery:
    resolved_scope = scope or (
        ObservationScope.PROCESS
        if instance_id is not None
        else ObservationScope.APPLICATION
        if app_id is not None
        else ObservationScope.FLEET
    )
    return IncidentQuery(
        context=ObservationContext(
            environment_id="prod",
            app_id=app_id,
            instance_id=instance_id,
            resource=None,
            scope=resolved_scope,
            window=ObservationWindow(_FROM, _TO),
        ),
        severity=severity,
        category=category,
        cursor=cursor,
        page_size=20,
    )


def _event(
    event_id: str,
    *,
    app_id: str = "checkout",
    instance_id: str | None = "checkout-1",
    occurred_at: datetime = datetime(2026, 10, 9, 0, 59, tzinfo=UTC),
    severity: IncidentSeverity = IncidentSeverity.WARNING,
    caption: IncidentFact | None = None,
    category: IncidentCategory = IncidentCategory.RESOURCE,
    publication_id: str | None = None,
) -> ObservedIncident:
    fact = caption or IncidentFact(
        IncidentFactCode.RESOURCE_PRESSURE,
        metric="cpu_ratio",
        value=0.91,
        threshold=0.85,
    )
    return ObservedIncident(
        id=event_id,
        environment_id="prod",
        app_id=app_id,
        instance_id=instance_id,
        process_epoch="epoch-1" if instance_id is not None else None,
        occurred_at=occurred_at,
        received_at=datetime(2026, 10, 9, 1, 0, tzinfo=UTC),
        severity=severity,
        category=category,
        source_event_id=f"source-{event_id}",
        publication_id=publication_id,
        caption=fact,
    )


def _detail_query(
    event_id: str = "event-b",
    *,
    app_id: str | None = None,
    category: IncidentCategory | None = None,
) -> IncidentDetailQuery:
    return IncidentDetailQuery(_query(app_id=app_id).context, event_id, None, category)


def _evidence(query: IncidentDetailQuery) -> IncidentEvidence:
    is_rule = query.event_id == "event-rule"
    event = (
        _event(
            query.event_id,
            app_id="billing",
            instance_id=None,
            occurred_at=datetime(2026, 10, 9, 0, 58, tzinfo=UTC),
            severity=IncidentSeverity.INFO,
            category=IncidentCategory.RULE_PUBLISHED,
            publication_id="publication-3",
            caption=IncidentFact(
                IncidentFactCode.RULE_PUBLISHED, version_id="rules-v3"
            ),
        )
        if is_rule
        else _event(query.event_id)
    )
    related_rule = (
        RelatedRuleIdentity(
            environment_id="prod",
            app_id="billing",
            binding_id="binding-1",
            version_id="rules-v3",
            publication_id="publication-3",
        )
        if is_rule
        else None
    )
    fact_at = datetime(2026, 10, 9, 0, 30, tzinfo=UTC)
    return IncidentEvidence(
        query=query,
        as_of=_AS_OF,
        event=event,
        facts=(
            IncidentEvidenceFact(
                "fact-1",
                "collector-1",
                fact_at,
                IncidentFact(
                    IncidentFactCode.RESPONSE_TIME,
                    value_ms=190,
                    threshold_ms=150,
                ),
            ),
        ),
        completeness=IncidentEvidenceCompleteness.PARTIAL,
        suggested_views=(
            (IncidentSuggestedView.METRICS, IncidentSuggestedView.RULES)
            if is_rule
            else (IncidentSuggestedView.INSTANCE, IncidentSuggestedView.METRICS)
        ),
        related_rule=related_rule,
    )


def _page(query: IncidentQuery | None = None) -> IncidentPage:
    selected = query or _query()
    events = (
        _event("event-b"),
        _event("event-a"),
        _event(
            "event-rule",
            app_id="billing",
            instance_id=None,
            occurred_at=datetime(2026, 10, 9, 0, 58, tzinfo=UTC),
            severity=IncidentSeverity.INFO,
            category=IncidentCategory.RULE_PUBLISHED,
            caption=IncidentFact(
                IncidentFactCode.RULE_PUBLISHED, version_id="rules-v3"
            ),
        ),
    )
    matches = tuple(
        event
        for event in events
        if event.environment_id == selected.context.environment_id
        and (selected.context.app_id is None or event.app_id == selected.context.app_id)
        and (
            selected.context.instance_id is None
            or event.instance_id == selected.context.instance_id
        )
        and (selected.severity is None or event.severity is selected.severity)
        and (selected.category is None or event.category is selected.category)
    )
    scope_events = tuple(
        event
        for event in events
        if event.environment_id == selected.context.environment_id
        and (selected.context.app_id is None or event.app_id == selected.context.app_id)
        and (
            selected.context.instance_id is None
            or event.instance_id == selected.context.instance_id
        )
    )
    return IncidentPage(
        query=selected,
        as_of=_AS_OF,
        statistics=IncidentStatistics(
            total=len(scope_events),
            critical=sum(
                event.severity is IncidentSeverity.CRITICAL for event in scope_events
            ),
            warning=sum(
                event.severity is IncidentSeverity.WARNING for event in scope_events
            ),
            info=sum(event.severity is IncidentSeverity.INFO for event in scope_events),
            rule_changes=sum(
                event.category
                in (IncidentCategory.RULE_PUBLISHED, IncidentCategory.RULE_EFFECTIVE)
                for event in scope_events
            ),
            affected_applications=len({event.app_id for event in scope_events}),
        ),
        items=matches,
        filtered_total=len(matches),
        next_cursor="next-page" if matches and selected.cursor is None else None,
    )


def _app(
    role: str | None,
    *,
    reader=None,
    evidence_reader=None,
    session_reader=None,
):
    return build_app(
        bootstrap_initialization_reader=_Initialized(),
        setup_window_reader=_OpenSetupWindow(),
        bootstrap_operator_verifier=_OperatorVerifier(),
        current_session_reader=session_reader or _SessionReader(role),
        current_session_revoker=UnusedSessionRevoker(),
        account_directory_reader=_UnusedAccountDirectoryReader(),
        allowed_browser_origins=frozenset({"https://console.test"}),
        incident_timeline_reader=reader,
        incident_evidence_reader=evidence_reader,
    )


def _params(**overrides: str) -> dict[str, str]:
    values = {
        "environmentId": "prod",
        "scope": "fleet",
        "from": "2026-10-09T00:45:00.000Z",
        "to": "2026-10-09T01:00:00.000Z",
        "pageSize": "20",
    }
    values.update(overrides)
    return values


def _evidence_params(**overrides: str) -> dict[str, str]:
    values = _params()
    values.pop("pageSize")
    values.update(overrides)
    return values


class IncidentTimelineApiTests(unittest.IsolatedAsyncioTestCase):
    def test_incident_fact_rejects_python_integer_outside_json_finite_range(
        self,
    ) -> None:
        with self.assertRaisesRegex(ValueError, "resource pressure fact is invalid"):
            IncidentFact(
                IncidentFactCode.RESOURCE_PRESSURE,
                metric="cpu_ratio",
                value=10**1000,
                threshold=0.9,
            )

    def test_cursor_limit_matches_javascript_utf16_length(self) -> None:
        _query(cursor="😀" * 256)

        with self.assertRaisesRegex(ValueError, "incident cursor is invalid"):
            _query(cursor="😀" * 257)

    def test_cursor_blank_characters_match_console_wire_policy(self) -> None:
        for blank in ("\x1c", "\x85", "\ufeff", "\u3000"):
            with (
                self.subTest(blank=hex(ord(blank))),
                self.assertRaisesRegex(ValueError, "incident cursor is invalid"),
            ):
                _query(cursor=blank)

        with self.assertRaisesRegex(ValueError, "incident cursor is invalid"):
            _query(cursor="\ud800")

        _query(cursor="opaque\ufefftoken")

    async def test_admin_and_view_read_exact_timeline_and_safe_wire_facts(self) -> None:
        for role in ("admin", "view"):
            with self.subTest(role=role):
                reader = _IncidentReader()
                async with AsyncClient(
                    transport=ASGITransport(app=_app(role, reader=reader)),
                    base_url="http://console.test",
                    cookies={"sentinel_session": _OPAQUE_SESSION},
                ) as client:
                    response = await client.get(
                        "/api/v1/incidents",
                        params=_params(severity="warning", category="resource"),
                        headers=_REQUEST_HEADERS,
                    )

                self.assertEqual(response.status_code, 200)
                assert_openapi_response("readIncidentTimeline", response)
                self.assertEqual(
                    response.headers["x-request-id"], _REQUEST_HEADERS["x-request-id"]
                )
                self.assertEqual(response.headers["cache-control"], "no-store")
                self.assertEqual(reader.calls, 1)
                self.assertEqual(
                    reader.query,
                    _query(
                        severity=IncidentSeverity.WARNING,
                        category=IncidentCategory.RESOURCE,
                    ),
                )
                body = response.json()
                self.assertEqual(body["query"]["severity"], "warning")
                self.assertEqual(body["statistics"]["total"], 3)
                self.assertEqual(
                    [item["id"] for item in body["items"]], ["event-b", "event-a"]
                )
                self.assertEqual(
                    body["items"][0]["caption"],
                    {
                        "code": "resource_pressure",
                        "metric": "cpu_ratio",
                        "value": 0.91,
                        "threshold": 0.85,
                    },
                )
                self.assertNotIn("message", body["items"][0]["caption"])

    async def test_process_scope_and_opaque_cursor_are_forwarded_exactly(self) -> None:
        cursor = "cursor-" + "x" * 300
        query = _query(app_id="checkout", instance_id="checkout-1", cursor=cursor)
        reader = _IncidentReader(_page(query))
        async with AsyncClient(
            transport=ASGITransport(app=_app("view", reader=reader)),
            base_url="http://console.test",
            cookies={"sentinel_session": _OPAQUE_SESSION},
        ) as client:
            response = await client.get(
                "/api/v1/incidents",
                params=_params(
                    appId="checkout",
                    instanceId="checkout-1",
                    scope="process",
                    cursor=cursor,
                ),
                headers=_REQUEST_HEADERS,
            )
        self.assertEqual(response.status_code, 200)
        assert_openapi_response("readIncidentTimeline", response)
        self.assertEqual(reader.query, query)
        self.assertEqual(response.json()["query"]["context"]["scope"], "process")
        self.assertEqual(response.json()["query"]["cursor"], cursor)

    async def test_authority_failures_do_not_leak_details(self) -> None:
        reader = _IncidentReader()
        async with AsyncClient(
            transport=ASGITransport(app=_app(None, reader=reader)),
            base_url="http://console.test",
        ) as client:
            response = await client.get(
                "/api/v1/incidents", params=_params(), headers=_REQUEST_HEADERS
            )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(reader.calls, 0)

        cases = (
            (_IncidentReader(error=IncidentTimelineTargetNotFound()), 404, "not_found"),
            (
                _IncidentReader(error=IncidentTimelineRateLimited(850)),
                429,
                "rate_limited",
            ),
            (
                _IncidentReader(error=IncidentTimelineAuthorityUnavailable("private")),
                503,
                "service_unavailable",
            ),
            (
                _IncidentReader(page=_page(_query(app_id="other"))),
                503,
                "service_unavailable",
            ),
            (None, 503, "service_unavailable"),
        )
        for authority, status, code in cases:
            with self.subTest(status=status, code=code):
                async with AsyncClient(
                    transport=ASGITransport(app=_app("admin", reader=authority)),
                    base_url="http://console.test",
                    cookies={"sentinel_session": _OPAQUE_SESSION},
                ) as client:
                    response = await client.get(
                        "/api/v1/incidents", params=_params(), headers=_REQUEST_HEADERS
                    )
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json()["error"]["code"], code)
                if status == 429:
                    self.assertEqual(response.json()["error"]["retryAfterMs"], 850)
                else:
                    self.assertNotIn("retryAfterMs", response.json()["error"])
                self.assertNotIn("private", response.text)

    async def test_session_authority_failure_is_unavailable(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(
                app=_app("unavailable", session_reader=_SessionReader("unavailable"))
            ),
            base_url="http://console.test",
            cookies={"sentinel_session": _OPAQUE_SESSION},
        ) as client:
            response = await client.get(
                "/api/v1/incidents", params=_params(), headers=_REQUEST_HEADERS
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "service_unavailable")

    async def test_invalid_queries_are_rejected_before_authority(self) -> None:
        reader = _IncidentReader()
        cases = (
            ({"scope": "fleet", "appId": "checkout"},),
            ({"scope": "application"},),
            ({"scope": "process", "appId": "checkout"},),
            (
                {
                    "scope": "application",
                    "appId": "checkout",
                    "instanceId": "checkout-1",
                },
            ),
            ({"scope": "host"},),
            ({"scope": "container"},),
            ({"scope": "fleet", "resource": "cpu"},),
            ({"scope": "fleet", "unknown": "x"},),
            ({"scope": "fleet", "severity": "fatal"},),
            ({"scope": "fleet", "pageSize": "101"},),
            ({"scope": "fleet", "cursor": "x" * 513},),
            ({"scope": "fleet", "cursor": "😀" * 257},),
            ({"scope": "fleet", "cursor": "\x1c"},),
            ({"scope": "fleet", "cursor": "\x85"},),
            ({"scope": "fleet", "cursor": "\ufeff"},),
            ({"scope": "fleet", "from": "2026-10-09T00:00:00Z"},),
        )
        async with AsyncClient(
            transport=ASGITransport(app=_app("admin", reader=reader)),
            base_url="http://console.test",
            cookies={"sentinel_session": _OPAQUE_SESSION},
        ) as client:
            for (overrides,) in cases:
                with self.subTest(overrides=tuple(overrides)):
                    response = await client.get(
                        "/api/v1/incidents",
                        params=_params(**overrides),
                        headers=_REQUEST_HEADERS,
                    )
                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(
                        response.json()["error"]["code"], "invalid_request"
                    )
            duplicate = await client.get(
                "/api/v1/incidents?environmentId=prod&environmentId=other&scope=fleet"
                "&from=2026-10-09T00%3A45%3A00.000Z"
                "&to=2026-10-09T01%3A00%3A00.000Z&pageSize=20",
                headers=_REQUEST_HEADERS,
            )
        self.assertEqual(duplicate.status_code, 400)
        self.assertEqual(reader.calls, 0)

    async def test_evidence_returns_exact_event_and_authority_rule_link(self) -> None:
        query = _detail_query(
            "event-rule",
            app_id="billing",
            category=IncidentCategory.RULE_PUBLISHED,
        )
        reader = _IncidentEvidenceReader(_evidence(query))
        async with AsyncClient(
            transport=ASGITransport(app=_app("view", evidence_reader=reader)),
            base_url="http://console.test",
            cookies={"sentinel_session": _OPAQUE_SESSION},
        ) as client:
            response = await client.get(
                "/api/v1/incidents/event-rule/evidence",
                params=_evidence_params(
                    appId="billing",
                    scope="application",
                    category="rulePublished",
                ),
                headers=_REQUEST_HEADERS,
            )
        self.assertEqual(response.status_code, 200)
        assert_openapi_response("readIncidentEvidence", response)
        self.assertEqual(reader.query, query)
        body = response.json()
        self.assertEqual(body["event"]["id"], "event-rule")
        self.assertEqual(body["completeness"], "partial")
        self.assertEqual(body["relatedRule"]["publicationId"], "publication-3")
        self.assertEqual(body["suggestedViews"], ["metrics", "rules"])
        self.assertEqual(body["facts"][0]["fact"]["code"], "response_time")
        self.assertEqual(body["facts"][0]["at"], "2026-10-09T00:30:00.000Z")

    async def test_non_rule_evidence_never_infers_a_related_rule(self) -> None:
        query = _detail_query()
        reader = _IncidentEvidenceReader(_evidence(query))
        async with AsyncClient(
            transport=ASGITransport(app=_app("admin", evidence_reader=reader)),
            base_url="http://console.test",
            cookies={"sentinel_session": _OPAQUE_SESSION},
        ) as client:
            response = await client.get(
                "/api/v1/incidents/event-b/evidence",
                params=_evidence_params(),
                headers=_REQUEST_HEADERS,
            )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["relatedRule"])
        self.assertNotIn("rules", response.json()["suggestedViews"])

    async def test_evidence_access_and_filtered_event_are_non_disclosing(self) -> None:
        reader = _IncidentEvidenceReader()
        async with AsyncClient(
            transport=ASGITransport(app=_app(None, evidence_reader=reader)),
            base_url="http://console.test",
        ) as client:
            anonymous = await client.get(
                "/api/v1/incidents/event-b/evidence",
                params=_evidence_params(),
                headers=_REQUEST_HEADERS,
            )
        self.assertEqual(anonymous.status_code, 401)
        self.assertEqual(reader.calls, 0)

        cases = (
            (IncidentEvidenceNotFound(), "not_found"),
            (
                IncidentEvidenceRateLimited(500),
                "rate_limited",
            ),
        )
        for error, code in cases:
            with self.subTest(code=code):
                current = _IncidentEvidenceReader(error=error)
                async with AsyncClient(
                    transport=ASGITransport(app=_app("view", evidence_reader=current)),
                    base_url="http://console.test",
                    cookies={"sentinel_session": _OPAQUE_SESSION},
                ) as client:
                    response = await client.get(
                        "/api/v1/incidents/event-b/evidence",
                        params=_evidence_params(),
                        headers=_REQUEST_HEADERS,
                    )
                expected_status = 404 if code == "not_found" else 429
                self.assertEqual(response.status_code, expected_status)
                self.assertEqual(response.json()["error"]["code"], code)
                if expected_status == 429:
                    self.assertEqual(response.json()["error"]["retryAfterMs"], 500)
                else:
                    self.assertNotIn("retryAfterMs", response.json()["error"])

    async def test_evidence_rejects_query_errors_and_mismatched_authority(self) -> None:
        reader = _IncidentEvidenceReader(_evidence(_detail_query("event-b")))
        async with AsyncClient(
            transport=ASGITransport(app=_app("admin", evidence_reader=reader)),
            base_url="http://console.test",
            cookies={"sentinel_session": _OPAQUE_SESSION},
        ) as client:
            invalid = await client.get(
                "/api/v1/incidents/event-b/evidence",
                params=_evidence_params(scope="fleet", unknown="x"),
                headers=_REQUEST_HEADERS,
            )
            unsupported = await client.get(
                "/api/v1/incidents/event-b/evidence",
                params=_evidence_params(scope="fleet", resource="cpu"),
                headers=_REQUEST_HEADERS,
            )
            invalid_scope = await client.get(
                "/api/v1/incidents/event-b/evidence",
                params=_evidence_params(scope="container"),
                headers=_REQUEST_HEADERS,
            )
            inconsistent_scope = await client.get(
                "/api/v1/incidents/event-b/evidence",
                params=_evidence_params(
                    scope="application", appId="checkout", instanceId="checkout-1"
                ),
                headers=_REQUEST_HEADERS,
            )
            mismatch = await client.get(
                "/api/v1/incidents/another-event/evidence",
                params=_evidence_params(),
                headers=_REQUEST_HEADERS,
            )
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(unsupported.status_code, 400)
        self.assertEqual(invalid_scope.status_code, 400)
        self.assertEqual(inconsistent_scope.status_code, 400)
        self.assertEqual(mismatch.status_code, 503)
        self.assertEqual(reader.calls, 1)

    async def test_unavailable_evidence_authority_fails_closed(self) -> None:
        reader = _IncidentEvidenceReader(
            error=IncidentEvidenceAuthorityUnavailable("private evidence detail")
        )
        async with AsyncClient(
            transport=ASGITransport(app=_app("admin", evidence_reader=reader)),
            base_url="http://console.test",
            cookies={"sentinel_session": _OPAQUE_SESSION},
        ) as client:
            response = await client.get(
                "/api/v1/incidents/event-b/evidence",
                params=_evidence_params(),
                headers=_REQUEST_HEADERS,
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "service_unavailable")
        self.assertNotIn("private evidence detail", response.text)

        async with AsyncClient(
            transport=ASGITransport(app=_app("admin")),
            base_url="http://console.test",
            cookies={"sentinel_session": _OPAQUE_SESSION},
        ) as client:
            missing_reader = await client.get(
                "/api/v1/incidents/event-b/evidence",
                params=_evidence_params(),
                headers=_REQUEST_HEADERS,
            )
        self.assertEqual(missing_reader.status_code, 503)
        self.assertEqual(missing_reader.json()["error"]["code"], "service_unavailable")


if __name__ == "__main__":
    unittest.main()
