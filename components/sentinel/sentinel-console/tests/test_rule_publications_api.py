"""Publication-stage HTTP/domain contracts against isolated authorities."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import unittest

from httpx import ASGITransport, AsyncClient

from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.application.errors import SessionAuthorityUnavailable
from atlas_richie.sentinel_console.application.rule_publication_ports import (
    RulePublicationAuthorityUnavailable,
    RulePublicationNotFound,
    RulePublicationRateLimited,
)
from atlas_richie.sentinel_console.domain.rule_publications import (
    PublicationPhase,
    PublicationReason,
    PublicationReceiptState,
    PublicationStage,
    RulePublication,
    RulePublicationCollection,
    RulePublicationReceipt,
    RulePublicationReceiptPage,
)
from atlas_richie.sentinel_console.domain.rule_publication_targets import (
    NacosRulePublicationTarget,
    VersionedRulePublicationTarget,
)
from atlas_richie.sentinel_console.domain.session import ActiveAccountSession
from session_test_doubles import UnusedSessionRevoker

_HEADERS = {"x-request-id": "rule-publications-read-1"}
_COOKIE = "synthetic-session-token-for-rule-publications-0001"
_AS_OF = datetime(2026, 10, 9, 1, 0, 1, 123000, tzinfo=UTC)


class _Initialized:
    async def is_initialized(self) -> bool:
        return True


class _ClosedSetupWindow:
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
            raise SessionAuthorityUnavailable("private session detail")
        if self.role is None:
            return None
        return ActiveAccountSession("account-1", "operator", self.role, "epoch-1")


class _AccountDirectoryReader:
    async def list_accounts(self, query):
        raise AssertionError("publication reads must not query accounts")

    async def read_account(self, account_id: str):
        raise AssertionError("publication reads must not query accounts")


def _phase(
    state: PublicationStage = PublicationStage.SUCCEEDED,
    *,
    reason: PublicationReason | None = None,
    observed_at: datetime | None = _AS_OF,
) -> PublicationPhase:
    return PublicationPhase(state, observed_at, reason)


def _publication(
    *,
    publication_id: str = "publication-1",
    binding_id: str = "binding-1",
    validation: PublicationPhase | None = None,
    configuration_write: PublicationPhase | None = None,
    read_back: PublicationPhase | None = None,
) -> RulePublication:
    return RulePublication(
        id=publication_id,
        binding_id=binding_id,
        target_version_id="version-2",
        target_checksum="sha256-version-2",
        base_version_id="version-1",
        created_at=_AS_OF,
        validation=validation or _phase(),
        configuration_write=configuration_write or _phase(),
        read_back=read_back or _phase(),
    )


def _collection(
    *, binding_id: str = "binding-1", items: tuple[RulePublication, ...] | None = None
) -> RulePublicationCollection:
    publications = (_publication(binding_id=binding_id),) if items is None else items
    return RulePublicationCollection(binding_id, _AS_OF, publications)


def _receipt(
    *,
    instance_id: str = "instance-1",
    state: PublicationReceiptState = PublicationReceiptState.APPLIED,
    process_epoch: str | None = "process-1",
    loaded_process_epoch: str | None = "process-1",
    target_version_id: str = "version-2",
    loaded_version_id: str | None = "version-2",
    loaded_checksum: str | None = "sha256-version-2",
    applied_at: datetime | None = _AS_OF,
    last_report_at: datetime | None = _AS_OF,
) -> RulePublicationReceipt:
    return RulePublicationReceipt(
        instance_id,
        process_epoch,
        loaded_process_epoch,
        target_version_id,
        loaded_version_id,
        loaded_checksum,
        applied_at,
        last_report_at,
        state,
    )


def _receipt_page(
    *,
    publication_id: str = "publication-1",
    binding_id: str = "binding-1",
    page: int = 1,
    page_size: int = 10,
    total: int = 1,
    expected: int | None = 1,
    inventory_source: str | None = "inventory-1",
    applied: int = 1,
    pending: int = 0,
    failed: int = 0,
    unknown: int = 0,
    restart_required: int = 0,
    items: tuple[RulePublicationReceipt, ...] | None = None,
) -> RulePublicationReceiptPage:
    receipt_items = (_receipt(),) if items is None else items
    return RulePublicationReceiptPage(
        publication_id,
        binding_id,
        page,
        page_size,
        _AS_OF,
        total,
        expected,
        inventory_source,
        applied,
        pending,
        failed,
        unknown,
        restart_required,
        receipt_items,
    )


class _PublicationReader:
    def __init__(
        self,
        *,
        error=None,
        collection: RulePublicationCollection | None = None,
    ):
        self.error = error
        self.collection = collection
        self.binding_id: str | None = None
        self.calls = 0

    async def read_rule_publications(
        self, binding_id: str
    ) -> RulePublicationCollection:
        self.binding_id = binding_id
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.collection or _collection(binding_id=binding_id)


class _PublicationDetailReader:
    def __init__(self, *, error=None, publication: RulePublication | None = None):
        self.error = error
        self.publication = publication
        self.binding_id: str | None = None
        self.publication_id: str | None = None
        self.calls = 0

    async def read_rule_publication(
        self, binding_id: str, publication_id: str
    ) -> RulePublication:
        self.binding_id = binding_id
        self.publication_id = publication_id
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.publication or _publication(
            publication_id=publication_id, binding_id=binding_id
        )


class _PublicationReceiptReader:
    def __init__(
        self,
        *,
        error=None,
        receipt_page: RulePublicationReceiptPage | None = None,
    ):
        self.error = error
        self.receipt_page = receipt_page
        self.arguments: tuple[str, str, int, int] | None = None
        self.calls = 0

    async def read_rule_publication_receipts(
        self, binding_id: str, publication_id: str, page: int, page_size: int
    ) -> RulePublicationReceiptPage:
        self.arguments = (binding_id, publication_id, page, page_size)
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.receipt_page or _receipt_page(
            binding_id=binding_id,
            publication_id=publication_id,
            page=page,
            page_size=page_size,
        )


class _PublicationTargetReader:
    def __init__(self, target=None):
        self.target = target
        self.binding_id = None

    async def read_rule_publication_target(self, binding_id):
        self.binding_id = binding_id
        return self.target


def _app(
    role: str | None,
    *,
    reader=None,
    detail_reader=None,
    receipt_reader=None,
    target_reader=None,
    session_reader=None,
):
    return build_app(
        bootstrap_initialization_reader=_Initialized(),
        setup_window_reader=_ClosedSetupWindow(),
        bootstrap_operator_verifier=_OperatorVerifier(),
        current_session_reader=session_reader or _SessionReader(role),
        current_session_revoker=UnusedSessionRevoker(),
        account_directory_reader=_AccountDirectoryReader(),
        allowed_browser_origins=frozenset({"https://console.test"}),
        rule_publication_reader=reader,
        rule_publication_detail_reader=detail_reader,
        rule_publication_receipt_reader=receipt_reader,
        rule_publication_target_reader=target_reader,
    )


class RulePublicationApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_target_read_projects_versioned_provider_fields_without_credentials(self):
        target = VersionedRulePublicationTarget(
            revision="target-rev-2",
            source_revision="source-rev-5",
            target=NacosRulePublicationTarget(
                binding_id="binding-1",
                source_id="source-1",
                namespace="prod",
                group="SENTINEL_GROUP",
                data_id="orders-flow-rules",
            ),
        )
        reader = _PublicationTargetReader(target)
        app = _app("view", target_reader=reader)
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="https://console.test",
            cookies={"sentinel_session": _COOKIE},
        ) as client:
            response = await client.get(
                "/api/v1/rulesets/binding-1/publication-target", headers=_HEADERS
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(reader.binding_id, "binding-1")
        self.assertEqual(response.json()["targetRevision"], "target-rev-2")
        self.assertEqual(response.json()["sourceRevision"], "source-rev-5")
        self.assertEqual(response.json()["target"]["dataId"], "orders-flow-rules")
        self.assertNotIn("credential", response.text)
        self.assertNotIn("token", response.text.lower())

    async def test_target_read_requires_session_and_returns_explicit_unconfigured_value(self):
        reader = _PublicationTargetReader()
        app = _app("view", target_reader=reader)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://console.test"
        ) as client:
            anonymous = await client.get(
                "/api/v1/rulesets/binding-1/publication-target", headers=_HEADERS
            )
        self.assertEqual(anonymous.status_code, 401)
        self.assertIsNone(reader.binding_id)
        app = _app("admin", target_reader=reader)
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="https://console.test",
            cookies={"sentinel_session": _COOKIE},
        ) as client:
            response = await client.get(
                "/api/v1/rulesets/binding-1/publication-target", headers=_HEADERS
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"bindingId": "binding-1", "target": None})

    async def _get(
        self,
        role,
        *,
        reader=None,
        session_reader=None,
        binding_id="binding-1",
    ):
        app = _app(role, reader=reader, session_reader=session_reader)
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="https://console.test",
            cookies={"sentinel_session": _COOKIE},
        ) as client:
            return await client.get(
                f"/api/v1/rulesets/{binding_id}/publications", headers=_HEADERS
            )

    async def _get_detail(
        self,
        role,
        *,
        reader=None,
        session_reader=None,
        binding_id="binding-1",
        publication_id="publication-1",
    ):
        app = _app(role, detail_reader=reader, session_reader=session_reader)
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="https://console.test",
            cookies={"sentinel_session": _COOKIE},
        ) as client:
            return await client.get(
                f"/api/v1/rulesets/{binding_id}/publications/{publication_id}",
                headers=_HEADERS,
            )

    async def _get_receipts(
        self,
        role,
        *,
        reader=None,
        detail_reader=None,
        session_reader=None,
        binding_id="binding-1",
        publication_id="publication-1",
        query="page=1&pageSize=10",
    ):
        app = _app(
            role,
            detail_reader=detail_reader or _PublicationDetailReader(),
            receipt_reader=reader,
            session_reader=session_reader,
        )
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="https://console.test",
            cookies={"sentinel_session": _COOKIE},
        ) as client:
            return await client.get(
                (
                    f"/api/v1/rulesets/{binding_id}/publications/"
                    f"{publication_id}/receipts?{query}"
                ),
                headers=_HEADERS,
            )

    async def test_session_reads_independent_publication_phases(self):
        publication = _publication(
            configuration_write=_phase(
                PublicationStage.UNKNOWN, reason=PublicationReason.UNKNOWN
            ),
            read_back=_phase(PublicationStage.AWAITING, observed_at=None),
        )
        reader = _PublicationReader(collection=_collection(items=(publication,)))
        response = await self._get("view", reader=reader)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(reader.binding_id, "binding-1")
        body = response.json()
        self.assertEqual(body["asOf"], "2026-10-09T01:00:01.123Z")
        item = body["items"][0]
        self.assertEqual(item["validation"]["state"], "succeeded")
        self.assertEqual(item["configurationWrite"]["state"], "unknown")
        self.assertEqual(item["configurationWrite"]["reason"], "unknown")
        self.assertEqual(
            item["readBack"],
            {"state": "awaiting", "observedAt": None, "reason": None},
        )
        self.assertNotIn("credential", response.text)
        self.assertNotIn("records", response.json()["items"][0])

    async def test_anonymous_invalid_paths_and_session_failure_skip_authority(self):
        anonymous_reader = _PublicationReader()
        anonymous = await self._get(None, reader=anonymous_reader)
        self.assertEqual(anonymous.status_code, 401)
        self.assertEqual(anonymous_reader.calls, 0)
        invalid_reader = _PublicationReader()
        invalid = await self._get("admin", reader=invalid_reader, binding_id=" ")
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(invalid_reader.calls, 0)
        unavailable_reader = _PublicationReader()
        unavailable = await self._get(
            "admin",
            reader=unavailable_reader,
            session_reader=_SessionReader("unavailable"),
        )
        self.assertEqual(unavailable.status_code, 503)
        self.assertEqual(unavailable_reader.calls, 0)

    async def test_list_maps_missing_and_authority_failures_safely(self):
        missing = await self._get("admin")
        self.assertEqual(missing.status_code, 503)
        cases = (
            (RulePublicationNotFound("private binding"), 404, "not_found"),
            (RulePublicationRateLimited(45), 429, "rate_limited"),
            (
                RulePublicationAuthorityUnavailable("private store detail"),
                503,
                "service_unavailable",
            ),
        )
        for error, status, code in cases:
            with self.subTest(code=code):
                response = await self._get(
                    "admin", reader=_PublicationReader(error=error)
                )
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json()["error"]["code"], code)
                self.assertNotIn("private", response.text)

    async def test_mismatched_collection_fails_closed(self):
        response = await self._get(
            "admin",
            reader=_PublicationReader(collection=_collection(binding_id="other")),
        )
        self.assertEqual(response.status_code, 503)

    async def test_session_reads_exact_publication_detail(self):
        reader = _PublicationDetailReader()
        response = await self._get_detail("admin", reader=reader)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(reader.binding_id, "binding-1")
        self.assertEqual(reader.publication_id, "publication-1")
        self.assertEqual(response.json()["id"], "publication-1")
        self.assertEqual(response.json()["targetVersionId"], "version-2")

    async def test_detail_rejects_anonymous_invalid_and_mismatched_identity(self):
        anonymous_reader = _PublicationDetailReader()
        anonymous = await self._get_detail(None, reader=anonymous_reader)
        self.assertEqual(anonymous.status_code, 401)
        self.assertEqual(anonymous_reader.calls, 0)
        invalid_reader = _PublicationDetailReader()
        invalid = await self._get_detail(
            "view", reader=invalid_reader, publication_id=" "
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(invalid_reader.calls, 0)
        wrong_id = await self._get_detail(
            "view",
            reader=_PublicationDetailReader(
                publication=_publication(publication_id="other")
            ),
        )
        self.assertEqual(wrong_id.status_code, 503)
        wrong_binding = await self._get_detail(
            "view",
            reader=_PublicationDetailReader(
                publication=_publication(binding_id="other")
            ),
        )
        self.assertEqual(wrong_binding.status_code, 503)

    async def test_detail_maps_not_found_and_authority_failures(self):
        missing = await self._get_detail("view")
        self.assertEqual(missing.status_code, 503)
        cases = (
            (RulePublicationNotFound("private"), 404, "not_found"),
            (RulePublicationRateLimited(45), 429, "rate_limited"),
            (
                RulePublicationAuthorityUnavailable("private persistence detail"),
                503,
                "service_unavailable",
            ),
        )
        for error, status, code in cases:
            with self.subTest(code=code):
                response = await self._get_detail(
                    "view", reader=_PublicationDetailReader(error=error)
                )
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json()["error"]["code"], code)
                self.assertNotIn("private", response.text)

    async def test_receipt_page_preserves_counts_and_exact_instance_evidence(self):
        applied = _receipt()
        unknown = _receipt(
            instance_id="instance-2",
            state=PublicationReceiptState.UNKNOWN,
            process_epoch=None,
            loaded_process_epoch=None,
            loaded_version_id=None,
            loaded_checksum=None,
            applied_at=None,
            last_report_at=None,
        )
        reader = _PublicationReceiptReader(
            receipt_page=_receipt_page(
                total=2,
                expected=2,
                applied=1,
                unknown=1,
                items=(applied, unknown),
            )
        )
        response = await self._get_receipts("view", reader=reader)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(reader.arguments, ("binding-1", "publication-1", 1, 10))
        body = response.json()
        self.assertEqual(body["asOf"], "2026-10-09T01:00:01.123Z")
        self.assertEqual(body["expected"], 2)
        self.assertEqual(body["inventorySource"], "inventory-1")
        self.assertEqual(body["applied"] + body["unknown"], body["total"])
        self.assertEqual(body["items"][0]["loadedChecksum"], "sha256-version-2")
        self.assertEqual(body["items"][1]["state"], "unknown")
        self.assertIsNone(body["items"][1]["processEpoch"])

    async def test_receipts_require_auth_valid_unique_query_and_both_readers(self):
        reader = _PublicationReceiptReader()
        anonymous = await self._get_receipts(None, reader=reader)
        self.assertEqual(anonymous.status_code, 401)
        self.assertEqual(reader.calls, 0)
        invalid_queries = (
            "page=1&page=2&pageSize=10",
            "page=1&pageSize=10&pageSize=20",
            "page=1&pageSize=10&resource=orders",
            "page=1&pageSize=0",
            "page=1000001&pageSize=10",
            "page=1&pageSize=101",
        )
        for query in invalid_queries:
            with self.subTest(query=query):
                response = await self._get_receipts(
                    "admin", reader=reader, query=query
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(reader.calls, 0)
        missing = await self._get_receipts("admin")
        self.assertEqual(missing.status_code, 503)

    async def test_receipt_page_rejects_wrong_publication_page_and_target(self):
        cases = (
            (_receipt_page(binding_id="another-binding"), "page=1&pageSize=10"),
            (_receipt_page(publication_id="another-publication"), "page=1&pageSize=10"),
            (_receipt_page(), "page=2&pageSize=10"),
            (
                _receipt_page(
                    items=(
                        _receipt(
                            target_version_id="another-version",
                            loaded_version_id="another-version",
                        ),
                    )
                ),
                "page=1&pageSize=10",
            ),
            (
                _receipt_page(items=(_receipt(loaded_checksum="another-checksum"),)),
                "page=1&pageSize=10",
            ),
        )
        for receipt_page, query in cases:
            with self.subTest(receipt_page=receipt_page, query=query):
                response = await self._get_receipts(
                    "admin",
                    reader=_PublicationReceiptReader(receipt_page=receipt_page),
                    query=query,
                )
                self.assertEqual(response.status_code, 503)

    async def test_receipt_authority_errors_are_finite_and_redacted(self):
        cases = (
            (RulePublicationNotFound("private receipt target"), 404, "not_found"),
            (RulePublicationRateLimited(17), 429, "rate_limited"),
            (
                RulePublicationAuthorityUnavailable("private receipt store"),
                503,
                "service_unavailable",
            ),
        )
        for error, status, code in cases:
            with self.subTest(code=code):
                response = await self._get_receipts(
                    "view", reader=_PublicationReceiptReader(error=error)
                )
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json()["error"]["code"], code)
                self.assertNotIn("private", response.text)


class RulePublicationDomainTests(unittest.TestCase):
    def test_publication_phase_invariants_keep_write_and_readback_separate(self):
        succeeded = _phase()
        with self.assertRaises(ValueError):
            _phase(PublicationStage.SUCCEEDED, observed_at=None)
        with self.assertRaises(ValueError):
            _phase(PublicationStage.FAILED)
        with self.assertRaises(ValueError):
            replace(
                _publication(),
                validation=_phase(
                    PublicationStage.FAILED,
                    reason=PublicationReason.REJECTED,
                ),
                configuration_write=_phase(
                    PublicationStage.RUNNING,
                    observed_at=None,
                ),
            )
        with self.assertRaises(ValueError):
            replace(
                _publication(),
                configuration_write=_phase(
                    PublicationStage.AWAITING,
                    observed_at=None,
                ),
                read_back=_phase(PublicationStage.SUCCEEDED),
            )
        self.assertIsNotNone(succeeded.observed_at)

    def test_collection_rejects_duplicates_foreign_bindings_and_overflow(self):
        publication = _publication()
        with self.assertRaises(ValueError):
            _collection(items=(publication, publication))
        with self.assertRaises(ValueError):
            RulePublicationCollection("binding-1", _AS_OF, (_publication(),) * 1_001)
        with self.assertRaises(ValueError):
            _collection(items=(_publication(binding_id="other"),))

    def test_publication_rejects_inexact_utc_time(self):
        with self.assertRaises(ValueError):
            replace(
                _publication(),
                created_at=datetime(2026, 10, 9, 1, 0, 1, 123456, tzinfo=UTC),
            )

    def test_receipt_population_and_applied_evidence_invariants(self):
        applied = _receipt()
        second_applied = _receipt(instance_id="instance-2")
        with self.assertRaises(ValueError):
            replace(applied, loaded_process_epoch="old-process")
        with self.assertRaises(ValueError):
            replace(applied, loaded_version_id="old-version")
        with self.assertRaises(ValueError):
            _receipt_page(expected=2, inventory_source=None)
        with self.assertRaises(ValueError):
            _receipt_page(total=2, expected=2)
        with self.assertRaises(ValueError):
            _receipt_page(total=2, expected=1, applied=2, items=(applied, second_applied))
        with self.assertRaises(ValueError):
            _receipt_page(total=2, applied=1, pending=0, items=(applied, second_applied))
        with self.assertRaises(ValueError):
            _receipt_page(
                total=2,
                applied=2,
                page_size=1,
                items=(applied, second_applied),
            )
        with self.assertRaises(ValueError):
            _receipt_page(
                total=2,
                applied=1,
                pending=1,
                items=(applied, second_applied),
            )
        with self.assertRaises(ValueError):
            _receipt_page(items=(applied, applied))
        with self.assertRaises(ValueError):
            replace(_receipt_page(), page=2, total=1)


if __name__ == "__main__":
    unittest.main()
