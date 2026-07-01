"""FastMCP application setup for local-mcp."""

from __future__ import annotations

import contextlib
import os

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

load_dotenv()

from local_mcp.tools import register_tools  # noqa: E402
from local_mcp.web import fetcher  # noqa: E402


@contextlib.asynccontextmanager
async def _lifespan(_server: "FastMCP"):
    try:
        yield
    finally:
        await fetcher.close_crawler()


mcp = FastMCP(
    "local-mcp",
    lifespan=_lifespan,
    host=os.environ.get("MCP_HTTP_HOST", "127.0.0.1"),
    port=int(os.environ.get("MCP_HTTP_PORT", "3002")),
    # Public ASGI hosts use their deployment domain as Host. FastMCP's DNS
    # rebinding protection is useful for localhost-only servers, but rejects
    # those public hosts, so remote deployments disable it here.
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

register_tools(mcp)

with contextlib.suppress(Exception):
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_req: "Request") -> "JSONResponse":
        return JSONResponse({"status": "ok", "server": "local-mcp"})


# Top-level ASGI application for serverless/ASGI hosts.
app = mcp.streamable_http_app()
