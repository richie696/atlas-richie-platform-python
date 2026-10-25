# Dashboard 验证节奏

## 目标

按变更风险选择最小充分证据。一个逻辑完整的改动切片验证一次；不要因编辑了多个文件而逐文件重复跑回归。完整浏览器旅程只在全部计划实现完成后的最终验收执行；日常提交和中间里程碑不启动 E2E。

## 日常改动

1. **不要在每次编辑或每个文件改动后回归。** 先完成同一职责边界内的一组改动，把它作为一个验证切片。
2. 对这个完整切片运行一次 `npm run check:fast`，覆盖 TypeScript、格式、lint 与 OpenAPI 生成物一致性。
3. 再只运行受影响的逻辑或 HTTP 用例：

   ```sh
   npm run test:logic:focused -- 'SETUP-(SHAPE|VALIDATE|SECRET)'
   npm run test:http:focused -- 'BOOTSTRAP-(HTTP|ACK)'
   ```

   实际 pattern 应按本次改动选择；runner 找不到匹配测试、或目标测试文件未登记到对应 suite entry 时均以非零状态退出，不允许将空跑/未执行目标测试算作通过。

4. 如果变更跨越 feature、共享 transport、权限/会话所有权或公共 DTO，再把对应逻辑/HTTP 测试扩展为完整套件；只有受影响边界需要升级，不自动升级到全部 E2E。
5. 纯文档改动不跑应用构建或回归，只做链接、命令、状态事实核对和 `git diff --check`。

### Python Console 切片

同一 Python 职责切片完成后，在 Console 包目录运行其相关测试；不要因为同一切片中改了多个 Python 文件而重复跑整套测试：

```sh
PYTHONPATH=components/sentinel/sentinel-console/src \
  .venv/bin/pytest -q components/sentinel/sentinel-console/tests/test_<受影响能力>.py
```

只有跨越共享身份/持久化/路由组合边界时，才把测试扩展到受影响的相邻能力。临时 SQLite、ASGITransport 和 mock authority 属于定向单测/集成证据，不是生产数据库或真实部署 E2E。

## 页面改动验证

可见行为、布局、键盘/焦点或导航改动，开发期间用受影响组件/逻辑测试、DOM 断言和静态规则验证，不启动浏览器 E2E。最终验收时再用 Codex 内置浏览器执行完整用户旅程，记录实际路由、操作、可见结果与失败范围；它不能单独证明 Python 服务、数据库或配置中心已联调。

## 最终验收

**完整浏览器 E2E 只在全部计划实现完成后的最终验收执行**；中间里程碑和普通小改动都不启动完整 E2E：

1. 运行 `npm run check:milestone`。它等价于 `check:full`，执行完整非浏览器门禁、生产/Demo 构建、构建隔离和 Sites 检查。
2. 使用 Codex 内置浏览器，按最终验收清单跑完整用户旅程，并记录真实页面断言。不得启动 Chrome、Edge 或 CDP。
3. 运行隔离后端/协议测试与真实前后端验收；MSW、fixture、静态检查和浏览器 mock 都不能代替真实服务证据。
4. 记录命令、通过/失败数、浏览器路径和未覆盖边界。没有执行的层级明确写“未运行”，不得从中间切片或里程碑的结果继承通过结论。

`npm run check:milestone` 本身不包含页面 E2E；`npm run test:e2e` 使用外部 CDP 浏览器，不是本项目允许的浏览器入口。只在最终验收使用 Codex 内置浏览器；不能把脚本状态或单测结果混称为 IAB 验收。

GitHub Actions 的普通 PR/push 只运行 `check:fast`；手动 workflow dispatch 默认仍为 `fast`，只有显式选择 `milestone` 才运行 `check:milestone`，避免误触发完整回归。完整浏览器旅程不绑定中间 milestone，留至全部计划实现完成后的最终验收。

## 何时扩大验证范围

| 变更                           | 最低验证                            | 需要扩大时                                              |
| ------------------------------ | ----------------------------------- | ------------------------------------------------------- |
| 纯文档                         | diff / 链接与事实核对               | 文档生成器或发布脚本改变时跑对应工具测试                |
| 单一领域纯逻辑                 | `check:fast` + 相关 focused logic   | 领域状态/共享策略改变时跑完整 logic                     |
| 单一 HTTP adapter/mock handler | `check:fast` + 相关 focused HTTP    | transport、身份或多个 feature 共用合同改变时跑完整 HTTP |
| 单页 UI/CSS                    | `check:fast` + 相关交互/DOM 测试    | 浏览器页面旅程留至最终验收                              |
| 共享架构/公共协议/构建管线     | `check:milestone` + 对应静态/单测   | 全部实现完成后跑完整浏览器旅程                          |
| Python Console 与前端跨层      | 两端定向测试 + 本地真实服务协议验证 | 全部实现完成后跑真实跨层 E2E                            |
