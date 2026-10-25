# 本地发行产物检查

这些命令只构建与验证文件，不向 PyPI 发布，也不启动 Docker 服务。
在仓库根目录执行；`uv` 与目标版本的 Python 必须可用，workspace venv 无需安装 pip。

```sh
uv build --all-packages
uv run python tools/release/prepare_wheelhouse.py
uv run python tools/release/verify_isolated_wheels.py
```

准备步骤联网读取受 `uv.lock` 哈希保护的 runtime 依赖，生成 `dist/wheelhouse/*.whl`。
只有 sdist 的依赖在临时环境构建，build-system 依赖遵循上游声明，不属于 runtime 锁定范围。
验证步骤逐个在新 venv 中使用 `--no-index` 安装，再运行 `pip check`、精确版本及导入目录检查。
发行清单来自 `pyproject.toml` 的 workspace 成员和各自 project 版本/模块声明；不从旧 dist 推断。
独立 Console 项目不属于根 workspace，这个命令的 36 包结果不代替 Console 的单独打包验证。

可用 `--wheel-dir /absolute/path` 在独立构建目录运行上述两个 Python 脚本；对应
`uv build --all-packages --out-dir /absolute/path`。默认验证全部成员，修改个别包后可定向复核：

```sh
uv run python tools/release/verify_isolated_wheels.py --package atlas-richie-contracts
```

即使定向验证，内部依赖仍受完整 workspace 的精确版本约束。缺少依赖 wheel、声明错误、
目标包名不存在或空 workspace 都是验证失败；不得把失败包装成跳过后的成功。
