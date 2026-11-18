"""tenant-core：上下文、命名、缓存、路由与身份解析。"""

from __future__ import annotations

import asyncio
import threading

import pytest

from atlas_richie.tenant_core import (
    CachingTenantInfoProvider,
    ContextVarHolder,
    IdentityResolution,
    IsolationMode,
    NoOpTenantInfoProvider,
    TenancyRouter,
    TenantContext,
    TenantError,
    TenantErrorCode,
    TenantIdentityResolver,
    TenantInfo,
    TenantPrincipal,
    TenantStatus,
    propagate,
    validate,
    validate_tenant_id,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_context():
    TenantContext.init(ContextVarHolder())
    TenantContext.clear()
    yield
    TenantContext.clear()


class TestContext:
    def test_unbound_get_is_none(self) -> None:
        assert TenantContext.get() is None
        assert TenantContext.get_tenant_id() is None

    def test_require_unbound_raises(self) -> None:
        with pytest.raises(TenantError) as info:
            TenantContext.require()
        assert info.value.code == TenantErrorCode.TENANT_NOT_BOUND

    def test_run_with_tenant_binds_and_restores(self) -> None:
        principal = TenantPrincipal(tenant_id=7, tenant_name="acme")
        result = TenantContext.run_with_tenant(principal, lambda: TenantContext.require_tenant_id())
        assert result == 7
        assert TenantContext.get() is None, "退出后必须恢复未绑定"

    def test_nested_run_restores_outer(self) -> None:
        outer = TenantPrincipal(tenant_id=1)
        inner = TenantPrincipal(tenant_id=2)

        def task():
            assert TenantContext.get_tenant_id() == 2
            return "ok"

        TenantContext.run_with_tenant(outer, lambda: TenantContext.run_with_tenant(inner, task))
        assert TenantContext.get() is None

    def test_exception_restores_context(self) -> None:
        def boom():
            raise RuntimeError("down")

        with pytest.raises(RuntimeError):
            TenantContext.run_with_tenant(TenantPrincipal(tenant_id=1), boom)
        assert TenantContext.get() is None, "异常时不得泄漏租户上下文"

    def test_get_tenant_name(self) -> None:
        TenantContext.run_with_tenant(
            TenantPrincipal(tenant_id=1, tenant_name="acme"),
            lambda: None,
        )
        # run_with_tenant 退出后已恢复；在任务内取
        name = TenantContext.run_with_tenant(
            TenantPrincipal(tenant_id=1, tenant_name="acme"),
            TenantContext.get_tenant_name,
        )
        assert name == "acme"

    def test_clear(self) -> None:
        holder = ContextVarHolder()
        holder.run_with_tenant(TenantPrincipal(tenant_id=1), lambda: holder.clear())
        assert holder.get() is None

    def test_cross_thread_propagation(self) -> None:
        results: list[int | None] = []

        def job():
            results.append(TenantContext.get_tenant_id())

        TenantContext.run_with_tenant(
            TenantPrincipal(tenant_id=42),
            lambda: threading.Thread(target=propagate(job)).start(),
        )
        # 等线程结束
        import time
        time.sleep(0.05)
        assert results == [42], "propagate 必须把租户带到新线程"

    def test_without_propagation_thread_does_not_inherit(self) -> None:
        results: list[int | None] = []

        def job():
            results.append(TenantContext.get_tenant_id())

        thread = threading.Thread(target=job)
        TenantContext.run_with_tenant(TenantPrincipal(tenant_id=42), lambda: thread.start())
        thread.join(5)
        assert results == [None], "裸线程不继承 contextvars（需显式 propagate）"

    def test_asyncio_propagation(self) -> None:
        async def scenario():
            async def child():
                return TenantContext.get_tenant_id()

            return await asyncio.gather(child(), child())

        ids = TenantContext.run_with_tenant(
            TenantPrincipal(tenant_id=9), lambda: asyncio.run(scenario())
        )
        assert ids == [9, 9], "contextvars 天然跨 asyncio 任务传播"


class TestNaming:
    @pytest.mark.parametrize("name", ["tenant_1", "_private", "A", "a1_b2", "x" * 128])
    def test_valid(self, name) -> None:
        assert validate(name, "schema") == name

    @pytest.mark.parametrize("name", [None, "", "1abc", "a-b", "a b", "a.b", "a;b", "租户", "x" * 129])
    def test_invalid(self, name) -> None:
        with pytest.raises(TenantError) as info:
            validate(name, "schema")
        assert info.value.code == TenantErrorCode.TENANT_INVALID_NAMING

    def test_sql_injection_rejected(self) -> None:
        with pytest.raises(TenantError):
            validate("x; DROP TABLE users", "tableSuffix")


class TestProvider:
    def test_noop_always_absent(self) -> None:
        provider = NoOpTenantInfoProvider()
        assert provider.get_tenant_info(1) is None
        assert provider.exists(1) is False

    def test_caching_hits_delegate_once(self) -> None:
        calls: list[int] = []

        class _Delegate:
            def get_tenant_info(self, tenant_id):
                calls.append(tenant_id)
                return TenantInfo(tenant_id=tenant_id)

            def exists(self, tenant_id):
                return True

        provider = CachingTenantInfoProvider(_Delegate(), ttl_seconds=60, max_size=10)
        provider.get_tenant_info(1)
        provider.get_tenant_info(1)
        assert calls == [1]

    def test_ttl_expiry_refetches(self) -> None:
        clock = [0.0]
        calls: list[int] = []

        class _Delegate:
            def get_tenant_info(self, tenant_id):
                calls.append(tenant_id)
                return TenantInfo(tenant_id=tenant_id)

            def exists(self, tenant_id):
                return True

        provider = CachingTenantInfoProvider(_Delegate(), 10, 10, clock=lambda: clock[0])
        provider.get_tenant_info(1)
        clock[0] = 11.0
        provider.get_tenant_info(1)
        assert calls == [1, 1]

    def test_ttl_zero_disables_caching(self) -> None:
        calls: list[int] = []

        class _Delegate:
            def get_tenant_info(self, tenant_id):
                calls.append(tenant_id)
                return TenantInfo(tenant_id=tenant_id)

            def exists(self, tenant_id):
                return True

        provider = CachingTenantInfoProvider(_Delegate(), 0, 10)
        assert provider.caching_enabled is False
        provider.get_tenant_info(1)
        provider.get_tenant_info(1)
        assert calls == [1, 1]

    def test_max_size_evicts_oldest(self) -> None:
        clock = [0.0]

        class _Delegate:
            def get_tenant_info(self, tenant_id):
                return TenantInfo(tenant_id=tenant_id)

            def exists(self, tenant_id):
                return True

        provider = CachingTenantInfoProvider(_Delegate(), 60, 2, clock=lambda: clock[0])
        provider.get_tenant_info(1)
        clock[0] = 1.0
        provider.get_tenant_info(2)
        clock[0] = 2.0
        provider.get_tenant_info(3)
        assert provider.size() == 2, "超出容量驱逐最旧条目"

    def test_invalidate_and_clear(self) -> None:
        class _Delegate:
            def get_tenant_info(self, tenant_id):
                return TenantInfo(tenant_id=tenant_id)

            def exists(self, tenant_id):
                return True

        provider = CachingTenantInfoProvider(_Delegate(), 60, 10)
        provider.get_tenant_info(1)
        provider.invalidate(1)
        assert provider.size() == 0
        provider.get_tenant_info(2)
        provider.clear()
        assert provider.size() == 0

    def test_none_delegate_rejected(self) -> None:
        with pytest.raises(ValueError):
            CachingTenantInfoProvider(None, 60, 10)

    def test_invalid_max_size_rejected(self) -> None:
        with pytest.raises(ValueError):
            CachingTenantInfoProvider(NoOpTenantInfoProvider(), 60, 0)


class TestRouting:
    def test_column_mode(self) -> None:
        routing = TenancyRouter().resolve(TenantInfo(tenant_id=1, mode=IsolationMode.COLUMN))
        assert routing.column_filter is True
        assert routing.table_suffix is None

    def test_table_mode(self) -> None:
        routing = TenancyRouter().resolve(
            TenantInfo(tenant_id=1, mode=IsolationMode.TABLE, table_suffix="t_1")
        )
        assert routing.table_suffix == "t_1"

    def test_schema_mode(self) -> None:
        routing = TenancyRouter().resolve(
            TenantInfo(tenant_id=1, mode=IsolationMode.SCHEMA, schema_name="tenant_1")
        )
        assert routing.schema_name == "tenant_1"

    def test_database_mode(self) -> None:
        routing = TenancyRouter().resolve(
            TenantInfo(tenant_id=1, mode=IsolationMode.DATABASE, data_source_name="ds_1")
        )
        assert routing.data_source_key == "ds_1"

    def test_database_without_datasource_rejected(self) -> None:
        with pytest.raises(TenantError):
            TenancyRouter().resolve(TenantInfo(tenant_id=1, mode=IsolationMode.DATABASE))

    def test_invalid_table_suffix_rejected(self) -> None:
        with pytest.raises(TenantError) as info:
            TenancyRouter().resolve(
                TenantInfo(tenant_id=1, mode=IsolationMode.TABLE, table_suffix="bad-name")
            )
        assert info.value.code == TenantErrorCode.TENANT_INVALID_NAMING

    def test_hybrid_as_tenant_mode_rejected(self) -> None:
        with pytest.raises(TenantError, match="delegate to itself"):
            TenancyRouter().resolve(TenantInfo(tenant_id=1, mode=IsolationMode.HYBRID))

    def test_invalid_tenant_id_rejected(self) -> None:
        with pytest.raises(TenantError) as info:
            TenancyRouter().resolve(TenantInfo(tenant_id=0, mode=IsolationMode.COLUMN))
        assert info.value.code == TenantErrorCode.INVALID_TENANT_ID

    def test_explicit_tenant_id_overrides(self) -> None:
        routing = TenancyRouter().resolve(
            TenantInfo(tenant_id=1, mode=IsolationMode.COLUMN), tenant_id=5
        )
        assert routing.mode is IsolationMode.COLUMN

    def test_none_tenant_info_rejected(self) -> None:
        with pytest.raises(TenantError):
            TenancyRouter().resolve(None)

    @pytest.mark.parametrize("tenant_id", [None, 0, -1])
    def test_validate_tenant_id(self, tenant_id) -> None:
        with pytest.raises(TenantError):
            validate_tenant_id(tenant_id)


class _Provider:
    def __init__(self, info: TenantInfo | None) -> None:
        self._info = info

    def get_tenant_info(self, tenant_id):
        return self._info

    def exists(self, tenant_id):
        return self._info is not None


def _active_info(tenant_id=7) -> TenantInfo:
    return TenantInfo(tenant_id=tenant_id, status=TenantStatus.ACTIVE)


class TestIdentityResolution:
    def test_disabled_passes_through(self) -> None:
        resolver = TenantIdentityResolver(_Provider(None), enabled=False)
        assert resolver.resolve("/api", {}).bound is False
        assert resolver.resolve("/api", {}).denied is False

    def test_whitelisted_path_passes(self) -> None:
        resolver = TenantIdentityResolver(
            _Provider(None), enforce_auth_tenant=True, whitelist=["/health", "/public/**"]
        )
        assert resolver.resolve("/health", {}).denied is False
        assert resolver.resolve("/public/x/y", {}).denied is False

    def test_assertion_resolver_wins(self) -> None:
        resolver = TenantIdentityResolver(
            _Provider(_active_info()),
            assertion_resolver=lambda h: TenantPrincipal(tenant_id=7),
            jwt_resolver=lambda h: TenantPrincipal(tenant_id=99),
        )
        resolution = resolver.resolve("/api", {})
        assert resolution.bound is True
        assert resolution.principal.tenant_id == 7

    def test_jwt_fallback(self) -> None:
        resolver = TenantIdentityResolver(
            _Provider(_active_info()),
            assertion_resolver=lambda h: None,
            jwt_resolver=lambda h: TenantPrincipal(tenant_id=7),
        )
        assert resolver.resolve("/api", {}).principal.tenant_id == 7

    def test_unsigned_header_only_when_allowed(self) -> None:
        provider = _Provider(_active_info())
        strict = TenantIdentityResolver(provider, enforce_auth_tenant=True)
        assert strict.resolve("/api", {"x-tenant-id": "7"}).denied is True
        permissive = TenantIdentityResolver(provider, allow_unsigned_header=True)
        assert permissive.resolve("/api", {"x-tenant-id": "7"}).principal.tenant_id == 7

    def test_enforce_missing_token_denied(self) -> None:
        resolver = TenantIdentityResolver(_Provider(None), enforce_auth_tenant=True)
        resolution = resolver.resolve("/api", {})
        assert resolution.error_code == TenantErrorCode.TENANT_AUTH_MISSING_TOKEN

    def test_not_enforced_missing_passes(self) -> None:
        resolver = TenantIdentityResolver(_Provider(None))
        assert resolver.resolve("/api", {}).denied is False

    def test_super_admin_path_bypasses_enforce(self) -> None:
        resolver = TenantIdentityResolver(
            _Provider(None), enforce_auth_tenant=True, super_admin_paths=["/admin/**"]
        )
        assert resolver.resolve("/admin/x", {}).denied is False

    def test_tenant_zero_requires_authenticated_super_admin(self) -> None:
        resolver = TenantIdentityResolver(
            _Provider(_active_info(0)), super_admin_paths=["/admin/**"]
        )
        # unsigned header tenantId=0 → 非认证 → 拒绝
        unsigned = TenantIdentityResolver(
            _Provider(_active_info(0)), allow_unsigned_header=True, super_admin_paths=["/admin/**"]
        )
        assert unsigned.resolve("/admin/x", {"x-tenant-id": "0"}).error_code == (
            TenantErrorCode.TENANT_AUTH_INVALID_FORMAT
        )
        # 认证 + 超管路径 → 放行
        authed = TenantIdentityResolver(
            _Provider(_active_info(0)),
            jwt_resolver=lambda h: TenantPrincipal(tenant_id=0),
            super_admin_paths=["/admin/**"],
        )
        assert authed.resolve("/admin/x", {}).bound is True

    def test_tenant_not_found(self) -> None:
        resolver = TenantIdentityResolver(
            _Provider(None), jwt_resolver=lambda h: TenantPrincipal(tenant_id=7)
        )
        assert resolver.resolve("/api", {}).error_code == TenantErrorCode.TENANT_IDENTITY_NOT_FOUND

    @pytest.mark.parametrize(
        ("status", "code"),
        [
            (TenantStatus.EXPIRED, TenantErrorCode.TENANT_AUTH_EXPIRED),
            (TenantStatus.MIGRATING, TenantErrorCode.TENANT_MIGRATING),
            (TenantStatus.INACTIVE, TenantErrorCode.TENANT_AUTH_INACTIVE),
            (None, TenantErrorCode.TENANT_AUTH_INACTIVE),
            (TenantStatus.PROVISIONING, TenantErrorCode.TENANT_PROVISIONING),
        ],
    )
    def test_status_errors(self, status, code) -> None:
        info = TenantInfo(tenant_id=7, status=status)
        resolver = TenantIdentityResolver(
            _Provider(info), jwt_resolver=lambda h: TenantPrincipal(tenant_id=7)
        )
        assert resolver.resolve("/api", {}).error_code == code

    def test_header_mismatch_denied(self) -> None:
        resolver = TenantIdentityResolver(
            _Provider(_active_info(7)), jwt_resolver=lambda h: TenantPrincipal(tenant_id=7)
        )
        resolution = resolver.resolve("/api", {"x-tenant-id": "8"})
        assert resolution.error_code == TenantErrorCode.TENANT_AUTH_MISMATCH

    def test_header_match_passes(self) -> None:
        resolver = TenantIdentityResolver(
            _Provider(_active_info(7)), jwt_resolver=lambda h: TenantPrincipal(tenant_id=7)
        )
        assert resolver.resolve("/api", {"x-tenant-id": "7"}).bound is True

    def test_invalid_header_value_ignored(self) -> None:
        resolver = TenantIdentityResolver(
            _Provider(_active_info(7)), jwt_resolver=lambda h: TenantPrincipal(tenant_id=7)
        )
        assert resolver.resolve("/api", {"x-tenant-id": "not-a-number"}).bound is True

    def test_none_provider_rejected(self) -> None:
        with pytest.raises(ValueError):
            TenantIdentityResolver(None)