# Atlas Richie Python HTTP Component

> 状态：HTTP 请求表达、受限响应、同步/异步流与 SSE 解析已实施并有受控单元测试。它是**出站 HTTP 客户端**，不是 HTTP server、框架 adapter、
> OAuth 实现或多 Provider 框架。

## 目标与唯一职责

`atlas-richie-http` 统一拥有跨应用的 HTTP 行为：请求/响应 DTO、超时与连接
限制、安全默认值、错误分类、资源生命周期和受控调用切面。HTTPX 是唯一的内部网络实现；
业务代码不 import HTTPX，也没有 `provider` 配置或运行时切换。

## 公开契约

```text
HttpRequest / HttpResponse / HttpClientOptions
HttpClient                # 同步，显式 close / context manager
AsyncHttpClient           # 异步，显式 aclose / async context manager
HttpInterceptor / AsyncHttpInterceptor
HttpError hierarchy
```

`HttpResponse` 默认返回已受大小上限保护的 bytes；非 2xx 是正常 HTTP 响应，调用
`require_success()` 才转换为 `HttpStatusError`。网络、TLS、连接、读写超时、协议、解码、
响应过大与客户端已关闭都有不同的错误类别。

`HttpRequest` 是不可变值，支持 Pythonic 的链式构造：查询参数、headers、JSON、XML、
SOAP 1.2、urlencoded form 和 multipart 均在请求值中表达；`HttpClient.send()`/`execute()`
才触发 I/O。`open_stream()` 与 `iter_sse()` 复用相同的 request-id、审计和调用方切面，
并在生成器结束、异常或显式 close 时释放连接。

## 调用切面

请求的固定顺序为：

```text
RequestId -> Audit -> caller interceptors（声明顺序） -> HTTPX transport
```

- `RequestId` 自动补充缺失的 `X-Request-Id`；不覆盖上游已经传入的值。
- `Audit` 只发布无 body、无敏感 header 的交换结果。没有 sink 时不做任何 I/O。
- 调用方 interceptor 可以改写请求、观测结果或短路返回缓存/降级响应；短路仍被 Audit
  观测。它们不得吞掉 `HttpError` 后伪造成功。
- 传输异常在 terminal transport 处映射为平台错误，不能由 interceptor 重新泄漏 HTTPX
  异常或对象。

## 已确认的模式与边界

用户已确认在此处预留切面。

| 位置 | 模式 | 为什么采用 | 防护 |
|---|---|---|---|
| `HttpClient` / `AsyncHttpClient` | Facade | 隐藏 HTTPX 生命周期和技术类型，暴露稳定的 HTTP 语义 | 不逐项转发 HTTPX API。 |
| HTTPX 映射层 | Adapter | 只在内部翻译 DTO、异常、资源关闭 | 没有第二 provider 和 provider SPI。 |
| invocation pipeline | Chain of Responsibility | 审计、OAuth header、追踪等横切能力可按固定顺序积累 | 顺序固定；短路、异常和无 sink 行为均有契约测试。 |
| 未来 retry policy | Strategy（暂不实现） | 仅当并发组件定义幂等和重试预算后才有独立变化维度 | HTTP P1 不重试 POST，不内置熔断/限流。 |

不采用 Singleton、Service Locator、Provider Factory、全局 interceptor 注册或 import-time
配置：这些会隐藏应用生命周期、污染测试或重新引入多 Provider 复杂度。

HTTPX client factory 是私有实现细节；组件测试可替换它来接入 HTTPX 官方受控 transport。
这不是公共 API、Provider SPI 或生产配置入口。生产代码始终使用组件构造的唯一 HTTPX
client。

## 安全与资源规则

- TLS 校验默认且不能由全局“trust all”开关关闭；测试显式使用受控 local transport。
- 默认不跟随重定向，防止敏感 Header 被无意转交；若以后开放，必须定义跨 origin header
  规则。
- `max_response_bytes` 在读取时强制执行并关闭连接；不会先把无限响应读进内存。
- Client 由应用显式持有并关闭；不得每个请求创建连接池，也不建立隐式全局 client。

完整风险与证据记录见 [HTTP 验收矩阵](docs/acceptance/http-component-test-matrix.md)。
