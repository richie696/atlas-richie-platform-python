"""Live Authorization Server integration test for `atlas_richie.oauth`.

中文
----
针对真实 OAuth 2.1 Authorization Server 的端到端联调（非 MockTransport）。
证明平台 OAuth 客户端与资源服务器验签适配器能对真实 AS 完成：

1. RFC 8414 元数据发现
2. client_credentials + RFC 8707 resource 取 token
3. 经 JWKS 的 RS256 本地验签（iss / aud / exp / sub）
4. 错误 audience 与篡改签名被拒收

运行前提：一个可达的 AS，并配置以下环境变量（缺 secret 或 AS 不可达
则整组 `pytest.skip`，因此 CI 无 AS 时自动跳过）：

    AS_ISSUER        默认 http://localhost:8892
    AS_CLIENT_ID     默认 client_integration_test
    AS_CLIENT_SECRET 必填（confidential 客户端明文 secret）
    AS_RESOURCE      默认 https://integration-test.local/mcp（URI audience）
    AS_SCOPE         默认 mcp.read

本地 AS 为 http，故显式注入 `AllowHttpEndpointPolicy`（组件默认仅 https）。

运行须知：若 shell 的 `NO_PROXY` 含 IPv6 条目（如 `[::1]`/`::1`），
httpx 0.28.1 解析代理环境变量时会构造 client 失败；本机联调请 unset
代理变量后运行，例如：

    env -u NO_PROXY -u no_proxy -u ALL_PROXY \
        .venv/bin/python -m pytest components/oauth/tests/test_e2e_live_as.py -m e2e

English
--------
End-to-end integration against a real OAuth 2.1 Authorization Server (no
MockTransport). Exercises RFC 8414 discovery, client_credentials with an
RFC 8707 resource indicator, JWKS-backed RS256 local validation, and
rejection of a wrong audience / tampered signature. Skips when the AS is
unreachable or `AS_CLIENT_SECRET` is unset, so CI without a live AS skips.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from atlas_richie.http import HttpClient
from atlas_richie.oauth import (
    AllowHttpEndpointPolicy,
    DpopProofVerifier,
    HttpJwkSetSource,
    InMemoryDpopReplayStore,
    OAuthAccessToken,
    OAuthClientCredentials,
    OAuthEndpointError,
    OAuthMetadataClient,
    OAuthTokenClient,
    OAuthTokenManager,
    OAuthTokenValidationError,
    PkcePair,
    ResourceIndicator,
    ResourceServerAuthenticator,
)
from atlas_richie.oauth.jose.dpop import JoseDpopProofFactory, JoseDpopProofValidator
from atlas_richie.oauth.jose.validator import JoseJwtTokenValidator

pytestmark = pytest.mark.e2e

AS_ISSUER = os.environ.get("AS_ISSUER", "http://localhost:8892")
AS_CLIENT_ID = os.environ.get("AS_CLIENT_ID", "client_integration_test")
AS_CLIENT_SECRET = os.environ.get("AS_CLIENT_SECRET", "")
AS_RESOURCE = os.environ.get("AS_RESOURCE", "https://integration-test.local/mcp")
AS_SCOPE = os.environ.get("AS_SCOPE", "mcp.read")
AS_SUBJECT_USERNAME = os.environ.get("AS_SUBJECT_USERNAME", "integration-subject")
AS_SUBJECT_PASSWORD = os.environ.get("AS_SUBJECT_PASSWORD", "")
AS_PUBLIC_CLIENT_ID = os.environ.get("AS_PUBLIC_CLIENT_ID", "client_integration_public")
AS_REDIRECT_URI = os.environ.get("AS_REDIRECT_URI", "https://integration-test.local/callback")

_METADATA_ENDPOINT = f"{AS_ISSUER}/.well-known/oauth-authorization-server"


@pytest.fixture(scope="module")
def live_as() -> Iterator[dict[str, object]]:
    """Discover the AS and yield the wired client/validator pieces.

    Skips the whole module when the secret is missing or the AS is not
    reachable, mirroring the real-Redis e2e convention.
    """
    if not AS_CLIENT_SECRET:
        pytest.skip("AS_CLIENT_SECRET is not set; live AS integration disabled")
    policy = AllowHttpEndpointPolicy()
    with HttpClient() as http_client:
        metadata_client = OAuthMetadataClient(http_client, endpoint_policy=policy)
        try:
            metadata = metadata_client.authorization_server(_METADATA_ENDPOINT)
        except Exception as exc:  # noqa: BLE001 — any discovery failure means no live AS
            pytest.skip(f"Authorization Server not reachable at {AS_ISSUER!r}: {exc}")
        if not metadata.token_endpoint or not metadata.jwks_uri:
            pytest.skip("AS metadata is missing token_endpoint or jwks_uri")
        token_client = OAuthTokenClient(http_client, endpoint_policy=policy)
        jwk_source = HttpJwkSetSource(http_client, metadata.jwks_uri, endpoint_policy=policy)
        yield {
            "metadata": metadata,
            "token_client": token_client,
            "jwk_source": jwk_source,
            "credentials": OAuthClientCredentials(AS_CLIENT_ID, AS_CLIENT_SECRET),
            "resource": ResourceIndicator(AS_RESOURCE),
        }


def _issue_token(live_as: dict[str, object]) -> str:
    token_client: OAuthTokenClient = live_as["token_client"]  # type: ignore[assignment]
    response = token_client.client_credentials(
        live_as["metadata"].token_endpoint,  # type: ignore[attr-defined]
        live_as["credentials"],  # type: ignore[arg-type]
        live_as["resource"],  # type: ignore[arg-type]
        frozenset({AS_SCOPE}),
    )
    return response.access_token.value


def _validator(live_as: dict[str, object], *, audience: str) -> JoseJwtTokenValidator:
    return JoseJwtTokenValidator(
        live_as["jwk_source"],  # type: ignore[arg-type]
        issuer=live_as["metadata"].issuer,  # type: ignore[attr-defined]
        audience=audience,
    )


def test_client_credentials_token_validates_via_jwks(live_as: dict[str, object]) -> None:
    token = _issue_token(live_as)
    authenticator = ResourceServerAuthenticator(
        _validator(live_as, audience=AS_RESOURCE),
        introspection_fallback=False,
    )
    principal = authenticator.authenticate(token)
    assert principal.subject == AS_CLIENT_ID
    assert principal.client_id == AS_CLIENT_ID
    assert principal.issuer == AS_ISSUER
    assert AS_RESOURCE in principal.audience
    assert AS_SCOPE in principal.scopes


def test_wrong_audience_is_rejected(live_as: dict[str, object]) -> None:
    token = _issue_token(live_as)
    authenticator = ResourceServerAuthenticator(
        _validator(live_as, audience="https://wrong-audience.local/mcp"),
        introspection_fallback=False,
    )
    with pytest.raises(OAuthTokenValidationError):
        authenticator.authenticate(token)


def test_tampered_signature_is_rejected(live_as: dict[str, object]) -> None:
    token = _issue_token(live_as)
    header, payload, signature = token.split(".")
    flipped = ("A" if signature[0] != "A" else "B") + signature[1:]
    tampered = f"{header}.{payload}.{flipped}"
    authenticator = ResourceServerAuthenticator(
        _validator(live_as, audience=AS_RESOURCE),
        introspection_fallback=False,
    )
    with pytest.raises(OAuthTokenValidationError):
        authenticator.authenticate(tampered)


def test_introspection_reports_active_token(live_as: dict[str, object]) -> None:
    token = _issue_token(live_as)
    token_client: OAuthTokenClient = live_as["token_client"]  # type: ignore[assignment]
    result = token_client.introspect(
        live_as["metadata"].introspection_endpoint,  # type: ignore[attr-defined]
        live_as["credentials"],  # type: ignore[arg-type]
        token,
    )
    assert result.active is True
    assert result.client_id == AS_CLIENT_ID
    assert AS_RESOURCE in result.audience
    assert AS_SCOPE in result.scopes


def test_revocation_deactivates_token(live_as: dict[str, object]) -> None:
    token = _issue_token(live_as)
    token_client: OAuthTokenClient = live_as["token_client"]  # type: ignore[assignment]
    credentials: OAuthClientCredentials = live_as["credentials"]  # type: ignore[assignment]
    introspection_endpoint = live_as["metadata"].introspection_endpoint  # type: ignore[attr-defined]
    assert token_client.introspect(introspection_endpoint, credentials, token).active is True
    token_client.revoke(
        live_as["metadata"].revocation_endpoint,  # type: ignore[attr-defined]
        credentials,
        token=token,
        token_type_hint="access_token",
    )
    assert token_client.introspect(introspection_endpoint, credentials, token).active is False


def _issue_dpop_token(live_as: dict[str, object], factory: JoseDpopProofFactory):  # type: ignore[no-untyped-def]
    with HttpClient() as http_client:
        client = OAuthTokenClient(
            http_client,
            endpoint_policy=AllowHttpEndpointPolicy(),
            dpop_proof_factory=factory,
        )
        response = client.client_credentials(
            live_as["metadata"].token_endpoint,  # type: ignore[attr-defined]
            live_as["credentials"],  # type: ignore[arg-type]
            live_as["resource"],  # type: ignore[arg-type]
            frozenset({AS_SCOPE}),
        )
        return response.access_token


def _jwt_claims(token: str) -> dict[str, object]:
    import base64
    import json

    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def test_dpop_client_credentials_binds_token(live_as: dict[str, object]) -> None:
    factory = JoseDpopProofFactory.generate()
    access = _issue_dpop_token(live_as, factory)
    assert access.token_type == "DPoP"
    claims = _jwt_claims(access.value)
    confirmation = claims.get("cnf")
    assert isinstance(confirmation, dict)
    assert confirmation.get("jkt") == factory.key_thumbprint
    principal = _validator(live_as, audience=AS_RESOURCE).validate(access.value)
    assert principal.subject == AS_CLIENT_ID


def test_dpop_resource_request_verifies(live_as: dict[str, object]) -> None:
    factory = JoseDpopProofFactory.generate()
    access = _issue_dpop_token(live_as, factory)
    resource_uri = f"{AS_RESOURCE}/data"
    proof = factory.create(method="GET", target_uri=resource_uri, access_token=access.value)
    authenticator = ResourceServerAuthenticator(
        _validator(live_as, audience=AS_RESOURCE),
        introspection_fallback=False,
    )
    verifier = DpopProofVerifier(JoseDpopProofValidator(), InMemoryDpopReplayStore())
    principal = authenticator.authenticate_dpop(
        access.value,
        proof,
        method="GET",
        target_uri=resource_uri,
        verifier=verifier,
    )
    assert principal.subject == AS_CLIENT_ID
    assert AS_SCOPE in principal.scopes


def test_dpop_proof_bound_to_other_token_is_rejected(live_as: dict[str, object]) -> None:
    factory = JoseDpopProofFactory.generate()
    access = _issue_dpop_token(live_as, factory)
    resource_uri = f"{AS_RESOURCE}/data"
    proof = factory.create(method="GET", target_uri=resource_uri, access_token="not-the-issued-token")
    authenticator = ResourceServerAuthenticator(
        _validator(live_as, audience=AS_RESOURCE),
        introspection_fallback=False,
    )
    verifier = DpopProofVerifier(JoseDpopProofValidator(), InMemoryDpopReplayStore())
    with pytest.raises(OAuthTokenValidationError):
        authenticator.authenticate_dpop(
            access.value,
            proof,
            method="GET",
            target_uri=resource_uri,
            verifier=verifier,
        )


def _authorization_code_response(live_as: dict[str, object]):  # type: ignore[no-untyped-def]
    """Drive the AS authorize/login/consent surfaces, then exchange the code
    through the platform OAuth client (PKCE S256). The browser-like steps use
    httpx with a cookie session; the platform-relevant token exchange and any
    refresh go through `OAuthTokenClient`/`OAuthTokenManager`.
    """
    if not AS_SUBJECT_PASSWORD:
        pytest.skip("AS_SUBJECT_PASSWORD is not set; authorization_code flow disabled")
    pair = PkcePair.generate()
    with httpx.Client(follow_redirects=False, trust_env=False, timeout=15) as browser:
        authorize = browser.get(
            f"{AS_ISSUER}/oauth2/authorize",
            params={
                "client_id": AS_PUBLIC_CLIENT_ID,
                "redirect_uri": AS_REDIRECT_URI,
                "response_type": "code",
                "scope": f"{AS_SCOPE} openid",
                "state": "integration-state",
                "nonce": "integration-nonce",
                "resource": AS_RESOURCE,
                "code_challenge": pair.challenge,
                "code_challenge_method": "S256",
            },
        )
        request_id = parse_qs(urlparse(authorize.headers["location"]).query)["request_id"][0]
        browser.post(
            f"{AS_ISSUER}/oauth2/authorization-requests/{request_id}/login",
            json={"username": AS_SUBJECT_USERNAME, "password": AS_SUBJECT_PASSWORD},
        ).raise_for_status()
        consent = browser.post(
            f"{AS_ISSUER}/oauth2/authorization-requests/{request_id}/consent",
            json={"approved": True},
        )
        consent.raise_for_status()
        code = parse_qs(urlparse(consent.json()["redirectUri"]).query)["code"][0]
    token_client: OAuthTokenClient = live_as["token_client"]  # type: ignore[assignment]
    return token_client.authorization_code(
        live_as["metadata"].token_endpoint,  # type: ignore[attr-defined]
        OAuthClientCredentials(AS_PUBLIC_CLIENT_ID),
        code=code,
        redirect_uri=AS_REDIRECT_URI,
        code_verifier=pair.verifier,
        resource=ResourceIndicator(AS_RESOURCE),
    )


def test_authorization_code_pkce_yields_refresh_token(live_as: dict[str, object]) -> None:
    response = _authorization_code_response(live_as)
    assert response.refresh_token
    principal = _validator(live_as, audience=AS_RESOURCE).validate(response.access_token.value)
    assert principal.subject
    assert AS_RESOURCE in principal.audience
    assert AS_SCOPE in principal.scopes


def test_refresh_token_rotates_and_replay_rejected(live_as: dict[str, object]) -> None:
    response = _authorization_code_response(live_as)
    resource = ResourceIndicator(AS_RESOURCE)
    manager = OAuthTokenManager(
        live_as["token_client"],  # type: ignore[arg-type]
        token_endpoint=live_as["metadata"].token_endpoint,  # type: ignore[attr-defined]
        credentials=OAuthClientCredentials(AS_PUBLIC_CLIENT_ID),
        resource=resource,
    )
    manager.accept(response)
    original_refresh = response.refresh_token
    manager._access_token = OAuthAccessToken(  # type: ignore[attr-defined]
        response.access_token.value, datetime.now(UTC) - timedelta(minutes=5), resource=resource
    )
    rotated = manager.token_for(resource)
    assert rotated.value != response.access_token.value
    assert manager._refresh_token != original_refresh  # type: ignore[attr-defined]
    manager._access_token = OAuthAccessToken(  # type: ignore[attr-defined]
        rotated.value, datetime.now(UTC) - timedelta(minutes=5), resource=resource
    )
    manager._refresh_token = original_refresh  # type: ignore[attr-defined]
    with pytest.raises(OAuthEndpointError) as ctx:
        manager.token_for(resource)
    assert ctx.value.error == "invalid_grant"


def test_device_code_flow(live_as: dict[str, object]) -> None:
    if not AS_SUBJECT_PASSWORD:
        pytest.skip("AS_SUBJECT_PASSWORD is not set; device flow disabled")
    device_client_id = os.environ.get("AS_DEVICE_CLIENT_ID", "client_integration_device")
    credentials = OAuthClientCredentials(device_client_id)
    resource = ResourceIndicator(AS_RESOURCE)
    scopes = frozenset({AS_SCOPE})
    token_client: OAuthTokenClient = live_as["token_client"]  # type: ignore[assignment]
    token_endpoint = live_as["metadata"].token_endpoint  # type: ignore[attr-defined]
    authorization = token_client.device_authorization(
        f"{AS_ISSUER}/oauth2/device_authorization", credentials, resource=resource, scopes=scopes
    )
    assert authorization.device_code and authorization.user_code
    with pytest.raises(OAuthEndpointError) as pending:
        token_client.device_code(token_endpoint, credentials, device_code=authorization.device_code, resource=resource, scopes=scopes)
    assert pending.value.error in {"authorization_pending", "slow_down"}
    with httpx.Client(follow_redirects=False, trust_env=False, timeout=15) as browser:
        browser.post(
            f"{AS_ISSUER}/oauth2/device/verification/{authorization.user_code}/login",
            json={"username": AS_SUBJECT_USERNAME, "password": AS_SUBJECT_PASSWORD},
        ).raise_for_status()
        browser.post(
            f"{AS_ISSUER}/oauth2/device/verification/{authorization.user_code}/consent",
            params={"approved": "true"},
        ).raise_for_status()
    response = token_client.device_code(token_endpoint, credentials, device_code=authorization.device_code, resource=resource, scopes=scopes)
    principal = _validator(live_as, audience=AS_RESOURCE).validate(response.access_token.value)
    assert AS_RESOURCE in principal.audience
    assert AS_SCOPE in principal.scopes