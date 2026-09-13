"""M6.4.1 Client Agent subprocess (双 Agent 验收夹具).

中文
----
Client Agent 是 M6.4 验收夹具里跑在**独立进程**的 RemoteTokenService wrapper.
它通过 stdin/stdout 跟 pytest 主进程通信, 接收 acquire/release 命令, 返回结果.

**为什么走 subprocess 而非 in-process thread** (M6.4.1 决策):

- M6.4 验收核心: **真实进程 + 真实网络**. Thread 还是同进程同 GIL 同 event loop.
- Subprocess 保证: 独立 instance_id, 独立 startup_epoch, 独立 event loop,
  真实 OS-level 网络栈 + 文件描述符隔离.
- 1.0 简化: 不用 multiprocessing.Manager / 共享内存, 走 stdin/stdout + JSON.

**协议** (跟 driver):

```
# Driver → Agent (stdin, JSON 1 行 1 命令)
{"cmd": "acquire", "resource": "/r1", "permits": 1.0, "deadline_ns": 5000000}
{"cmd": "release", "token": <token dict>}
{"cmd": "aclose"}
{"cmd": "shutdown"}

# Agent → Driver (stdout, JSON 1 行 1 结果)
{"result": "acquire", "ok": true, "response": <TokenResponse dict>}
{"result": "acquire", "ok": false, "error": "ClusterServerError", "message": "..."}
{"result": "release", "ok": true}
{"result": "shutdown", "ok": true}
```

**反例** (1.0 拒绝):

- ❌ multiprocessing.Queue (Agent 必须真 subprocess, 不能 fork 后共享 Queue)
- ❌ pickle (跨进程 dataclass 不可靠, 1.0 简化用 dict + JSON)
- ❌ aiohttp / httpx (0 3rd-party)

English
--------
Client Agent: subprocess wrapper around RemoteTokenService for M6.4 acceptance.

Why subprocess (M6.4.1 decision):

- M6.4 acceptance core: **real process + real network**. Threads share GIL + loop.
- Subprocess guarantees: independent instance_id, startup_epoch, event loop,
  real OS-level network stack.
- 1.0 simplification: stdin/stdout + JSON (no multiprocessing.Manager).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
import uuid
from dataclasses import asdict
from typing import Any, Sequence

from atlas_richie.sentinel.ports.token import (
    ClusterFailurePolicy,
    LocalTokenService,
    TokenDecision,
)
from atlas_richie.sentinel_cluster import (
    ClientIdentity,
    ClusterTokenConfig,
    ClusterTokenMode,
    RemoteTokenService,
    ResourceConfig,
)
from atlas_richie.sentinel_cluster.errors import (
    ClusterConfigError,
    ClusterServerError,
)

_log = logging.getLogger("atlas_richie.sentinel_cluster.tests.integration.agent_runtime")


# ---------------------------------------------------------------------------
# Token / TokenResponse dict 序列化 (跨进程)
# ---------------------------------------------------------------------------


def _token_to_dict(token: Any) -> dict[str, Any]:
    """``Token`` frozen dataclass → dict (跨进程 JSON 兼容)."""
    return {
        "resource": token.resource,
        "permits": token.permits,
        "issued_at_ns": token.issued_at_ns,
        "ttl_ns": token.ttl_ns,
        "lease_id": token.lease_id,
        "owner_epoch": token.owner_epoch,
    }


def _token_response_to_dict(resp: Any) -> dict[str, Any]:
    """``TokenResponse`` → dict."""
    return {
        "decision": resp.decision.value,
        "token": _token_to_dict(resp.token) if resp.token is not None else None,
        "deny_reason": resp.deny_reason.value if resp.deny_reason is not None else None,
        "wait_ns": resp.wait_ns,
        "retry_after_ns": resp.retry_after_ns,
    }


def _dict_to_token(d: dict[str, Any]) -> Any:
    """``dict`` → ``Token`` (用于 release)."""
    from atlas_richie.sentinel.ports.token import Token

    return Token(
        resource=d["resource"],
        permits=d["permits"],
        issued_at_ns=d["issued_at_ns"],
        ttl_ns=d["ttl_ns"],
        lease_id=d["lease_id"],
        owner_epoch=d["owner_epoch"],
    )


# ---------------------------------------------------------------------------
# Agent 主循环
# ---------------------------------------------------------------------------


class ClientAgent:
    """Client Agent 主类. 1 个 Agent = 1 个 RemoteTokenService."""

    def __init__(self, args: argparse.Namespace) -> None:
        # 构造 config
        resources = tuple(
            ResourceConfig(name=r["name"], max_permits=r["max_permits"])
            for r in args.resources
        )
        failure_policy = {
            r["name"]: ClusterFailurePolicy(r["failure_policy"]) for r in args.resources
        }
        config = ClusterTokenConfig(
            cluster_token_mode=ClusterTokenMode.CLIENT_ONLY,
            auth_secret=args.auth_secret,
            server_addresses=(args.server_address,),
            resources=resources,
            failure_policy_per_resource=failure_policy,
        )
        identity = ClientIdentity(
            instance_id=args.instance_id,
            startup_epoch=args.startup_epoch,
        )
        local_fallback = (
            LocalTokenService() if args.local_fallback == "yes" else None
        )
        self._rts = RemoteTokenService(
            config, identity=identity, local_fallback=local_fallback
        )
        self._started = False
        # 1.0 简化: 内部 new_event_loop 已经处理 async-to-sync, 不需要 astart
        # 但 acquire 内部判 _started, 我们 lazy mark

    def handle_command(self, cmd: dict[str, Any]) -> dict[str, Any]:
        """处理 1 个 driver 命令, 返回结果 dict (写到 stdout)."""
        op = cmd.get("cmd")
        try:
            if op == "acquire":
                return self._cmd_acquire(cmd)
            elif op == "release":
                return self._cmd_release(cmd)
            elif op == "aclose":
                return self._cmd_aclose()
            elif op == "shutdown":
                return self._cmd_shutdown()
            else:
                return {
                    "result": "error",
                    "ok": False,
                    "error": "UnknownCommand",
                    "message": f"unknown cmd: {op!r}",
                }
        except Exception as e:
            # 任何未捕获错都返 (Agent 不死)
            return {
                "result": op or "error",
                "ok": False,
                "error": type(e).__name__,
                "message": str(e)[:200],  # 限长, 避免反序列化错
            }

    def _cmd_acquire(self, cmd: dict[str, Any]) -> dict[str, Any]:
        if not self._started:
            self._rts._started = True
        resp = self._rts.acquire(cmd["resource"], cmd["permits"])
        return {
            "result": "acquire",
            "ok": True,
            "response": _token_response_to_dict(resp),
        }

    def _cmd_release(self, cmd: dict[str, Any]) -> dict[str, Any]:
        token = _dict_to_token(cmd["token"])
        self._rts.release(token)
        return {"result": "release", "ok": True}

    def _cmd_aclose(self) -> dict[str, Any]:
        if not self._closed:
            self._rts._closed = True
        return {"result": "aclose", "ok": True}

    _closed = False

    def _cmd_shutdown(self) -> dict[str, Any]:
        return {"result": "shutdown", "ok": True}


# ---------------------------------------------------------------------------
# 主循环 (stdin → handle_command → stdout)
# ---------------------------------------------------------------------------


def _run_agent_stdio(args: argparse.Namespace) -> int:
    """agent stdio main loop: 读 stdin JSON → handle → 写 stdout JSON."""
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.WARNING),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,  # log → stderr, 避免污染 stdout 协议
    )
    agent = ClientAgent(args)
    # 通知 driver agent ready
    sys.stdout.write(
        json.dumps({"result": "ready", "ok": True, "instance_id": args.instance_id}) + "\n"
    )
    sys.stdout.flush()
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                cmd = json.loads(line)
            except json.JSONDecodeError as e:
                sys.stdout.write(
                    json.dumps(
                        {
                            "result": "error",
                            "ok": False,
                            "error": "JSONDecodeError",
                            "message": str(e),
                        }
                    )
                    + "\n"
                )
                sys.stdout.flush()
                continue
            result = agent.handle_command(cmd)
            sys.stdout.write(json.dumps(result) + "\n")
            sys.stdout.flush()
            if cmd.get("cmd") == "shutdown":
                break
    except (KeyboardInterrupt, BrokenPipeError):
        pass
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="agent_runtime",
        description="M6.4.1 Client Agent subprocess (RemoteTokenService + stdio IPC)",
    )
    parser.add_argument(
        "--server-address", required=True, help="Server address (e.g. 127.0.0.1:8765)"
    )
    parser.add_argument(
        "--auth-secret", required=True, help="shared secret (跟 Server 配对)"
    )
    parser.add_argument(
        "--instance-id",
        default=lambda: str(uuid.uuid4()),
        help="Client 身份 UUID (default: 新生成)",
    )
    parser.add_argument(
        "--startup-epoch", type=int, default=0, help="startup epoch (default 0)"
    )
    parser.add_argument(
        "--request-timeout-ns",
        type=int,
        default=5_000_000_000,
        help="request timeout 纳秒 (default 5s)",
    )
    parser.add_argument(
        "--local-fallback",
        choices=("yes", "no"),
        default="no",
        help="LOCAL_FALLBACK 用的 LocalTokenService (default no)",
    )
    parser.add_argument(
        "--resources",
        type=json.loads,
        required=True,
        help=(
            'JSON 数组, e.g. '
            '[{"name":"/r1","max_permits":5.0,"failure_policy":"FAIL_CLOSED"}]'
        ),
    )
    parser.add_argument("--log-level", default="WARNING", help="日志级别 (default WARNING)")
    args = parser.parse_args(argv)
    return _run_agent_stdio(args)


if __name__ == "__main__":
    sys.exit(main())
