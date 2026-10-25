# F7.2 远端降权后的管理员数据清理

日期：2026-10-12  
状态：受控 HTTP/workflow 合同通过；F7.2 整体仍开放。

## 风险与验证边界

管理员页面的本地权限投影来自已确认的 `/auth/me`。另一个管理员可在当前浏览器会话仍打开时撤销其管理员角色；此时首个管理命令可能收到 `403 forbidden`。若客户端继续信任旧快照，账户目录中的管理信息会继续留在已降权用户的页面状态中，即使服务端正确拒绝写入。

新增合同测试组合真实 `createConsoleAuthentication`、Console HTTP transport、账户 HTTP adapter、`AccountManagementWorkflow` 与 MSW 受控响应。先确认 admin 身份并读取合成账户目录；管理命令收到 `403 forbidden` 后，服务端 `/auth/me` 返回 view。断言客户端刷新到 view、撤销管理访问、清空缓存目录、后续列表调用在网络派发前拒绝，且被拒绝的写请求未重放。

修复前执行同一测试，观察到真实缺陷：期望 `view`，实际仍为 `admin`，测试失败。修复后该合同通过。账号管理仅在 `403 forbidden`（不包括 `csrf_failed`）后重新读取权威会话；写入不会因权限重读而重试。该行为复用现有会话 revalidation 能力，没有增加新的模式或基础设施。

## 定向验证

工作目录：`components/sentinel/dashboard-prototype`

```text
npm run test:http:focused -- 'F7[.]2-ROLE-REVOCATION'
1 passed, 0 failed
```

## 未覆盖范围

- 这是 MSW HTTP/workflow 合同，不是 Python Console live 授权或数据库持久化验收。
- 未验证浏览器挂载页面中的敏感目录隐藏与导航跳转，也未运行完整 E2E、Chrome、Edge 或 CDP。
- 本测试只证明账号管理命令收到规范的 `403 forbidden` 后收敛当前身份和清理账号目录；没有覆盖其它 feature 的所有远端权限撤销路径。
- 没有访问真实服务、数据库、配置中心，也没有提交或发布。
