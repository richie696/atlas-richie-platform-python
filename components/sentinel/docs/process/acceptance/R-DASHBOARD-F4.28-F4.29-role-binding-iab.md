# R-DASHBOARD-F4.28 / F4.29 角色绑定与草稿状态 IAB 验收

日期：2026-10-08  
状态：部分完成；F4.28、F4.29 均不勾选  
范围：本地 dashboard demo + Codex 内置浏览器；无真实 Console、数据库或 Python 服务

## IAB 验收记录

- 直接打开 `#/roles?account=account-view`，选择器显示 `viewer`，详情显示启用状态及 `view` 角色；再通过选择器改选 `admin`，URL 同步为 `#/roles?app=all&range=1h&account=account-admin`，详情随目标切换，内置账号角色选项为 disabled。
- 直接打开 `#/roles?account=does-not-exist`，选择器保持“选择…”，详情显示“未找到账号；不会自动选择其他账号”，没有回退到 admin 或 viewer。
- viewer → admin 的 Radio 选择只将 Save/Discard 控件置为可用；没有提交保存。尝试切换目标账号时出现未保存确认；选“继续编辑”保留 viewer 草稿与 URL。
- 通过路由离开时明确选择“放弃更改并离开”，再回到 viewer 深链，页面重新读取并显示已保存的 `view` 角色，两个草稿按钮 disabled。该过程未确认角色变更或修改 mock 账号数据。
- 同标签调用 IAB reload 后曾观察到 Radio 仍显示本地 admin 草稿（Save/Discard 仍可用）；点击“放弃修改”后数据回到 viewer/view。与新标签初始状态、路由卸载重入结果不一致，故将 IAB reload 的草稿恢复语义记录为待确认，不推断其为业务持久化或实现缺陷。

## 自动化与边界

- `npm run test:logic`：**253/253 passed**。现有导航逻辑测试确认显式无效 `account` 目标保持原值；账号模型测试确认角色仅为 `admin` / `view`、草稿独立于基线 revision，受保护账号不允许静默改角色。
- 当前 demo 目录只有 active viewer/admin；本轮没有把账号改为 disabled，也没有清空账号目录。因此 disabled / 空列表 UI 的显式反馈尚未验证。
- 本轮只用 Codex IAB，没有调用 Chrome、Edge、CDP；也没有访问真实后端、数据库或配置中心。页面显示为 Mock/demo，不证明持久化、并发 revision 或服务端权限。

## 收口条件

- F4.28：还需在无破坏性/可重置 fixture 下验证 disabled 与空目录状态，以及刷新后显式目标与详情的一致性。
- F4.29：还需明确/验证真实硬刷新时本地草稿的预期生命周期，并覆盖保存成功、pending/unknown、revision conflict 与目标会话失效提示。本次“切 radio 不立即保存”和未保存账号切换确认已观察，但不足以完成整项。

## 2026-10-12 IAB 增量复验

- **环境：**Codex 内置浏览器访问 `http://127.0.0.1:5174/#/system?env=test-env&app=all&range=1h&account=account-view&view=roles`。页面明确提示为演示数据；没有连接 Python 服务、数据库或配置中心。
- **动作与结果：**Viewer 当前绑定 `view`。选择 `admin` radio 后，URL 未变，Save/Discard 变为可用；未保存时尝试切换到 `admin` 账号触发统一离页确认。点击“留在当前页面”后仍选中本地 `admin` 草稿，`viewer` 目标和原 URL 均保留。再点“放弃修改”，radio 恢复 `view`，Save/Discard 禁用。全程没有提交角色命令；示例数据保持原角色。
- **结论与边界：**补充证明 mounted 的本地角色草稿、切目标保护、取消保留与显式丢弃恢复；它不覆盖保存/unknown/revision conflict、硬刷新草稿寿命或 Python live authority。因此 F4.28/F4.29 仍保持未完成，主清单计数不变。

### 2026-10-12 主开发端口筛选与硬刷新复验

