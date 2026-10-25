# 本机 PG + Nacos 切换记录（2026-10-24）

## 范围与安全边界

复用已有 `postgres`（15432）与 `nacos-pg-3.2.3`（8848/9848），创建独立数据库/账号 `sentinel_console` 和独立 namespace `sentinel-console-local`。不修改其他数据库、namespace 或业务配置，不新增数据库/配置中心容器，不改变规则、身份或 wire 合同。

复用现有 SQLAlchemy 数据库适配器、Alembic 迁移、生产 managed-envelope codec 和 Nacos provider；不引入新业务设计模式。迁移脚本只承担本次运维切换，不进入核心依赖图。

原 MySQL 先做完整备份，保留原加密密钥、账号 hash、所有历史标识及数据。目标库先验证逐表行数和内容摘要，再改动当前来源/目标映射。历史发布和回执不得改写成 Nacos 成功事实。旧 Consul 是 dev 实例，已停止，其规则须核实能否恢复；若只能从最后成功的发布/快照恢复，记录恢复来源，不冒充当前配置中心读回。

运行状态与秘密保存在 `/Users/richie696/.local/state/atlas-richie-sentinel/`，目录 0700，秘密/备份 0600，不入库。保留原前端 57893、Console 57900、Collector 57903 端口和原身份密钥。TLS 使用受信本地 CA；不得关闭证书或主机名校验。共享 PG 增加 TLS 支持时保留现有非 TLS 客户端兼容，不强制重启。Nacos 如需 TLS 终结，使用 loopback 本机转发进程，不更改共享 Nacos 的现有入口。

## 顺序与验收矩阵

| 顺序 | 风险 | 验证与关闭条件 |
| --- | --- | --- |
| 1 | 丢失现有数据/密钥 | MySQL 完整备份、45 表盘点、运行密钥备份；未删旧容器 |
| 2 | 覆盖共享资源 | 专用数据库/账号及 namespace 不冲突；只写专用目标 |
| 3 | 跨数据库类型/时区漂移 | 以生产模型读取、PG 官方迁移创建结构；逐表行数与规范化摘要全部一致 |
| 4 | 规则与 binding 错配 | 保留 binding_id/kind/profile；恢复载荷与已存摘要一致；Nacos 独立读回；fail-closed 校验通过 |
| 5 | 假成功/历史重写 | 旧发布/审计完整保留；新发布由 Console 产生新身份；独立确认回读和 Runtime 加载/限流 |
| 6 | 登录/页面不可用 | 原账号可登录；浏览器查看规则、版本、系统连接；仍保留文档公开入口 |
| 7 | 清理过度 | 仅删除确认不再引用的 Sentinel MySQL/Consul/过期 bridge/demo 容器；保留共享 PG/Nacos/Redis、监控链路和备份 |

此次为本机依赖切换的定向验收，不重跑已关闭的全量测试，不重新执行 setup 或重置管理员密码。验证未完成不得清理旧数据源。

## 执行结果

### 已完成

