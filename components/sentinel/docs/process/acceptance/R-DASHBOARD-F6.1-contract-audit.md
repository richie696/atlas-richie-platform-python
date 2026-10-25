# F6.1 Console API 合同冻结验收

日期：2026-10-13  
冻结版本：Console API wire **0.4.0**  
批准人：产品 owner（用户明确批准当前版本冻结）

## 冻结范围

- 仅冻结 `CONSOLE_API_CONTRACT.md` §9 与生成的 `protocol/console-api.openapi.json` 中当前 wire：**44 paths / 45 operations**、**94 exchanges / 121 media examples**。
- 不修改 endpoint、DTO、错误码、权限、时间、分页、幂等或 schema；历史 §0–§8 不再是规范入口。
- OpenAPI `info.version=0.4.0`、`x-contract-status=frozen`。冻结不等于已发布，也不代表 Python 全部实现、生产部署或 React→Python E2E 已通过。
- 0.4.0 生成物 SHA-256：`14b105770aac930b48d558526f23559ee443b0d3530b213e3112f344653c480b`；machine test 锁定该 fingerprint，任何 wire 或生成物变更必须显式评审并推进合同版本。

## 防漂移门禁

| 检查 | 门禁 | 当前结果 |
| --- | --- | --- |
| Runtime contract registry 与生成 OpenAPI 一致 | `npm run contract:check` | 通过，44 paths |
| OpenAPI 冻结状态/版本、批准记录与 0.4.0 fingerprint | `npm run test:http:focused -- 'CONSOLE-MACHINE|F6\.1|F7\.4|MOCK-OPERATION-COVERAGE'` | 34 passed |
| Python 读取 OpenAPI 的冻结元数据与合同文档对齐 | `uv run --project . --extra test pytest -q tests/test_console_openapi_route_parity.py` | 通过 |
| 页面 operation/access/error/Mock 映射 | `npm run test:http:focused -- 'F6\.1|F7\.4|MOCK-OPERATION-COVERAGE'` | 27 passed |
| Python route/method 与 runtime response contract | `uv run --project . --extra test pytest -q tests/test_console_openapi_route_parity.py tests/test_openapi_runtime_response_coverage.py` | 32 passed（含冻结元数据断言） |

## 结论与边界

产品 owner 已批准当前 Console API wire 版本冻结，自动门禁锁定状态、版本和文档批准记录；后续 wire 修改必须通过显式合同版本演进，而不能静默改写 0.4.0。历史记录中“草案/待签字”状态是冻结前快照，不覆盖本验收结论。

本冻结关闭的是合同定义与签字，不关闭 B0.1/B0.2/B0.3/B0.4、其他前端页面实现或 B0.5 最终真实 E2E；生产数据库、配置中心、真实 Python 服务和浏览器全流程仍需按总清单验收。