- **目录筛选：**在 5173 的 admin 会话中，角色目录搜索 `viewer` 返回 1 个账号；搜索一个无匹配值时页面显示“读取失败”，显式重试后仍未恢复。随后硬刷新恢复完整两行目录、URL 目标 `account-view`、viewer 详情与已保存 `view` 角色。该无匹配结果不是 filtered-empty 正向验收，反而留下一个 Mock/mounted 查询异常待查。
- **硬刷新草稿：**以 `viewer/view` 为基线将 radio 暂选为 `admin`，Save/Discard 启用；未保存即整页刷新，页面仍选中 `admin` 且按钮保持启用，说明当前 mounted 实际保留该草稿。随后显式“放弃修改”，恢复 `viewer/view` 且两个按钮禁用。未调用保存接口。
- **边界与结论：**硬刷新行为已观察，但其持久化来源/产品预期仍未冻结；无匹配筛选、disabled/空目录、真实分页、保存回执、冲突/unknown 和 live Python 均未验收。F4.28/F4.29 均保持开放。
- **后续对照：**`ACCOUNT-LIST` workflow **3/3**、`ACCOUNT-SEARCH` HTTP **1/1**、`I18N-ROLE-DIRECTORY-TARGET` 实际三语 SSR **1/1** 均通过，其中 SSR 确认 filtered-empty 保留 URL 目标选择器。它们证明模型/HTTP/schema/render 合同，不覆盖本轮 IAB 无匹配查询时的 mounted 读取失败。

### 2026-10-12 最终定向 mounted 复验（F4.28）

- 新建 Codex IAB 标签的本地 Mock 页面中，选择 viewer 后 URL 含 `account=account-view`，详情明确显示 viewer/view。搜索无匹配值后，目录显示“没有符合筛选条件的账号”，但 viewer 仍留在目标选择器中，URL 和角色详情不变；本次未复现先前记录的“读取失败”。
- 经账号维护页临时停用 viewer 后返回同一目标角色页，页面显示“该账号已停用，不能修改其角色”，两个 radio 与保存/放弃操作均 disabled；随后通过确认启用恢复了本地 Mock viewer 的启用基线。
- 结合前述 viewer/admin 深链、无效 account 不回退、账号选择与 URL/详情同步、仅 admin/view 角色选项及定向 logic/SSR，F4.28 的前端页面合同已完成并在主清单勾选。此项不证明 Python live UI 或全部浏览器响应式矩阵；这些仍由 B0.5/F5.4/F5.5 承担。
- F4.29 仍开放：刷新时本地草稿的预期寿命尚未冻结，且 save/pending/unknown/revision-conflict/owner失效完整路径未通过 mounted 验收。本次未保存角色变更。

### 2026-10-12 保存成功与恢复基线 mounted 复验（F4.29）

- **环境：**Codex IAB `http://localhost:5173`，显式本地 Mock；进入前会话为 viewer。没有访问 Python Console、数据库、配置中心或真实身份服务。
- **保存路径：**admin 选择目标 viewer，将 radio 从 `view` 切到 `admin` 后只形成草稿；点击 Save 后页面明确显示服务端确认且刷新当前读取，详情选中 admin、Save/Discard 禁用。整页 reload 后仍从 Mock authority 读回已保存 admin。
- **清理/恢复：**为恢复测试前账号基线，将目标 viewer 再保存回 `view`，reload 后 radio 仍为 view 且两个操作 disabled；退出 admin 测试会话并恢复原 viewer Mock 会话。无待处理角色草稿。
- **结论与边界：**补齐 mounted Mock 的保存成功、统一刷新及保存后重载读回正向证据。pending/unknown、revision conflict、读回失败时保留冲突、目标会话失效和 Python live 权威仍未验证；刷新时**未保存本地草稿**的实际寿命仍待产品合同裁定，因此 F4.29 保持开放。
- **工具边界：**没有运行完整 `test:e2e`，没有调用 Chrome、Edge 或 CDP。

### 2026-10-12 未保存角色草稿刷新生命周期实现

- **当前前端规则：**dirty role draft 在同一浏览器 tab 与同一已认证 `sessionEpoch` 中跨硬刷新保留；快照只包含 schema version、目标 account ID、起始 revision、起始角色和选择角色，不写账号名、凭证或其他会话事实。它按 session epoch 与目标 account ID 分键，目标详情权威读取后才恢复。硬刷新期间编辑器先保持锁定，恢复失败/损坏/超限数据不影响服务端角色事实。
- **冲突规则：**恢复后仍以原起始 revision 为基线；若权威详情 revision 已变化，保留 dirty draft 并显示现有冲突提示，不能静默把 baseline 推进到新版本。取消、明确读取最新、成功保存后清除对应草稿快照；浏览器拒绝 sessionStorage 时继续内存编辑，不阻塞角色功能。
- **自动化证据：**新增 strict snapshot、错误账号/session 隔离、旧 revision 保持、schema/role/key 负例、损坏/超限快照清理与 storage 故障降级测试；`ROLE-` 聚焦逻辑 **13/13 passed**，`typecheck`、ESLint 通过。
- **mounted 限制：**尝试以 IAB 打开临时角色草稿探针时只渲染空页面，未取得组件交互证据；临时探针已移除，隔离标签恢复到 login。没有访问真实 Console、数据库或 Python 服务，也没有运行完整 E2E/Chrome/Edge/CDP。因此这只是明确 F4.29 刷新策略并完成前端状态恢复实现，不关闭 F4.29；待最终验收仍包括 mounted hard-refresh/冲突、pending/unknown、读回失败、会话失效与 Python live 权威。

