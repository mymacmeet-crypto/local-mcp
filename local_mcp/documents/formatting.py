"""Document parser result formatting."""

from __future__ import annotations

import json

from local_mcp.documents.models import ParseResult
from local_mcp.shared.errors import tool_error


def format_result(result: ParseResult, *, include_metadata: bool, max_chars: int) -> str:
    content, truncated = truncate(result.content, max_chars)
    warnings = list(result.warnings)
    if truncated:
        warnings.append(f"Content truncated to {max_chars} characters.")

    if result.output_format == "json":
        payload = {
            "parser": result.parser,
            "source": result.source,
            "output_format": result.output_format,
            "metadata": result.metadata,
            "warnings": warnings,
            "content": content,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    if not include_metadata:
        return content

    lines = [
        f"Parser: {result.parser}",
        f"Source: {result.source}",
        f"Output format: {result.output_format}",
    ]
    if result.metadata:
        lines.append("Metadata:")
        for key, value in result.metadata.items():
            lines.append(f"- {key}: {value}")
    if warnings:
        lines.append("Warnings:")
        lines.extend(f"- {warning}" for warning in warnings)
    return "\n".join(lines).strip() + "\n\n" + content


def truncate(content: str, max_chars: int) -> tuple[str, bool]:
    if max_chars <= 0 or len(content) <= max_chars:
        return content, False
    return content[:max_chars].rstrip(), True


def validate_choice(value: str, allowed: set[str], label: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized not in allowed:
        choices = ", ".join(sorted(allowed))
        raise tool_error(f"Unsupported {label}: {value}. Choose one of: {choices}.")
    return normalized


def json_string(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)
