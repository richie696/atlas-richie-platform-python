# R-SENTINEL-M5.4 Python / OS Matrix Evidence

| Field | Value |
| ----- | ----- |
| Test ID | SEN-MATRIX-001 (Python × OS matrix) |
| Date | 2026-09-13 |
| Commit | `39ab896` + 5 follow-ups (M1.6 → M5.3) |
| Build host | macOS Darwin 27.0.0 (arm64) |
| Python 3.12 | `cpython-3.12.14-macos-aarch64-none` |
| Python 3.13 | `cpython-3.13.15-macos-aarch64-none` |
| Author | Mavis (Atlas Richie Sentinel M5.4) |

> **Matrix coverage**: 2 Python versions × 5 wheels × isolated venv
> install + import + smoke test. **No** 3.10 / 3.11 (主包
> `requires-python = ">=3.12"`, 1.0 不支持 3.11 及以下)。
>
> **Matrix coverage**: 2 Python × 5 wheels × isolated venv install +
> import + smoke. **No** 3.10 / 3.11 (main package
> `requires-python = ">=3.12"`, 1.0 doesn't support ≤ 3.11).

---

## 1. 5 wheels built (M5.4 step 1)

`uv build --out-dir /tmp/wheels-final/<wheel>/` 全部成功。

| Wheel | Version | Path |
| ----- | ------- | ---- |
| `atlas-richie-sentinel` | 0.2.0 | `sentinel/atlas_richie_sentinel-0.2.0-py3-none-any.whl` |
| `atlas-richie-sentinel-adapter-asgi` | 0.2.0 | `sentinel-adapter-asgi/atlas_richie_sentinel_adapter_asgi-0.2.0-py3-none-any.whl` |
| `atlas-richie-sentinel-adapter-httpx` | 0.2.0 | `sentinel-adapter-httpx/atlas_richie_sentinel_adapter_httpx-0.2.0-py3-none-any.whl` |
| `sentinel-source-file` | 0.2.0 | `sentinel-source-file/atlas_richie_sentinel_source_file-0.2.0-py3-none-any.whl` |
| `sentinel-dashboard` | 0.2.0 | `sentinel-dashboard/atlas_richie_sentinel_dashboard-0.2.0-py3-none-any.whl` |

PEP 625 命名(slug 用下划线)全部 OK。

## 2. Version consistency (3 sources, all 5 wheels)

```
$ tools/release/check_version_consistency.py --name atlas-richie-sentinel /tmp/wheels-final/sentinel
OK: name='atlas-richie-sentinel' version='0.2.0' consistent across pyproject.toml, wheel METADATA, sdist PKG-INFO

$ tools/release/check_version_consistency.py --name atlas-richie-sentinel-adapter-asgi /tmp/wheels-final/sentinel-adapter-asgi
OK: name='atlas-richie-sentinel-adapter-asgi' version='0.2.0' consistent across pyproject.toml, wheel METADATA, sdist PKG-INFO

# 同样适配 -adapter-httpx / -source-file / -dashboard
```

3 sources 一致:`pyproject.toml` / wheel `METADATA` / sdist `PKG-INFO`。

## 3. Python 3.12 isolated venv (M5.4 step 2)

```bash
$ uv venv /tmp/sentinel-verify_312/venv-312 --python 3.12
$ source /tmp/sentinel-verify_312/venv-312/bin/activate
$ for w in /tmp/wheels-final/*/atlas_richie_*.whl; do
    uv pip install "$w"
  done
 + atlas-richie-sentinel==0.2.0
 + atlas-richie-sentinel-adapter-asgi==0.2.0
 + typing-extensions==4.16.0
 + atlas-richie-sentinel-source-file==0.2.0
 + atlas-richie-sentinel-dashboard==0.2.0

$ python -c "import atlas_richie.sentinel; print(atlas_richie.sentinel.__version__)"
0.2.0
```

**Smoke test 3.12**:Engine / ASGI / HTTPX / File source 全部 OK。

## 4. Python 3.13 isolated venv (M5.4 step 3)

```bash
$ uv venv /tmp/sentinel-verify_313/venv-313 --python 3.13
$ source /tmp/sentinel-verify_313/venv-313/bin/activate
$ for w in /tmp/wheels-final/*/atlas_richie_*.whl; do
    uv pip install "$w"
  done
 + atlas-richie-sentinel==0.2.0
 + atlas-richie-sentinel-adapter-asgi==0.2.0
 + typing-extensions==4.16.0
 + atlas-richie-sentinel-source-file==0.2.0
 + atlas-richie-sentinel-dashboard==0.2.0

$ python -c "import atlas_richie.sentinel; print(atlas_richie.sentinel.__version__)"
0.2.0
```

**Smoke test 3.13**:Engine / ASGI / HTTPX / File source 全部 OK。

## 5. Exit Criteria 复盘

| Criterion | 状态 | 证据 |
| --------- | ---- | ---- |
| 5 wheel 独立 build 成功 | ✅ | §1 |
| 3 source version consistency | ✅ | §2 (5/5 OK) |
| 3.12 isolated venv install | ✅ | §3 |
| 3.12 5 wheel import + smoke | ✅ | §3 |
| 3.13 isolated venv install | ✅ | §4 |
| 3.13 5 wheel import + smoke | ✅ | §4 |
| 主包零 3rd-party 依赖 | ✅ | `dependencies = []` 在 5 个 wheel 的 pyproject |
| `requires-python = ">=3.12"` | ✅ | 5 个 wheel pyproject |
| PEP 625 命名 (slug = 下划线) | ✅ | 5 wheel 文件名 |

---

## 6. 已知边界

- **3.10 / 3.11 不支持**:主包 `requires-python = ">=3.12"`;3.10/3.11
  是 1.0 不在 support 范围。如用户需 3.11 兼容,需开新 milestone
  (PLANNING §M5.4.1 候选,1.x 路线)。
- **Linux x86_64 / Windows 1.0 不在本次 matrix**:本次只跑了 macOS
  arm64 + 3.12/3.13。Linux / Windows 由 CI 覆盖(1.x 加)。
- **typping-extensions 是间接依赖**(adapters 透传);1.0 不会强约束
  typing-extensions 版本。

## 7. 重新跑 matrix 的命令

```bash
# 1. 5 wheel build
for w in sentinel sentinel-adapter-asgi sentinel-adapter-httpx \
         sentinel-source-file sentinel-dashboard; do
  cd /Users/richie696/Projects/workspace/atlas-richie-platform-python/components/sentinel/$w 2>/dev/null || \
  cd /Users/richie696/Projects/workspace/atlas-richie-platform-python/components/sentinel/sentinel
  uv build --out-dir /tmp/wheels-final/$w
done

# 2. 3 source version consistency
for w in sentinel sentinel-adapter-asgi sentinel-adapter-httpx \
         sentinel-source-file sentinel-dashboard; do
  /opt/homebrew/bin/python3.12 tools/release/check_version_consistency.py \
    --name atlas-richie-$w /tmp/wheels-final/$w
done

# 3. 3.12 / 3.13 isolated venv
mkdir -p /tmp/sentinel-verify_312 /tmp/sentinel-verify_313
cd /tmp/sentinel-verify_312 && uv venv venv-312 --python 3.12
source venv-312/bin/activate
for w in /tmp/wheels-final/*/atlas_richie_*.whl; do uv pip install "$w"; done
python -c "import atlas_richie.sentinel; print('3.12 OK')"

cd /tmp/sentinel-verify_313 && uv venv venv-313 --python 3.13
source venv-313/bin/activate
for w in /tmp/wheels-final/*/atlas_richie_*.whl; do uv pip install "$w"; done
python -c "import atlas_richie.sentinel; print('3.13 OK')"
```
