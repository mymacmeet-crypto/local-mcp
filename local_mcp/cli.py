"""Command-line entry point for local-mcp."""

from __future__ import annotations

import os
import sys

from local_mcp.app import mcp


def main() -> None:
    argv = sys.argv[1:]
    if "--http" in argv:
        mode = "http"
    elif "--stdio" in argv:
        mode = "stdio"
    else:
        mode = os.environ.get("MCP_TRANSPORT", "stdio").lower()

    if mode == "http":
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")
