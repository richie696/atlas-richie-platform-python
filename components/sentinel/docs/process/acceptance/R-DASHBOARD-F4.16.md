# R-DASHBOARD-F4.16 配置中心登记 UI 验收

日期：2026-10-08  
范围：Dashboard 本地 demo HTTP/MSW 与 Codex 内置浏览器。不是 Python Console、真实 Nacos/Consul、数据库持久化或生产 Secret 管理验收。

## 验收结果

- [x] Connections tab 组合配置中心登记、连接健康探测及配置源注册表；探测显示结果、采集时间、有效期、延迟和能力。浏览器在线与后端链路状态彼此独立。
- [x] 新增表单支持 Nacos/Consul；Nacos namespace、Consul datacenter、Nacos 用户/密码、Consul ACL token 字段随 provider/auth mode 显示。
- [x] 认证支持凭证引用、直接录入、无需认证，不要求 KMS；新增连接默认无需认证，编辑已有连接默认保留既有凭证。
- [x] 读取与编辑已有连接不返回或回显密码、ACL token、凭证引用内容；注册表仅展示认证方式和凭证是否已配置。
- [x] 连接测试只执行独立只读检查；页面明确 demo 结果为模拟、不访问 Nacos/Consul、不修改规则，也不登记候选来源。字段改变使既有检查结果失效。
- [x] 连接测试异常与登记写入未知结果使用不同状态反馈；连接检查异常不应提示用户查询或重发一个并不存在的写操作。

## 内置浏览器证据

只使用 Codex In-app Browser，访问本机 `127.0.0.1:5183` Vite demo/MSW；未启动或连接 Chrome/Edge/CDP。

1. 系统管理连接页显示一条 Nacos demo source、探测成功状态、UTC `checkedAt` / `expiresAt`、12 ms 示例耗时与 read/conditional-write/watch 示例能力；未登记的指标服务、状态未知的 collector 均明确分开。
2. 新增对话框列出 Nacos 与 Consul，以及“使用凭证引用 / 直接录入凭证 / 无需认证”。没有强制 KMS 字段；reference 是不回显的标识，direct 字段按 Nacos 或 Consul 显示对应 write-only 录入项。
3. 从 Nacos direct 模式切换 Consul 后，字段切换为 Consul datacenter/ACL token；切换过程中不复用已录入秘密（本次没有输入或提交真实秘密）。
4. 关闭新建对话框，打开已有 Nacos source 编辑；显示“保留已有凭证”，原凭证值不在控件中，列表只显示“已配置凭证”。
5. 对现有 source 运行本地只读 demo 检查，看到成功、UTC 检查时间与能力列表。没有保存或修改登记/规则。

第一次在未重载的 HMR 页面执行检查时有一次泛化检查失败，重载后同一候选检查成功；HMR/transport 瞬态根因未证实。发现检查异常曾复用写入未知结果文案后，独立为“连接测试未能完成”文案；未通过制造外部服务故障来模拟失败态。

## 自动化验证

- `npm run typecheck`：通过。
- 目标 `eslint`、`prettier --check`、`npm run i18n:check`：通过，三语消息键一致。
- `npm run test:logic`：242/242 passed。
- `npm run test:http`：85 passed / 1 环境失败。失败项 `HTTP-LIVE-CONTROLLED` 需要绑定隔离 `127.0.0.1` listener，当前受限环境返回 `listen EPERM`；source registry/check/command/authorization 的 source HTTP/mock 用例通过。
- 未运行会启动 CDP 外部浏览器的 `npm run test:e2e`；以 IAB 当前路由交互作为本切片页面证据。

## 明确未验收

真实 Nacos/Consul 健康检查、Python Console API、关系库持久化、CSRF/SSRF 的生产部署路径、Secret/KMS/Vault 保护、条件写入并发及跨服务 E2E 均未验收。F4.16 的 checkbox 只表示前端管理 UI 与 demo mock 交互完成；F6.6 与最终整体验收仍未完成。
