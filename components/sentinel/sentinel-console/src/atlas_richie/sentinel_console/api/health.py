"""Process health endpoint for orchestrators and deployment probes."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route


async def _read_process_health(_: Request) -> Response:
    """Report that the ASGI process can serve requests, without dependency claims."""
    return JSONResponse(
        {"status": "ok"},
        headers={"cache-control": "no-store"},
    )


def process_health_route() -> Route:
    """Create the unversioned liveness/readiness probe route.

    This intentionally checks only process-level request handling. Database,
    configuration-center, and monitoring-source health are reported by their
    dedicated Console APIs and are not prerequisites for serving the UI/setup.
    """
    return Route("/healthz", _read_process_health, methods=["GET", "HEAD"])
