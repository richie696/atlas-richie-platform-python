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
