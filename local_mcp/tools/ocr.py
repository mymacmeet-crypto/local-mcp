"""MCP tool handler for image OCR."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from local_mcp.ocr import extract_image_text as extract_image_text_impl
from local_mcp.shared.errors import tool_error


async def extract_image_text(
    image: Annotated[
        str,
        Field(description="Image file path, image URL, data URL, or base64-encoded image content."),
    ],
    lang: Annotated[
        str,
        Field(description="Tesseract language code, for example 'eng' or 'eng+hin'."),
    ] = "eng",
) -> str:
    """Extract text from an image with Tesseract OCR."""
    try:
        return await extract_image_text_impl(image, lang=lang)
    except Exception as err:
        raise tool_error(str(err))
