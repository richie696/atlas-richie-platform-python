"""Live MCP OAuth integration against a real Authorization Server.

中文
----
证明 MCP OAuth 桥接与真实 AS 的完整互操作链路（非 mock）：

1. RFC 9728 protected-resource metadata 发现（hosted PRM 文档指向 AS）
2. RFC 8414 AS 元数据发现 → client_credentials 取真实 token
3. `OAuthBearerContextResolver` 接受真实 AS token → ToolContext；缺失
   token 时返回携带 `resource_metadata` 的安全 401 challenge
4. MCP M2M DPoP profile（`McpM2mAuthorization`）取 DPoP-bound token，
   `OAuthDpopContextResolver` 校验 proof 后解析 ToolContext

运行前提与 `components/oauth/tests/test_e2e_live_as.py` 相同（AS_ISSUER /
AS_CLIENT_ID / AS_CLIENT_SECRET / AS_RESOURCE / AS_SCOPE）；缺 secret 或
AS 不可达则整组 skip。PRM 文档由测试内一个临时 HTTP 服务托管。本地 AS
为 http，显式注入 AllowHttpEndpointPolicy；NO_PROXY 含 IPv6 时请 unset
代理变量后运行。

English
--------
Proves the MCP OAuth bridge interoperates with a real AS: RFC 9728 PRM
discovery (a hosted PRM document pointing at the AS), RFC 8414 discovery,
client_credentials token issuance, bearer context resolution + safe 401
challenge, and the M2M DPoP profile end to end. Skips without a live AS.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from atlas_richie.http import HttpClient
from atlas_richie.mcp import AuthenticationError
from atlas_richie.mcp.security.oauth import (
    McpM2mAuthorization,
    McpM2mTarget,
    OAuthBearerContextResolver,
    OAuthDpopContextResolver,
)
from atlas_richie.oauth import (
    AllowHttpEndpointPolicy,
    DpopProofVerifier,
    HttpJwkSetSource,
    InMemoryDpopReplayStore,
    OAuthClientCredentials,
    OAuthMetadataClient,
    OAuthTokenClient,
    OAuthTokenManager,
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

_PRM_PATH = "/.well-known/oauth-protected-resource"


def _start_prm_server(document: dict[str, object]) -> tuple[ThreadingHTTPServer, str]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 — http.server API
            if self.path.split("?")[0] != _PRM_PATH:
                self.send_response(404)
                self.end_headers()
                return
            body = json.dumps(document).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    uri = f"http://127.0.0.1:{server.server_address[1]}{_PRM_PATH}"
    return server, uri


@pytest.fixture(scope="module")
def live_mcp() -> Iterator[dict[str, object]]:
    if not AS_CLIENT_SECRET:
        pytest.skip("AS_CLIENT_SECRET is not set; live MCP OAuth integration disabled")
    document = {
        "resource": AS_RESOURCE,
        "authorization_servers": [AS_ISSUER],
        "scopes_supported": [AS_SCOPE],
    }
    server, prm_uri = _start_prm_server(document)
    policy = AllowHttpEndpointPolicy()
    with HttpClient() as http_client:
        metadata_client = OAuthMetadataClient(http_client, endpoint_policy=policy)
        try:
            as_metadata = metadata_client.authorization_server(
                f"{AS_ISSUER}/.well-known/oauth-authorization-server"
            )
        except Exception as exc:  # noqa: BLE001 — discovery failure means no live AS
            server.shutdown()
            pytest.skip(f"Authorization Server not reachable at {AS_ISSUER!r}: {exc}")
        yield {
            "prm_uri": prm_uri,
            "metadata_client": metadata_client,
            "as_metadata": as_metadata,
            "http_client": http_client,
            "token_client": OAuthTokenClient(http_client, endpoint_policy=policy),
            "jwk_source": HttpJwkSetSource(http_client, as_metadata.jwks_uri, endpoint_policy=policy),
            "credentials": OAuthClientCredentials(AS_CLIENT_ID, AS_CLIENT_SECRET),
            "resource": ResourceIndicator(AS_RESOURCE),
            "policy": policy,
        }
    server.shutdown()


def _authenticator(live_mcp: dict[str, object]) -> ResourceServerAuthenticator:
    validator = JoseJwtTokenValidator(
        live_mcp["jwk_source"],  # type: ignore[arg-type]
        issuer=live_mcp["as_metadata"].issuer,  # type: ignore[attr-defined]
        audience=AS_RESOURCE,
    )
    return ResourceServerAuthenticator(validator, introspection_fallback=False)


def test_prm_discovery_points_to_as(live_mcp: dict[str, object]) -> None:
    metadata_client: OAuthMetadataClient = live_mcp["metadata_client"]  # type: ignore[assignment]
    prm = metadata_client.protected_resource(live_mcp["prm_uri"])  # type: ignore[arg-type]
    assert prm.resource.value == AS_RESOURCE
    assert prm.authorization_servers == (AS_ISSUER,)
    assert AS_SCOPE in prm.scopes_supported


def test_bearer_resolver_accepts_real_as_token(live_mcp: dict[str, object]) -> None:
    token_client: OAuthTokenClient = live_mcp["token_client"]  # type: ignore[assignment]
    response = token_client.client_credentials(
        live_mcp["as_metadata"].token_endpoint,  # type: ignore[attr-defined]
        live_mcp["credentials"],  # type: ignore[arg-type]
        live_mcp["resource"],  # type: ignore[arg-type]
        frozenset({AS_SCOPE}),
    )
    resolver = OAuthBearerContextResolver(
        _authenticator(live_mcp), resource_metadata_uri=live_mcp["prm_uri"]  # type: ignore[arg-type]
    )
    context = resolver({"Authorization": f"Bearer {response.access_token.value}"})
    assert context.principal_id == AS_CLIENT_ID
    assert AS_SCOPE in context.granted_scopes


def test_bearer_missing_token_returns_prm_challenge(live_mcp: dict[str, object]) -> None:
    resolver = OAuthBearerContextResolver(
        _authenticator(live_mcp), resource_metadata_uri=live_mcp["prm_uri"]  # type: ignore[arg-type]
    )
    with pytest.raises(AuthenticationError) as captured:
        resolver({})
    assert captured.value.challenge == f'Bearer resource_metadata="{live_mcp["prm_uri"]}"'


def test_m2m_dpop_authorization_and_resolver(live_mcp: dict[str, object]) -> None:
    factory = JoseDpopProofFactory.generate()
    dpop_client = OAuthTokenClient(
        live_mcp["http_client"],  # type: ignore[arg-type]
        endpoint_policy=live_mcp["policy"],  # type: ignore[arg-type]
        dpop_proof_factory=factory,
    )
    manager = OAuthTokenManager(
        dpop_client,
        token_endpoint=live_mcp["as_metadata"].token_endpoint,  # type: ignore[attr-defined]
        credentials=live_mcp["credentials"],  # type: ignore[arg-type]
        resource=live_mcp["resource"],  # type: ignore[arg-type]
        configured_scopes=frozenset({AS_SCOPE}),
    )
    authorization = McpM2mAuthorization(manager, McpM2mTarget(live_mcp["resource"], frozenset({AS_SCOPE})))  # type: ignore[arg-type]
    header = authorization.authorization_for()
    assert header.startswith("DPoP ")
    token = header.split(" ", 1)[1]
    proof = factory.create(method="POST", target_uri=AS_RESOURCE, access_token=token)
    resolver = OAuthDpopContextResolver(
        _authenticator(live_mcp),
        DpopProofVerifier(JoseDpopProofValidator(), InMemoryDpopReplayStore()),
        resource_metadata_uri=live_mcp["prm_uri"],  # type: ignore[arg-type]
        target_uri=AS_RESOURCE,
    )
    context = resolver({"Authorization": header, "DPoP": proof})
    assert context.principal_id == AS_CLIENT_ID
    assert AS_SCOPE in context.granted_scopes