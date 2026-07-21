"""Best-effort progress reporting over an optional MCP ``Context``.

FastMCP injects a ``Context`` into a tool whenever the tool declares a
parameter annotated ``Context`` (see FastMCP's ``find_context_parameter``).
Tools in this package wrap that — possibly ``None`` — context in a
:class:`Progress` and call ``await progress.report("...")`` at each meaningful
step. Every call emits an MCP ``notifications/progress`` message to the client;
the bundled OpenWebUI tool (``integrations/openwebui_tool.py``) forwards those
to the chat UI as live status updates during the call.

The context is ``None`` for internal cross-tool calls (for example
``generate_file`` invoking ``deep_research``) and in unit tests, so reporting is
then a no-op. Reporting also never raises: a client that did not pass a progress
token, or a transient transport error, must never fail the underlying tool.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import Context


class Progress:
    """Adapter that turns step messages into MCP progress notifications.

    ``progress`` values are auto-incremented per :meth:`report` call so they are
    always monotonically increasing (the MCP spec requires this). ``total`` is
    optional; when unknown, notifications carry an indeterminate progress.
    """

    def __init__(self, ctx: "Context | None" = None, *, total: float | None = None) -> None:
        self._ctx = ctx
        self._total = total
        self._step = 0.0

    @property
    def enabled(self) -> bool:
        """True when a live context is attached (progress will actually be sent)."""
        return self._ctx is not None

    async def report(self, message: str, *, total: float | None = None) -> None:
        """Emit one progress update. Best-effort: never raises.

        Args:
            message: Human-readable status shown by the client (e.g. OpenWebUI).
            total: Optional new total; keeps the previous total when omitted.
        """
        if self._ctx is None:
            return
        if total is not None:
            self._total = total
        self._step += 1
        try:
            ctx = self._ctx
            request_context = ctx.request_context
            token = request_context.meta.progressToken if request_context.meta else None
            if token is None:
                # The client did not opt in to progress for this request.
                return
            # NOTE: we deliberately do NOT use Context.report_progress here. That
            # helper omits ``related_request_id``, so the streamable-HTTP transport
            # routes the notification to the standalone GET stream. By tagging it
            # with the current request id, the notification instead rides the same
            # POST response stream as the tool result — which is the stream the
            # bundled OpenWebUI tool reads — so progress shows up live there.
            await ctx.session.send_progress_notification(
                progress_token=token,
                progress=self._step,
                total=self._total,
                message=message,
                related_request_id=ctx.request_id,
            )
        except Exception:
            # Progress is advisory: a missing progress token or a transport
            # hiccup must not break the tool itself.
            pass
