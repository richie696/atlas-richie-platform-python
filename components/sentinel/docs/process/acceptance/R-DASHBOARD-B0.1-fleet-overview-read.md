# B0.1 Fleet Overview Read API

日期：2026-10-16
状态：Fleet overview SQL read-model 已实现并接入正式 SQL composition；SQLite、PostgreSQL、MySQL 定向读回通过；B0.1 整体未完成

## 能力边界

实现 `GET /api/v1/fleet/overview` 的 Python ASGI 路由、不可变领域快照、应用读取用例、消费者拥有的 `FleetOverviewReader` Port 与 wire serializer。请求使用与前端 `readFleet` 一致的环境/应用/时间窗/页码/搜索/step 参数；实例或资源范围不属于 Fleet 页面查询，会被拒绝。

Fleet 总计数、关注应用计数、关注目标、当前页、每应用的六类指标、全局指标 bundle 和配置中心/Collector 健康是互相独立的 authority facts。页面页数据不得反推总数，缺样/未集成状态不得用 0 填充。领域快照验证查询回显、分页与总体计数边界、应用范围、指标名称/单位/时间窗、全局 MetricBundle 与读取时刻一致性、有限连接观察与有界集合。六类运营指标及其单位/denominator 统一由 observation domain catalog 定义。

Console 服务层只持有最小同步读取 Port。生产 SQL composition 默认装配 `SQLAlchemyMetricsFleetOverviewReader`：应用范围来自当前环境内未撤销、具备当前 epoch 且至少收到过一次 Metrics V2 快照的 Reporter；指标值复用既有 `MetricsReader`，并发读取有界为 8。无已观测应用时返回权威空目录和 `NO_SAMPLES` 指标，不合成应用或零值。应用 health 与 rule coverage 保持 unknown，连接事实集合为空：Reporter freshness 不是应用健康检查，Metrics V2 也不是规则回执/配置源探测。数据库/指标 authority 故障仍返回安全 `503 service_unavailable`，不提供 demo/fallback 数据。

没有新增 GoF 模式：这是既有消费者 Port 的 SQL Adapter 实现；不引入额外 Factory/Facade/Template Method/Strategy/Observer，也不更改 HTTP wire。

## 风险与验证矩阵

| 风险                                                 | 证据                                                 | 结果         |
| ---------------------------------------------------- | ---------------------------------------------------- | ------------ |
| 全局应用计数被当前页替代、分页回显错配               | Domain invariants + ASGI 正常响应断言                | 通过         |
| 未登录访问或查看权限边界遗漏                         | admin/view 正常读取；anonymous 在调用 reader 前拒绝  | 通过         |
| 参数缺失/未知/重复/越界或错误 scope                  | ASGI query rejection 用例；reader 调用数为 0         | 通过         |
| telemetry authority 缺失/失败细节泄漏                | 缺省 reader 与 typed unavailable 均映射到无细节 503  | 通过         |
| 已知目标缺失或限流错误映射漂移                       | `not_found` / `rate_limited` 与 Retry-After 毫秒断言 | 通过         |
| authority 返回另一查询的数据                         | Use Case 校验查询回显，ASGI 映射为安全 503           | 通过         |
| 修改公共 app composition 影响既有 observation routes | Fleet、目录、实例/指标 API 关联测试                  | 26/26 passed |
| 空 Reporter 目录被错误显示为 503 或虚构零指标 | 真实 SQLite migration + SQL adapter 集成测试 | 通过 |
| Reporter 撤销、未建立 epoch、从未上报或跨环境造成伪应用 | 真实 SQLite reporter-binding 数据读回 | 通过 |
| 搜索过滤篡改 whole-scope 总数 / 失联 Reporter 仍算新鲜 | 定向 SQLite query cases | 通过 |
| Fleet 目录查询在 PostgreSQL/MySQL 方言下的迁移、插入、聚合与真实 SQL 读回 | 各自 disposable loopback SQL wrapper + `SQLAlchemyMetricsFleetOverviewReader` | 通过 |

实际命令：

```sh
PYTHONPATH=src .venv/bin/pytest -q \
  tests/test_fleet_overview_api.py \
  tests/test_observation_catalog_api.py \
  tests/test_instance_catalog_api.py
PYTHONPATH=src .venv/bin/python -m compileall -q \
  src/atlas_richie/sentinel_console \
  tests/test_fleet_overview_api.py \
  tests/test_instance_catalog_api.py
```

实际命令（2026-10-16）：

```sh
uv run --extra test pytest -q \
  tests/test_metrics_fleet_overview_reader.py \
  tests/test_fleet_overview_api.py \
  tests/test_identity_composition.py
# 21 passed
uv run --with ruff ruff check \
  src/atlas_richie/sentinel_console/infrastructure/persistence/metrics_fleet_overview_reader.py \
  src/atlas_richie/sentinel_console/infrastructure/persistence/identity_composition.py \
  tests/test_metrics_fleet_overview_reader.py \
  tests/test_identity_composition.py
uv run --with ruff ruff format --check \
  src/atlas_richie/sentinel_console/infrastructure/persistence/metrics_fleet_overview_reader.py \
  src/atlas_richie/sentinel_console/infrastructure/persistence/identity_composition.py \
  tests/test_metrics_fleet_overview_reader.py \
  tests/test_identity_composition.py
```

涉及 Python 文件的 `compileall` 通过。验证基于 SQLite disposable DB；未跑 PostgreSQL/MySQL 方言、全量前后端回归、浏览器 E2E 或真实外部服务。

PostgreSQL/MySQL 方言定向验收（2026-10-16）：

```sh
./tools/with_disposable_postgresql_acceptance.sh \
  uv run --extra test pytest -q tests/test_metrics_fleet_overview_dialect_acceptance.py
# 1 passed
./tools/with_disposable_e2e_dependencies.sh \
  uv run --extra test pytest -q tests/test_metrics_fleet_overview_dialect_acceptance.py
# 1 passed (MySQL 8.4.11; wrapper 同时提供临时 Consul，本测试不访问 Consul)
```

验收测试只接受 wrapper 发放的随机 `sentinel_console_test_*` 数据库名、loopback host/port 与配套环境变量；直接运行会跳过，遇到其他数据库 URL 会拒绝。每次运行只写入合成 Reporter binding，验证迁移、非空环境目录、上报覆盖数、无样本指标和空环境目录。两个 wrapper 都清理了本次创建的容器；本轮只核验并移除了各自 run-owned 容器，没有触碰另一个仍在运行的既有测试 wrapper 资源。

## 未完成边界

- 没有独立的业务应用 inventory authority：总数是已接收 Reporter 覆盖到的应用数，`coverage.expected` 明确 unknown，不代表部署平台的全部应用。无 Reporter 的环境返回 0 个已观测应用，而不是声称系统完整清单为空。
- `rule_coverage`/应用 health/连接 health 尚无对应权威源，保持 unknown/空集合；不能把此实现解释为 T03.3 规则回执或 Nacos/Consul/Collector 探测闭环。
- ASGI 合同测试的 telemetry reader 是隔离测试替身，只证明路由、权限、DTO 不变量及错误映射；数据库方言测试不代表 Reporter/Collector 或浏览器→Python live 路径。
- PostgreSQL/MySQL 与 SQLite 结果都是 SQL Adapter 定向集成，不等于 React→Python 浏览器 live E2E。

本项只更新 B0.1 的路由切片进度，不勾选 B0.1/F6.2/B0.4/B0.5。
