# F6.6 Mock 查询、命令状态与敏感值隔离

日期：2026-10-09  
状态：F6.6 完成；Mock 不代表生产持久化

## 验收合同

- 读取类 handler 按服务端 query 语义实际执行过滤、窗口与分页，并保持全范围统计和单页返回值分开。
- 写操作改变对应 handler factory 持有的可重置内存状态；相同幂等键+相同输入重放同一结果，handler factory 重建恢复 canonical seed，支持 reset 的规则/配置源模拟器清空操作 ledger 与派生状态。
- 账号 Mock 创建请求中的密码只用于短期命令指纹，不进入账号目录、命令回执或持久化浏览器状态。
- localStorage 只持有 `IdentityMockScenario.storageKeys` 明确列出的 bootstrap 状态、合成角色和故障注入开关；不会写入账号密码、配置源凭证或规则正文。

## 验证

- 新增 `ACCOUNT-MOCK-QUERY` 覆盖 active/disabled 过滤、规范化搜索及 page 1/2 边界。
- 新增 `ACCOUNT-MOCK-COMMAND-STATE` 覆盖 role/status 命令改变后续目录结果及重放幂等。
- 加强 `ACCOUNT-MOCK-ISOLATION`，以包含敏感合成密码的 create 命令后读取目录和 operation receipt，断言二者均不包含该密码；重建 handler 后目录恢复 canonical seed、历史 operation 不存在。
- `npm run test:http:focused -- 'ACCOUNT-MOCK-(QUERY|COMMAND-STATE|ISOLATION)'`：**3/3 passed**。
- `npm run test:http`：**106/106 passed**；最后两条 no-secret assertions 加入后，以上 focused tests 又 **3/3 passed**。
- `npm run check:fast` exit **0**；相关测试文件 Prettier 检查通过。

## 边界

上述状态是单浏览器 Mock profile 或一个 Node handler factory 生命周期，不证明多 worker/多进程共享、重启保存、Python Console、关系数据库或真实配置中心行为。完整页面 E2E 不属于此子切片，仍按 `docs/TESTING_CADENCE.md` 只在产品里程碑执行。
