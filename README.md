# Atlas Richie Platform for Python

一个可裁剪、框架无关的 Python Component 中台。它不是 Python 版 Spring：应用可以在
FastAPI、Django、Flask、CLI、Worker 或无框架脚本中显式装配所需组件，而无需继承平台运行时。

## 当前内容

| 发行包 | 职责 | 运行时依赖 |
|---|---|---|
| `atlas-richie-contracts` | 稳定错误、能力与生命周期契约 | 标准库 |
| `atlas-richie-testing` | 轻量契约测试辅助 | contracts |
| `atlas-richie-http` | 统一 HTTP 语义、错误与调用切面 | HTTPX（仅内部实现） |
| `atlas-richie-mcp` | MCP modern core、工具注册与 stdio framing | contracts + 标准库 |
| `atlas-richie-mcp-schema-jsonschema` | Draft 2020-12 Schema 编译与本地校验 | MCP + jsonschema |
| `atlas-richie-mcp-asgi` | 无框架 ASGI MCP HTTP bridge | MCP |
| `atlas-richie-mcp-oauth` | OAuth Bearer 到 MCP 认证上下文与 PRM challenge | MCP + OAuth |
| `atlas-richie-mcp-http` | 基于 owned HTTP component 的远程 MCP exchange | MCP + HTTP |
| `atlas-richie-mcp-legacy` | 可选 `2025-11-25` legacy dialect 兼容层 | MCP |
| `atlas-richie-oauth` | OAuth 2.1 客户端、元数据、PKCE 与资源服务契约 | contracts + HTTP component |
| `atlas-richie-oauth-jose` | RS256 JWT/JWKS 本地验签适配器 | OAuth component + JOSERFC |
| `atlas-richie-platform` | 已验证组合的安装入口 | contracts + HTTP + MCP + OAuth |

基线为 Python 3.12；支持窗口与版本策略见
[VERSIONING.md](VERSIONING.md)。完整实施、验证与待办状态见
[TASK_CHECKLIST.md](TASK_CHECKLIST.md)。`uv.lock` 是可提交的开发/CI 解析记录。
GitHub Actions 会在 Python 3.12–3.15 运行同一受控验证；带 `v*` tag 的受保护发布流程使用 PyPI trusted publishing。

## MCP 最小使用方式

```python
from atlas_richie.mcp import McpClient, McpServer, ToolContext

server = McpServer()

@server.tool(description="Return a greeting.")
def greet(_context: ToolContext, name: str) -> dict[str, str]:
    return {"greeting": f"Hello, {name}!"}

client = McpClient(server.handle)  # production code supplies an explicit transport
result = await client.call_tool("greet", {"name": "Ada"})
```

工具装饰器只注册不可变元数据，函数本身仍可直接调用。stdio transport 使用一行一个 JSON
frame，并保留 stdout 给协议；日志由应用写至 stderr。

MCP 现在支持 `server/discover`、tools、resources、resource templates、prompts、completion、
pagination 与 `input_required` MRTR 结果。Schema、ASGI、OAuth 和远程 HTTP 都是独立适配器，
不进入 core 依赖树。OAuth component 仍只提供 OAuth 2.1 client/resource-server 能力，
不包含 Authorization Server。

真实 HTTPS/SSE、第三方标准 Authorization Server 和跨语言端到端互操作尚未验证；受控
测试矩阵、路线和双向认证边界见
[docs/acceptance/mcp-2026-07-28-test-matrix.md](docs/acceptance/mcp-2026-07-28-test-matrix.md)。

## 本地验证

```bash
uv lock --check
uv run python -m unittest discover -s components/mcp/tests -v
uv run python -m unittest discover -s adapters/mcp-schema-jsonschema/tests -v
uv run python -m unittest discover -s adapters/mcp-asgi/tests -v
uv run python -m unittest discover -s adapters/mcp-oauth/tests -v
uv run python -m unittest discover -s adapters/mcp-http/tests -v
uv run python -m unittest discover -s adapters/mcp-legacy/tests -v
uv run python -m unittest discover -s components/oauth/tests -v
uv run python -m unittest discover -s adapters/oauth-jose/tests -v
uv build --all-packages
/opt/homebrew/opt/python@3.12/bin/python3.12 tools/release/prepare_wheelhouse.py
/opt/homebrew/opt/python@3.12/bin/python3.12 tools/release/verify_isolated_wheels.py
```

这些验证证明 P0/P1 本地包构建、安装、导入以及 MCP/HTTP/OAuth 契约；它们不替代真实
网络、第三方标准 Authorization Server 或跨语言端到端互操作验证。
