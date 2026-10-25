# R-DASHBOARD-F4.23 注销与旧请求 owner 竞态（受控 HTTP 切片）

## 范围与风险矩阵

本记录只验证注销时并发的旧权限请求，不关闭 F4.23，也不替代 React mounted 到 Python 的最终验收。

| 场景 | 需要保持的安全性质 | 证据边界 |
| --- | --- | --- |
| 已认证 owner 发起受保护读取；随后显式注销成功；旧读取最后才返回 `401 unauthenticated` | 旧请求的 401 不得撤销注销后确认的匿名状态，不得覆盖注销命令成功结果 | 本地 MSW 受控 HTTP，使用正式认证组合、Console transport 与账户读取 HTTP adapter |
| 旧响应的请求/响应关联标识不匹配 | 响应不得被认作该命令/读取的有效响应 | 本切片让受控 handler 精确回显各自 request ID；错误关联 DTO/响应头由通用 transport 测试另行覆盖 |
| 注销已派发但客户端网络结果未知 | 不自动重放写命令；必须明确检查当前 session | 既有 logout/command 逻辑测试覆盖；本切片没有模拟网络中断 |

## 实现与观测

- 新增 `tests/http/authenticationLogoutOwnerRace.test.mjs`，将一个账户读取挂起，完成注销和匿名 `/auth/me` 回读后，再释放旧读取的 401。
- 捕获账户读取与注销各自的 `x-request-id`，断言 ID 独立、handler 响应回显匹配 ID，且拒绝错误携带账户读取自己的 request ID。
- 旧 401 被保留为该读取的确定性 `unauthenticated` 错误；注销命令仍为 `success`，session 仍为服务端确认的匿名。没有旧身份被恢复，也没有额外写请求。
- 未复用真实浏览器动作，未清理或修改浏览器状态；未连接 Python 服务、数据库或配置中心。

## 验证

在 `components/sentinel/dashboard-prototype` 执行：

```text
npm run test:http:focused -- 'AUTH-LOGOUT-OWNER-RACE'
```

结果：**1 passed**。这是应用组合 + 受控 HTTP 的定向自动化证据，不是 mounted 页面或部署态验收。完整 E2E/Chrome/Edge/CDP 均未运行。

## 结论

当前 owner 防护在该确定性竞态中有效，未复现需要修改生产代码的前端缺陷。此前 IAB 中 unknown logout 的具体 dispatch/response 根因仍不能由这个测试倒推；既往 unknown 结果保持未解释，F4.23 继续开放。
