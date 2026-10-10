"""Routes for serving the packaged Dashboard client from the Console ASGI app."""

from __future__ import annotations

import re
from os import PathLike, stat_result as StatResult
from pathlib import Path

from starlette.requests import Request
from starlette.responses import FileResponse, RedirectResponse, Response
from starlette.routing import BaseRoute, Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from .http_support import error_response, request_id

_ASSET_MAX_AGE_SECONDS = 31_536_000
_BASE_PATH_PATTERN = re.compile(r"^/(?:[A-Za-z0-9_-]+/)*$")
_API_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


class _DashboardAssetFiles(StaticFiles):
    """Serve Vite fingerprinted assets with immutable caching."""

    def file_response(
        self,
        full_path: PathLike[str] | str,
        stat_result: StatResult,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        response = super().file_response(full_path, stat_result, scope, status_code)
        response.headers["cache-control"] = (
            f"public, max-age={_ASSET_MAX_AGE_SECONDS}, immutable"
        )
        return response


def dashboard_web_routes(
    directory: Path, base_path: str = "/"
) -> list[BaseRoute]:
    """Serve the React client under a validated prefix, outside the API space."""
    if (
        not _BASE_PATH_PATTERN.fullmatch(base_path)
        or base_path == "/api/"
        or base_path.startswith("/api/")
    ):
        raise ValueError("dashboard base path must be / or a canonical slash path")

    index_file = directory / "index.html"
    assets_directory = directory / "assets"
    if not index_file.is_file() or not assets_directory.is_dir():
        raise FileNotFoundError("packaged Dashboard assets are incomplete")

    async def index(_: Request) -> Response:
        return FileResponse(index_file, headers={"cache-control": "no-cache"})

    async def api_not_found(request: Request) -> Response:
        correlation_id, _valid = request_id(request)
        return error_response(correlation_id, "not_found", 404)

    async def spa_fallback(_: Request) -> Response:
        return FileResponse(index_file, headers={"cache-control": "no-cache"})

    async def redirect_to_base_path(_: Request) -> Response:
        return RedirectResponse(base_path, status_code=308)

    api_prefixes = {"/api"}
    if base_path != "/":
        api_prefixes.add(f"{base_path}api")

    routes: list[BaseRoute] = [
        route
        for api_prefix in sorted(api_prefixes)
        for route in (
            Route(api_prefix, api_not_found, methods=_API_METHODS),
            Route(f"{api_prefix}/{{path:path}}", api_not_found, methods=_API_METHODS),
        )
    ]
    routes.append(
        Mount(
            f"{base_path}assets" if base_path != "/" else "/assets",
            app=_DashboardAssetFiles(directory=assets_directory),
        )
    )
    if base_path == "/":
        routes.extend(
            [
                Route("/", index, methods=["GET", "HEAD"]),
                Route("/{path:path}", spa_fallback, methods=["GET", "HEAD"]),
            ]
        )
    else:
        routes.extend(
            [
                Route(
                    base_path[:-1],
                    redirect_to_base_path,
                    methods=["GET", "HEAD"],
                ),
                Route(base_path, index, methods=["GET", "HEAD"]),
                Route(
                    f"{base_path}{{path:path}}",
                    spa_fallback,
                    methods=["GET", "HEAD"],
                ),
            ]
        )
    return routes
