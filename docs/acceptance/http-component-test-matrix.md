# HTTP Component P1 验收矩阵

| ID | 风险与来源 | 层次 | 断言 |
|---|---|---|---|
| HTTP-001 | Facade 不泄漏 HTTPX，受控 HTTPX transport 可互通 | 组件 | 请求 ID 到达 transport；响应是平台 DTO。 |
| HTTP-002 | 切面顺序与短路语义 | 单元 | RequestId、Audit、调用方切面按固定顺序；短路不触网且 Audit 可见。 |
| HTTP-003 | 错误与 HTTP 状态混淆 | 单元/组件 | connect、timeout、响应过大、JSON 解码与非 2xx 为不同类别。 |
| HTTP-004 | 资源泄漏或关闭后继续使用 | 单元/组件 | sync close / async aclose 幂等；关闭后受控拒绝。 |
| HTTP-005 | 默认安全退化 | 单元 | 不覆盖 caller request ID；默认不跟随 redirect；审计事件无 header/body。 |

测试使用标准库 `unittest` 和 HTTPX 官方受控 transport；它们证明 HTTPX 映射和平台契约，
不证明 TCP/DNS、代理、企业 CA、HTTP/2、真实 OAuth issuer 或生产网络行为。