### 2026-10-12 隔离 IAB 硬刷新草稿恢复与显式丢弃复验

- **环境：**使用独立本地 Vite 端口 `127.0.0.1:5197` 与 Codex 内置浏览器新标签，避免触碰既有 `localhost:5173` 会话和保留的未知注销标签。页面明确处于本地 Mock 模式；仅使用合成 `admin` 身份与测试口令，没有访问 Python、数据库或配置中心。
- **硬刷新恢复：**进入角色绑定页，目标为 `viewer/view`；仅选择 `admin` 后整页 reload。重载后目标仍为 viewer，`admin` radio 仍选中且保存/放弃操作保持可用，证明未提交草稿在同一标签/认证 epoch 内恢复。本次未点击保存。
- **显式丢弃：**点击“放弃修改”后，`view` radio 恢复选中、保存/放弃操作禁用；再次 reload，页面仍为干净的权威 `viewer/view` 基线，证明取消会清除草稿快照，而非只隐藏 dirty 状态。
- **结论与边界：**补齐 dirty draft 硬刷新恢复与取消后跨刷新清理的 mounted Mock 证据，和 §15.967 的实现/聚焦测试相互补充。没有验证刷新后服务端 revision 变化时的冲突 UI、保存 pending/unknown、权威读回失败、身份 owner 失效或 Python live authority；F4.29 仍开放，主清单维持 **76/98**。没有运行全量 `test:e2e`、Chrome、Edge 或 CDP。

### 2026-10-12 双标签角色保存与冲突提示复验（F4.29，异常未收口）

- **环境：**隔离 Vite `127.0.0.1:5197`，两枚 Codex IAB 标签，合成 admin 与本地 Mock；无真实服务或持久化依赖。
- **观察：**标签 A 在 viewer/view 基线上暂选 admin；标签 B 也读取 viewer/view 后选择 admin 并点保存。B 同时显示“服务端已确认保存，正在更新当前列表”和“账号已被其他操作修改”冲突提示，详情摘要仍为 `viewer · 启用`，radio 显示 admin、保存禁用。B reload 后该成功/冲突提示组合仍可见。未再提交、未试图猜测性恢复或重放。
- **解释边界（后续复核修正）：**这是保存回执已确认、权威详情重读尚未完成时捕获的中间态；当时的 reload 观察没有等待刷新收敛，不据此推断永久异常或真实服务端并发结果。Mock handler 跨标签共享语义仍未经验证，不能将它当成正式冲突验收。

### 2026-10-12 单标签成功保存刷新收敛复验

- **环境与动作：**隔离 `127.0.0.1:5198` 新建 IAB 标签，本地 Mock admin 会话；将 `viewer` 从 `view` 改为 `admin` 并保存。没有访问真实 Python、DB 或配置中心。
- **观察：**回执成功后短暂显示“正在更新列表”及旧详情；约 11 秒后成功/冲突反馈均清除，详情摘要和 radio 均显示 `admin`，Save/Discard 禁用。未重试命令。
- **结论：**先前单标签路径最终完成权威读回；本轮在该隔离 origin 上对另一角色写入却立即进入 `result-unknown`，检查操作后仍未有可见状态变化，未重放写入。因此前次成功路径不能代表稳定、可重复的 mounted 验收。本轮增加的源码门禁会在 mutation success 状态抑制基于旧详情推导的冲突提示，真实 revision conflict 仍由 workflow 正式 conflict 状态展示；但本轮没有成功回执 mounted 窗口可验证这个分支。
- **边界：**unknown 的原因未从网络层取证，不归因于代码或服务；读回失败/超时、真实并发 revision 冲突、session owner 失效与 Python live 仍未验收；F4.29 保持开放。未运行全量 `test:e2e`、Chrome、Edge 或 CDP。

### 2026-10-12 已提交角色写入丢失回执后的原操作核查集成测试

