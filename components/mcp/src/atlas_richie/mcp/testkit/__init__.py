"""MCP 协议夹具（testkit）。

中文
----
对位 Java `atlas-richie-mcp-testkit` 子模块。Python 端目前使用
pytest 内部的 fixture 机制（见 `components/mcp/tests/`），本子包为
未来跨包复用夹具预留位置（例如把 `McpProtocolFixtures` /
`McpToolFixtures` 从测试文件提到这里供外部 conformance 测试使用）。

English
--------
MCP protocol testkit — mirrors the Java `atlas-richie-mcp-testkit`
sub-module. The Python side currently uses pytest in-file fixtures
(see `components/mcp/tests/`); this sub-package is reserved for
future shared fixtures (e.g. extracting `McpProtocolFixtures` and
`McpToolFixtures` for cross-package conformance tests).
"""
