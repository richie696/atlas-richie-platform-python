"""Live HTTPS integration against a real Authorization Server with a custom CA.

中文
----
补「真实 HTTPS 未验证」缺口：平台 OAuth 组件在**默认 HttpsOnlyEndpointPolicy**
下，经自定义 CA 信任的本地 HTTPS AS 完成元数据发现、client_credentials 取
token 与 JWKS RS256 验签；并证明默认系统信任库会拒绝该本地 CA（即 CA 注入
确实生效）。

运行前提：一个 HTTPS AS（如本地 mkcert/openssl 自签实例），并配置：

    AS_HTTPS_ISSUER  必填，如 https://localhost:8443
    AS_CA_FILE       必填，信任该 AS 的 CA PEM 路径
    AS_CLIENT_ID / AS_CLIENT_SECRET / AS_RESOURCE / AS_SCOPE  同 http 联调

缺任一前提或 AS 不可达则整组 skip。

English
--------
Closes the "real HTTPS unverified" gap: under the default HttpsOnlyEndpointPolicy,
the platform OAuth components discover metadata, obtain a client_credentials token,
and validate it via JWKS RS256 against a local HTTPS AS trusted through a custom CA;
also proves the default system trust store rejects that local CA. Skips without the
HTTPS issuer / CA file / secret or when the AS is unreachable.
"""

from __future__ import annotations

import os
import ssl
from collections.abc import Iterator

import pytest

from atlas_richie.http import HttpClient, HttpClientOptions, HttpTransportError
from atlas_richie.oauth import (
    HttpJwkSetSource,
    OAuthClientCredentials,
    OAuthMetadataClient,
    OAuthTokenClient,
    ResourceIndicator,
    ResourceServerAuthenticator,
)
from atlas_richie.oauth.jose.validator import JoseJwtTokenValidator

pytestmark = pytest.mark.e2e

AS_HTTPS_ISSUER = os.environ.get("AS_HTTPS_ISSUER", "")
AS_CA_FILE = os.environ.get("AS_CA_FILE", "")
AS_CLIENT_ID = os.environ.get("AS_CLIENT_ID", "client_integration_test")
AS_CLIENT_SECRET = os.environ.get("AS_CLIENT_SECRET", "")
AS_RESOURCE = os.environ.get("AS_RESOURCE", "https://integration-test.local/mcp")
AS_SCOPE = os.environ.get("AS_SCOPE", "mcp.read")


@pytest.fixture(scope="module")
def live_https() -> Iterator[dict[str, object]]:
    if not AS_CLIENT_SECRET:
        pytest.skip("AS_CLIENT_SECRET is not set; live HTTPS integration disabled")
    if not AS_HTTPS_ISSUER or not AS_CA_FILE or not os.path.exists(AS_CA_FILE):
        pytest.skip("AS_HTTPS_ISSUER / AS_CA_FILE not configured; live HTTPS integration disabled")
    context = ssl.create_default_context(cafile=AS_CA_FILE)
    options = HttpClientOptions(ssl_context=context)
    with HttpClient(options) as http_client:
        metadata_client = OAuthMetadataClient(http_client)
        try:
            metadata = metadata_client.authorization_server(
                f"{AS_HTTPS_ISSUER}/.well-known/oauth-authorization-server"
            )
        except Exception as exc:  # noqa: BLE001 — discovery failure means no live HTTPS AS
            pytest.skip(f"HTTPS Authorization Server not reachable at {AS_HTTPS_ISSUER!r}: {exc}")
        yield {
            "metadata": metadata,
            "token_client": OAuthTokenClient(http_client),
            "jwk_source": HttpJwkSetSource(http_client, metadata.jwks_uri),
            "credentials": OAuthClientCredentials(AS_CLIENT_ID, AS_CLIENT_SECRET),
            "resource": ResourceIndicator(AS_RESOURCE),
        }


def test_https_client_credentials_validates_via_jwks(live_https: dict[str, object]) -> None:
    token_client: OAuthTokenClient = live_https["token_client"]  # type: ignore[assignment]
    response = token_client.client_credentials(
        live_https["metadata"].token_endpoint,  # type: ignore[attr-defined]
        live_https["credentials"],  # type: ignore[arg-type]
        live_https["resource"],  # type: ignore[arg-type]
        frozenset({AS_SCOPE}),
    )
    validator = JoseJwtTokenValidator(
        live_https["jwk_source"],  # type: ignore[arg-type]
        issuer=live_https["metadata"].issuer,  # type: ignore[attr-defined]
        audience=AS_RESOURCE,
    )
    principal = ResourceServerAuthenticator(validator, introspection_fallback=False).authenticate(
        response.access_token.value
    )
    assert principal.issuer == AS_HTTPS_ISSUER
    assert principal.subject == AS_CLIENT_ID
    assert AS_RESOURCE in principal.audience
    assert AS_SCOPE in principal.scopes


def test_https_default_trust_store_rejects_local_ca(live_https: dict[str, object]) -> None:
    with HttpClient() as http_client:
        metadata_client = OAuthMetadataClient(http_client)
        with pytest.raises(HttpTransportError):
            metadata_client.authorization_server(
                f"{AS_HTTPS_ISSUER}/.well-known/oauth-authorization-server"
            )