# atlas-richie-mcp-legacy

Optional compatibility adapter for MCP `2025-11-25`. It translates legacy
`initialize` handshakes and implicit `complete` results into the same Python
facades used by the `2026-07-28` core. It does not add legacy HTTP sessions or
deprecated SSE transports.
