# Atlas Richie Sentinel — Release Procedure

## Pre-flight

- `versions.toml` 包含 `atlas-richie-sentinel = "<X.Y.Z>"` 条目
- `components/sentinel/sentinel/pyproject.toml` 的 `[project] version` 与 `versions.toml` 同步
- 仓库根 `dist/` 已有其它组件(secret / cache)的旧产物,**不要** 直接扫描 `dist/`

## 发布流程(专用干净目录)

```bash
# 1. 准备专用输出目录
rm -rf /tmp/atlas-richie-sentinel-release

# 2. 构建 — --clear 重建 + --no-create-gitignore 避免 .gitignore 假失败
uv build --package atlas-richie-sentinel \
         --out-dir /tmp/atlas-richie-sentinel-release \
         --clear \
         --no-create-gitignore

# 3. 严格门禁: 恰好 1 wheel + 1 sdist, 包名匹配 atlas_richie_sentinel-*, 三处版本一致
python tools/release/check_version_consistency.py /tmp/atlas-richie-sentinel-release

# 4. 发布 — 用 glob 避免再次硬编码规范化和版本号
uv publish /tmp/atlas-richie-sentinel-release/*.whl \
           /tmp/atlas-richie-sentinel-release/*.tar.gz
```

## 命名约定(PEP 625)

- 仓库原始包名: `atlas-richie-sentinel`
- 规范化文件名 slug: `atlas_richie_sentinel`
- wheel 文件名: `atlas_richie_sentinel-X.Y.Z-py3-none-any.whl`
- sdist 文件名: `atlas_richie_sentinel-X.Y.Z.tar.gz`
- 内部 `Name:` / `Version:` 字段(METADATA + PKG-INFO)保留原始 `atlas-richie-sentinel`

## 命名空间所有权门禁

主 wheel 独占 `atlas_richie.sentinel` 命名空间;任何其它 wheel 在该
路径写文件都会失败:

```bash
python tools/release/check_sentinel_namespace.py --dist-dir /tmp/atlas-richie-sentinel-release
# OK: atlas-richie-sentinel exclusively owns the atlas_richie.sentinel namespace (N files)
```

## 失败模式

- `check_version_consistency.py` 退出码 1 → 修复后重试(常见原因:wheel/sdist 数量错、PEP 625 slug 不匹配、版本号漂移)
- `check_sentinel_namespace.py` 退出码 1 → 命名空间被扩展 wheel 污染,移除冲突文件后重试
- `uv publish` 失败 → 通常是网络 / token 问题,跟本流程无关

## CI 集成

`check_version_consistency.py` 和 `check_sentinel_namespace.py` 都接进
`tools/release/release_gate.sh`,作为发布前必经步骤。
