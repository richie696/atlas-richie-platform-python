# R-DASHBOARD-F4.32 本人改密冷却的 mounted 组件验收

日期：2026-10-12  
状态：**Happy DOM mounted 组件切片通过；真实浏览器与 live Console 仍待验收**

## 风险与证据

| 风险                                       | 检查                                                                                       | 证据                                                                                                           |
| ------------------------------------------ | ------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------- |
| 服务端 429 后页面仍允许再次点击            | 先让 session-bound workflow 返回带合成 `retryAfterMs` 的 429，再挂载正式 `OwnPasswordPage` | `tests/verification/own-password-cooldown-mounted.test.mjs` 断言真实表单提交按钮 disabled 且出现本地化冷却文案 |
| 冷却计时在到期后不恢复，或自动重试密码命令 | 推进注入的单调时钟并等待 mounted Hook 更新                                                 | 按钮到期后解锁；transport 调用次数仍为 1，证明只等待状态投影、未自动发送                                       |
| Hook 生命周期留下计时器                    | 观察 `window.setInterval` / `clearInterval` 生命周期                                       | 冷却期间仅有一个 timer；deadline 到达和组件卸载后均无遗留 timer                                                |

## 执行结果

在 `components/sentinel/dashboard-prototype` 执行：

```text
node --test tests/verification/own-password-cooldown-mounted.test.mjs
1 passed
```

测试使用 Happy DOM、React Strict Mode 和正式 `OwnPasswordPage`，账户、密码和服务端错误均为合成数据。没有提交真实凭证，也没有访问 Python Console 或持久数据库。

## 未覆盖边界

该用例是 mounted 组件测试，不是浏览器 E2E。它不证明真实浏览器键盘/焦点/自动填充行为、浏览器 URL/storage 泄漏扫描或 React→Python live Cookie/CSRF/数据库路径；这些仍需按最终 E2E 计划验收。全局 `npm run typecheck` 本轮受并行规则绑定工作区的类型错误阻塞：`src/features/rules/ui/RuleConsoleContainer.tsx` 传入 `receiptResource`，但接收组件当前 props 类型尚未声明该属性。该问题不在本人改密边界内，本记录不把 typecheck 记为通过。
