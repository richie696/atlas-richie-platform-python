# docs/process/ — 过程文档 (中间产物)

中文
----
本目录放 **M 系列开发期的过程文档**, **不**是产品最终保留的文档。

**约定** (richie696 决策 2026-09-13):

- **产品最终保留** 的文档放在 `docs/` 根 (跟 `DESIGN.md`, `OPERATIONS.md`,
  `RELEASE.md` 同级); V1 协议冻结后也不带 M 编号 (例:
  `上报协议-01-envelope-v1.md`, `上报协议-02-transport-v1.md`,
  `上报协议-03-freeze-v1.md`, `集群令牌协议-v1.md`).
- **过程文档** 放本目录 (`docs/process/`); M 系列开发结束 (1.0 publish)
  后, 本目录的文档会被清理掉, 不会随产品一起发布。
- **acceptance/** 子目录放 M 系列的测试 / 验收证据 (R-XXX-handoff,
  test-matrix, baseline report), 同样 1.0 publish 后清理。

**新增过程文档** 规则:

- 任何过程文档 (design / implementation-plan / handoff / sign-off
 过程中间产物 / 可行性评估 / 调研笔记) **必须**放本目录, 命名带
 过程编号 (M6.X / R-XXX / HANDOFF-XXX).
- V1 协议冻结 / API delta / 1.0 publish-ready 文档**不**放本目录,
 必须**先**改名为无过程编号的名字, 再放 `docs/` 根.

English
--------
`docs/process/` holds **M-series development process documents** —
NOT final product docs.

Convention (richie696 decision 2026-09-13):

- **Final product docs** (retained) live in `docs/` root (alongside
  `DESIGN.md`, `OPERATIONS.md`, `RELEASE.md`); V1 protocol docs
  also use non-M-number names (e.g. `上报协议-01-envelope-v1.md`,
  `上报协议-02-transport-v1.md`, `上报协议-03-freeze-v1.md`,
  `集群令牌协议-v1.md`).
- **Process docs** (deleted after 1.0 publish) live in this directory.
- **acceptance/** subdirectory holds M-series test/evidence docs
  (R-XXX-handoff, test-matrix, baseline report), also deleted.

Adding new process docs:

- Any process doc (design / impl-plan / handoff / mid-sign-off / eval /
  notes) **must** go here with M-series / R-XXX / HANDOFF-XXX naming.
- V1 frozen protocols / API deltas / 1.0-publish-ready docs do **NOT**
  go here — rename to drop process number, then place in `docs/` root.
