# docs/ — Sentinel 产品文档 (最终保留)

中文
----
本目录放 **Sentinel 产品最终保留的文档**, 跟代码一起发布给用户。

**目录结构**:

```
docs/
├── README.md                    # 本文件 (目录说明)
│
├── DESIGN.md                    # 架构总览 (产品)
├── OPERATIONS.md                # 运维指南 (产品)
├── EXTENSION_GUIDE.md           # 扩展编写指南 (产品)
├── QUICK_START.md               # 快速开始 (产品)
├── RULE_REFERENCE.md            # 5 类规则参考 (产品)
├── USAGE.md                     # 完整使用指南 (产品)
├── MIGRATION-M6.md              # 升级迁移指南 (产品)
├── RELEASE.md                   # 发布流程 (产品)
│
├── protocol/                    # V1 协议 frozen (产品, 跨语言 wire)
│   ├── AGENT_REPORTING_PROTOCOL.md
│   ├── CLUSTER_TOKEN_PROTOCOL.md
│   ├── REPORTING-PROTOCOL.md
│   └── ENVELOPE-SCHEMA-FREEZE.md
│
└── process/                     # 过程文档 (1.0 publish 后清理)
    ├── README.md                # 过程文档约定
    ├── M6.X-*.md                # M 系列 design / impl-plan / handoff
    ├── R-XXX-*.md               # R 系列 handoff / sign-off 中间产物
    ├── HANDOFF-*.md             # 会话交接
    ├── PLANNING.md              # milestone planning
    ├── rule_source_activation.md  # C 层内部 fact schema (非 wire)
    └── acceptance/              # 测试 / 验收证据
```

**V1 协议 命名约定** (richie696 决策 2026-09-13):

- V1 frozen 协议**不**带 M 编号 (例: `protocol/REPORTING-PROTOCOL.md`
  而不是 `protocol/M6.5-REPORTING-PROTOCOL-V1.md`).
- V1 frozen 协议统一放 `docs/protocol/` 子目录, 不混在根目录.
- 协议在 1.x 阶段**只允许** V1.1 minor 兼容变更; 任何破坏性变更走 V2
  major + 独立 ADR + 5 owner sign-off.

English
--------
`docs/` holds **Sentinel final product docs**, shipped to users
alongside code.

V1 protocol naming (richie696 decision 2026-09-13):

- V1 frozen protocols do **not** use M-numbers (e.g.
  `protocol/REPORTING-PROTOCOL.md` not `protocol/M6.5-REPORTING-PROTOCOL-V1.md`).
- V1 frozen protocols live in `docs/protocol/` subdir, not at root.
- 1.x only allows V1.1 minor-compatible changes; breaking changes go
  V2 major + independent ADR + 5 owner sign-off.