- PostgreSQL：复用 `postgres` 容器的 `127.0.0.1:15432`，新建 `sentinel_console` 数据库及同名非超级用户账号。原有 `sentinel_control`、`nacos_config` 等数据库未覆盖。通过配置 reload 增加 TLS 支持，没有重启共享 PG，也没有要求原有客户端立刻启用 TLS。
- Nacos：复用 `nacos-pg-3.2.3`，新建 namespace `sentinel-console-local`，group `SENTINEL_GROUP`，Data ID `sentinel-rust-demo-flow-rules.json`。按 [Nacos 3 Admin API](https://nacos.io/en/docs/latest/manual/admin/admin-api/) 创建独立 namespace，没有修改 public/development/lite 等既有配置。
- Console 通过本机 loopback TLS 转发 `https://127.0.0.1:9443/nacos` 连接共享 Nacos HTTP 服务，gRPC TLS 10443 转发到 9848。两个监听只在本机开放；使用完整 CA/主机名验证，没有关闭 TLS 校验，没有增加桥接容器。
- 按生产模型迁移 44 张业务表、1 张 Alembic 版本表；结构版本一致，1,243 条业务记录逐表行数及规范化 SHA-256 全部一致。规范化只消除 MySQL naive UTC 与 PG aware UTC 的表达差异，不改时间含义。原管理员密码哈希、原始会话、身份密钥及历史版本/审计/指标均保留。
- 原 Consul 已停止且为 dev 模式，未将空结果当作权威空规则。根据最后成功发布 `ffae1abb-1e8e-4cc4-ba96-5a0d8190cc7e` 与不可变版本恢复原生载荷；SHA-256 与原记录完全相等：`6b098bb495150ecccf869cc92c0845c5dcb3dd73799a74889ef9258d0102b42b`。通过生产 codec 重建 managed envelope，Nacos create-only 写入并独立读回逐字节一致。
- 保留 binding `t07-rust-e2e-cfc322879fa1`、kind `flow`、profile `sentinel-rust-v1`；新增来源 `sentinel-local-nacos`，只重映射当前 binding、发布目标及草稿的物理基线修订。恢复后执行正式 Console 发布，未将旧发布阶段改写成新 Nacos 成功事实。旧 Consul 来源在不再被当前绑定引用后，通过正式删除命令关闭，并保留审计与幂等回执。
- 新发布 `a28fe176-1307-496d-b401-abc8a5bb7046`，序号 3：校验、Nacos gRPC CAS 写入、独立回读均 succeeded；Runtime 上报 applied 回执，当前加载观察 current、预期 1 / 观察 1、完整成员清单。10 次真实业务请求返回 `200,200,200,429,429,429,429,429,429,429`。
- 原账号通过真实 HTTP 和内置浏览器登录成功；规则目录、快照、版本、发布目标、发布历史、系统来源、加载观察读通。浏览器确认规则使用数为 1，并显示新 namespace 与精确 Nacos 目标。
- 收尾发现原 Collector/Reporter CA 与叶证书仅有一天有效期，将于 2026-10-25 到期。本轮保留原 CA 私钥、客户端私钥、principal、Reporter ID、环境/应用/实例/进程作用域，重新签发一年有效期的本机证书（截至 2027-10-24）。现有 `metrics-reporter enroll` CLI 只接受完全相同的重试，不支持证书轮换；因此作为本次受控运维迁移，以原指纹及 principal 为 CAS 条件更新唯一 enrollment 的新证书指纹，并记录 `deployment.reporter_certificate_rotated` 审计，未新增角色或扩大作用域。这不是新增产品轮换 API。重启 Collector 与原 Rust 容器后，真实 mTLS 指标继续入库，加载观察为新进程 epoch、applied/current；PG 活跃连接的 `pg_stat_ssl.ssl` 均为 true。

### 最终运行与审查入口

| 服务 | 运行位置 | 地址 |
| --- | --- | --- |
| React 开发前端 | 本机 Node | `http://localhost:57893` |
| Python Console | 项目本机 `.venv` | `http://127.0.0.1:57900` |
| Python Collector | 项目本机 `.venv` | `https://127.0.0.1:57903`，mTLS |
| Nacos TLS 本地转发 | 本机 Python，仅 loopback | 9443、10443 |
| 共享 PG / Nacos / Redis | 用户现有容器 | 15432 / 8848、9848 / 16379；Redis 不是 Console 依赖 |
| Rust 业务演示 | `sentinel-local-rust-demo` | `http://127.0.0.1:60114/api/hello`；`/rules` 查看加载事实 |

本机服务的启动/状态入口：`/Users/richie696/.local/state/atlas-richie-sentinel/manage-local.py`，支持 `start` 与 `status`。前端仍使用源码开发服务，未发布到 pip、未重建 Docker 应用镜像。原账号密码不变；凭证不写入本文。

### 已清理与保留

删除 6 个不再使用的测试容器：原 MySQL、原 Consul、原 Rust demo、旧 Nacos TLS bridge、`sentinel-t054-prometheus` 和 `sentinel-t054-node-exporter`。没有执行全局 prune，也没有删除共享服务或镜像。原始数据库备份、容器元数据和旧数据卷保留作为回滚材料。

当前迁移库原本就没有配置主机监控源或主机关联（两表均为 0）；本轮未额外创建监控源或把缺测伪装为监控正常。应用 Reporter 指标链路已恢复，用户已有的独立 Prometheus/Grafana 栈未修改、未删除。主机监控如需启用，应登记现有 Prometheus 查询服务。

私有证据位于上述 state 目录：`migration-20261024/database-copy-verification.json`、`cutover-verification.json`、`source-finalization.json`。MySQL 原始导出、保留密钥和运行配置均 0600，所在目录 0700。它们含敏感运维材料，不纳入 Git。

内置浏览器截图：同目录 `screenshots/rules-after-cutover.png` 与 `screenshots/system-after-cutover.png`。最终只保留一个已登录的规则审查标签页；Python 服务、本地 TLS 转发、前端和 Rust 演示仍运行。
