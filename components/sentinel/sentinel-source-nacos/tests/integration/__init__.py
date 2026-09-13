"""Real-Nacos integration tests for ``atlas-richie-sentinel-source-nacos``.

中文
----
M6.1 真实验收 5 场景, 走真 Nacos server (本机 Docker
``nacos-pg-3.2.3``, 端口 8848+9848, username/password=nacos)。

整个套件 marker ``integration``; Nacos 不可达时自动 skip。运行:

    .venv/bin/pytest tests/integration/ -m integration -v

English
--------
Real-Nacos integration suite covering the 5 acceptance scenarios for
``NacosRuleSource``. Auto-skips when the configured Nacos server is
unreachable.
"""
