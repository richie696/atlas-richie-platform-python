# atlas-richie-mcp-http

Async MCP HTTP exchange built on the owned `atlas-richie-http` component rather
than leaking HTTPX into MCP client code.

When configured with a DPoP proof factory, the adapter requires `Authorization:
DPoP <access-token>` and binds every proof to the mounted MCP endpoint and POST
method. It deliberately rejects a bearer token plus a DPoP factory because that
combination cannot prove possession for the access token.
