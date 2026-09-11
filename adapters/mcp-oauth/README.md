# atlas-richie-mcp-oauth

Maps a standards-compliant OAuth resource-server authenticator to the MCP
`ToolContext`. It does not implement an authorization server or JWT library.

`OAuthDpopContextResolver` accepts only `Authorization: DPoP`, verifies the
`DPoP` proof against the mounted POST resource and access-token `cnf.jkt`, then
exposes a token-free `ToolContext` to MCP handlers.
