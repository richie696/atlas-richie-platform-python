# Atlas Richie Python Platform 任务清单

> 本文件是当前工程任务状态的单一事实来源。`[x]` 表示源码实现并有受控测试或构建证据；`[ ]` 表示待实现或待真实环境验证。构建、单元测试和 wheel 安装不等于真实互操作或生产验收。

## 工程与发布基础

- [x] Python 3.12+、`uv` workspace、多独立发行包
- [x] `contracts` / `testing` / `platform` 聚合包边界
- [x] wheel/sdist 构建、依赖边界、锁文件检查
- [x] Pythonic API、OOP、具名语义值与禁止重复实现的工程宪章
- [x] CI Python 3.12–3.15 完整版本矩阵
- [x] 发布版本、变更日志、PyPI trusted-publishing 流程

## HTTP Component

- [x] 单一 HTTPX 内部实现；公共 API 不泄漏 HTTPX
- [x] 不可变链式请求：查询参数、headers、JSON、XML、SOAP、form、multipart
- [x] 同步/异步 client、显式生命周期、超时、连接限制、响应上限和错误分类
- [x] request-id、审计与有序调用切面
- [x] 同步/异步流式响应与 SSE 解析
- [ ] 重试预算、幂等策略、熔断、限流（由 future concurrency/resilience 组件定义）
- [ ] 真实 TCP、DNS、代理、企业 CA、HTTP/2、SSE 长连接验证

## OAuth 2.1 Component（不实现 Authorization Server）

- [x] Authorization Server Metadata、PRM、PKCE S256、Resource Indicator
- [x] Client Credentials、Authorization Code + PKCE、Refresh Token、Introspection
- [x] Token Manager、JWT/JWKS、JWT-first + introspection fallback
- [x] Device Authorization、Device Code 单次兑换、Revocation、远程 DCR、OIDC UserInfo
- [x] DPoP 核心：请求/令牌/`cnf.jkt`/`ath` 绑定、时间窗、nonce、防重放
- [x] JOSERFC DPoP 签名与验签适配器
- [x] DPoP 接入 OAuth token 请求、MCP HTTP 出站与 ASGI 入站认证链
- [x] 分布式 JWKS、introspection、DPoP replay cache adapter（**R-103 已撤回**：cache 协议不该嵌进 OAuth，richie696 现场纠正；R-200 之后独立 `components/cache/` 仓 + 真实 Redis adapter，详见 `docs/acceptance/R-cache-java-python-alignment.md`）
- [x] OIDC ID Token 验证、RP-initiated logout（R-102：IdTokenValidator + RpInitiatedLogout Builder + code_hash helper）
- [ ] 真实标准 IdP 的授权流、密钥轮换与 DPoP 验证

## MCP Component

- [x] MCP `2026-07-28` JSON-RPC core、server/client、stdio
- [x] tools/resources/prompts/completion、分页、Schema fail-closed
- [x] Draft 2020-12 JSON Schema adapter，拒绝外部 `$ref`
- [x] ASGI HTTP 协议桥、header/body mirror、Origin、JSON 响应
- [x] HTTP 出站 MCP exchange adapter
- [x] OAuth Bearer 到无 token `ToolContext` bridge、scope 再授权
- [x] 协作式取消与 HMAC 完整性保护 MRTR state codec
- [x] 注册表全量原子快照、revision、reload、change listener
- [x] MCP invocation interceptor：审计、trace、deadline、progress 的固定链
- [x] Streamable HTTP SSE 响应、progress 通知、订阅、断流处理
- [x] MRTR codec 与 server/transport 的完整绑定及 revision 校验
- [x] client 协商缓存、失效策略、自动分页
- [x] legacy `2025-11-25` dialect adapter 与兼容矩阵
- [x] DPoP MCP 双向认证接入（出站仅接受 DPoP token；入站绑定 POST/resource/`cnf.jkt`）
- [x] 双应用 A→B / B→A 可镜像的 M2M profile（目标 resource、最小 scope、DPoP token）
- [x] 客户端 SSE 消费 + progress 回调 + 取消传播 + RetryPolicy `first_byte_only`（R-101）
- [ ] 双应用 A→B / B→A 的真实 OAuth/HTTPS 实证

## 后续独立 Component 与应用

- [x] resilience（R-104：retry / circuit-breaker / rate-limit / bulkhead / idempotency-key 5 个原语）
- [ ] secret、logging、tracing、cache
- [ ] storage、vector、document、AI
- [ ] Gateway、Antivirus 应用层

## 集成与互操作验证

- [ ] 两个独立 Python 进程的双向 MCP 调用
- [ ] 真实 HTTPS、SSE、OAuth IdP、JWKS 轮换
- [ ] 无 token、错误 issuer/audience、过期 token、scope 不足、tenant 串用
- [ ] Java ↔ Python MCP 标准协议互操作
- [ ] 官方 conformance / wire fixture 验证
- [ ] 性能、并发、故障恢复与安全扫描

## 当前下一项

**R-201：新建独立 `components/cache/` 仓 + 真实 Redis adapter（沿 Java 仓 24 项功能全做，scope 由 `docs/acceptance/R-cache-java-python-alignment.md` 锁定）**。
