"""Run the production mounted React rule page against a caller-owned live Console app."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import uvicorn
from starlette.applications import Starlette


async def verify_mounted_rule_catalog_page(
    app: Starlette,
    *,
    environment_id: str,
    app_id: str,
    resource: str,
    source_label: str,
) -> None:
    """Start the provided app on loopback and require the production page to render its catalog."""
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=0,
            log_level="error",
            access_log=False,
            lifespan="off",
        )
    )
    server_task = asyncio.create_task(server.serve())
    try:
        async with asyncio.timeout(10):
            while not server.started and not server_task.done():
                await asyncio.sleep(0.01)
        if server_task.done():
            server_task.result()
            raise RuntimeError(
                "Console HTTP server exited before mounted UI verification"
            )
        if not server.servers or not server.servers[0].sockets:
            raise RuntimeError("Console HTTP server did not bind a loopback socket")
        port = server.servers[0].sockets[0].getsockname()[1]
        dashboard_root = Path(__file__).resolve().parents[3] / "dashboard-prototype"
        node_environment = os.environ.copy()
        node_environment.update(
            {
                "SENTINEL_CONSOLE_BASE_URL": f"http://127.0.0.1:{port}",
                "SENTINEL_RULE_CATALOG_ENVIRONMENT": environment_id,
                "SENTINEL_RULE_CATALOG_APP": app_id,
                "SENTINEL_RULE_CATALOG_RESOURCE": resource,
                "SENTINEL_RULE_CATALOG_SOURCE": source_label,
            }
        )
        node_process = await asyncio.create_subprocess_exec(
            "node",
            "--test",
            "tests/verification/rule-catalog-python-mounted.test.mjs",
            cwd=dashboard_root,
            env=node_environment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(node_process.communicate(), timeout=60)
        if node_process.returncode != 0:
            raise AssertionError(
                "Mounted React page did not render the provider-backed Console projection.\n"
                f"stdout:\n{stdout.decode(errors='replace')}\n"
                f"stderr:\n{stderr.decode(errors='replace')}"
            )
    finally:
        server.should_exit = True
        await server_task
