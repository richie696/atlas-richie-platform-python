# R-DASHBOARD 验证节奏拆分验收

日期：2026-10-09  
状态：**日常/里程碑入口已拆分；远程 GitHub Actions 尚未触发**

## 决定

- 同一逻辑切片完成后集中验证，不按文件重复跑回归。
- 日常开发优先运行受影响的 focused logic/HTTP tests、类型/格式检查与契约检查；不因每个改动触发完整回归。
- 日常 PR/push 只执行 `npm run check:fast`。完整前端 E2E 和真实端到端验收延至全部计划开发完成后的最终验收，不在中间里程碑重复执行。
- 期间的里程碑可运行 `npm run check:milestone`（非浏览器质量门禁）及该里程碑所需的后端定向/完整单测；这些不能代替最终 E2E。
- 最终浏览器旅程只通过 Codex 内置浏览器执行；不调用 Chrome、Edge 或 CDP。
- `check:milestone` 是完整非浏览器门禁，不等同页面 E2E。历史 `npm run test:e2e` 使用外部 CDP，不由日常或里程碑 CI 调用。

## 实施

- GitHub `pull_request` / `push` 运行 `check:fast`；移除每次 CI 运行时对 Chrome 的强制依赖和自动浏览器回归。
- 增加 `workflow_dispatch` 的 `fast` / `milestone` 选项，默认 `fast`；只有显式选择 `milestone` 才运行 `check:milestone`。
- 最终 E2E 是交付前的单独验收节点，不自动绑定到普通 PR/push 或中间 milestone。
- 同步 `AGENTS.md`、README 与 `docs/TESTING_CADENCE.md`；新增 cadence 守卫，防止日常或 milestone 非浏览器脚本重新接入 `test:e2e` / CDP。

## 验证

- `node --test tests/verification/cadence.test.mjs`：**3/3 passed**。
- Prettier 检查覆盖 cadence 测试、README、AGENTS、验证节奏文档与 workflow：通过。
- `git diff --check`：通过。
- 未运行 `check:milestone`、外部 CDP、Chrome/Edge 或浏览器 E2E；未触发远程 GitHub workflow。

## 边界

普通 PR/push 的 Actions 行为尚未由 GitHub 实际执行证明；本地守卫只检查工作流配置的触发/命令分层。最终 E2E 仍须覆盖 React→Python、数据库与配置中心真实链路；定向测试、`check:milestone` 或 mock 验收均不替代它。
