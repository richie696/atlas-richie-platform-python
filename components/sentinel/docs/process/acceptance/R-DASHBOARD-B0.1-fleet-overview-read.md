# B0.1 Fleet Overview Read API

日期：2026-10-09  
状态：首个 Python Console 路由切片完成；B0.1 整体未完成

## 能力边界

实现 `GET /api/v1/fleet/overview` 的 Python ASGI 路由、不可变领域快照、应用读取用例、消费者拥有的 `FleetOverviewReader` Port 与 wire serializer。请求使用与前端 `readFleet` 一致的环境/应用/时间窗/页码/搜索/step 参数；实例或资源范围不属于 Fleet 页面查询，会被拒绝。

Fleet 总计数、关注应用计数、关注目标、当前页、每应用的六类指标、全局指标 bundle 和配置中心/Collector 健康是互相独立的 authority facts。页面页数据不得反推总数，缺样/未集成状态不得用 0 填充。领域快照验证查询回显、分页与总体计数边界、应用范围、指标名称/单位/时间窗、全局 MetricBundle 与读取时刻一致性、有限连接观察与有界集合。六类运营指标及其单位/denominator 统一由 observation domain catalog 定义。

Console 服务层只持有最小同步读取 Port。没有新增 GoF 模式：Factory/Strategy/Observer 等均不解决该同步读取用例；Port + use case + HTTP adapter 是现有分层边界，不额外增加通用抽象。`build_app` 允许部署组合显式注入 reader；缺失 reader 或权威不可用时返回安全 `503 service_unavailable`，不提供隐式 demo/fallback 数据。

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

Python 源码及关联测试的 88 列检查通过。没有运行全量前端/后端回归、里程碑 gate、浏览器 E2E 或真实外部服务。

## 未完成边界

- `build_app` 尚无生产 `FleetOverviewReader`；默认仍返回 503。无真实 inventory、telemetry/time-series 聚合、规则覆盖或 Nacos/Consul/Collector probe adapter。
- ASGI 合同测试的 telemetry reader 是隔离测试替身，只证明路由、权限、DTO 不变量及错误映射；没有 PostgreSQL/MySQL、Reporter/Collector 或浏览器→Python live 路径证据。
- 本切片使源码组合的 OpenAPI 路由数最多达到 19/42，不等于 19 项生产能力可用。

本项只更新 B0.1 的路由切片进度，不勾选 B0.1/F6.2/B0.4/B0.5。