- **覆盖：**新增 `ACCOUNT-ACK-INTEGRATION`，使用正式 `ConsoleTransport`、account HTTP adapter 和 `AccountManagementWorkflow`，由受控 HTTP authority 在角色变更写入后保留 completed operation，但向首次 POST 返回 503。工作流进入 `result-unknown` 后仅通过原 request key 查询回执；确认 completed 后重新读取活动目录和当前详情，二者均反映新角色。
- **安全断言：**写入 POST 恰好一次、operation lookup 恰好一次、目录/详情各在初始读取与确认后刷新一次；没有因 503 重放写命令。该结果表明未知路径的既定确认合同可由端到端 HTTP adapter/workflow 组合完成。
- **验证：**`npm run test:http:focused -- 'ACCOUNT-ACK-INTEGRATION'` **1/1 passed**；`npm run typecheck`、目标 Prettier 检查与 `git diff --check` 通过。
- **边界：**这是受控 MSW/HTTP 组合测试，不重现先前 mounted IAB 那次 `result-unknown`，也不证明 Python durable store、跨实例操作回读或真实服务网络故障；原浏览器事件仍无法归因。F4.29 继续开放，完整浏览器 E2E 与 Python live 验收保持后置。

### 2026-10-12 F4.29 角色状态定向逻辑复核

- **复核范围：**角色草稿恢复/隔离、保存 pending 与单飞、unknown 结果禁止重放、revision conflict 与权威刷新、刷新失败保留冲突、owner/session 变化及迟到命令结果。
- **验证命令：**在 `components/sentinel/dashboard-prototype` 执行 `npm run test:logic:focused -- 'ROLE-|ACCOUNT-OWNER|ACCOUNT-SELF-MUTATION|ACCOUNT-SELECT|ACCOUNT-LIST'`，**21/21 passed**。覆盖项包括 dirty draft 的 session/target 隔离、损坏/超限/storage 故障降级、dirty draft 保留旧 revision、保存前 stale baseline 不发命令、pending 单飞、冲突后的权威读解除且不重放、读失败不清冲突、unknown 不被普通详情读取解除，以及 owner 变化后取消在途操作并拒绝迟到结果回填。
- **代码变更：**本轮没有修改角色业务源码或测试；相关实现和测试均为工作区已有改动，本轮只复核并追加本验收记录。
- **浏览器与服务边界：**检查 Codex 可用 surfaces 得到 `browsers: []`，因此本轮没有运行 mounted IAB；没有调用 Chrome、Edge、CDP，也没有运行完整 E2E、Python 服务或持久化依赖。
- **结论：**上述为逻辑层合同证据，不替代 mounted pending/unknown/conflict/owner-change 交互验收，也不证明 Python live authority。F4.29 继续开放；F4.28 状态不变。

### 2026-10-13 mounted revision-conflict 恢复闭环

- **缺口与修复：**正式 `RoleEditor` 在 workflow 已进入 `conflict` 时仍允许编辑 radio 并再次提交旧 revision。现将 conflict 纳入编辑锁，保留“读取最新”这一只读恢复入口。
- **验证：**新增 Happy DOM 实际挂载测试覆盖冲突后保留选择、禁用旧版本编辑/写入、首次权威重读失败仍保留冲突和草稿、第二次读取成功后采用新 revision/角色；写入始终恰好一次。挂载用例 **1/1 passed**；`ROLE-|ACCOUNT-OWNER|ACCOUNT-SELF-MUTATION|ACCOUNT-SELECT|ACCOUNT-LIST` 逻辑 **21/21 passed**；`npm run check:fast` 与 `git diff --check` 通过。
- **边界：**未覆盖 mounted pending/unknown/owner-change 全矩阵、真实 Python 权威、多用户数据库并发或完整 E2E；F4.29 继续开放，完整 E2E 保留在最终阶段。

### 2026-10-13 mounted pending→unknown→operation inspection

- **覆盖：**在实际挂载的 `RoleEditor` 中保持写请求未决，确认 pending 提示、控件禁用且不提供核查入口；再注入网络中断，确认进入 `result-unknown`、草稿保留、仅提供原操作查询；第一次查询 `not-found` 不视作回滚且不解锁重提；后续查询取得 completed 回执后才刷新权威角色。
- **安全断言：**角色 POST 始终恰好一次，操作查询使用原 request key；查询期间/查询未找到时无写入重放。
- **验证：**`node --test tests/verification/role-editor-mounted-conflict.test.mjs tests/verification/role-editor-mounted-unknown.test.mjs` **2/2 passed**；角色相关 logic **21/21 passed**；`npm run check:fast` 通过；Prettier、ESLint 与 `git diff --check` 通过。
- **边界：**Happy DOM mounted + workflow 组合，不证明 Python durable receipt、跨实例查询或 Codex IAB 全流程；F4.29 保持开放，完整 E2E 保留在最终阶段。
