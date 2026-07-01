"""MCP tool error helpers."""

from __future__ import annotations

import httpx
from mcp.server.fastmcp.exceptions import ToolError


def describe_fetch_error(err: Exception, label: str) -> str:
    if isinstance(err, httpx.HTTPStatusError):
        status = err.response.status_code
        if status == 404:
            return f"{label} returned 404 Not Found."
        if status in (401, 403):
            return f"{label} refused access ({status})."
        if status == 429:
            return f"{label} rate-limited the request (429)."
        if status >= 500:
            return f"{label} returned a server error ({status})."
        return f"{label} returned HTTP {status}."
    if isinstance(err, (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout)):
        return f"Request to {label} timed out."
    if isinstance(err, httpx.ConnectError):
        return f"Could not connect to {label}. Check the URL or connection."
    return f"Error fetching {label}: {err}"


def tool_error(text: str) -> ToolError:
    return ToolError(text)
