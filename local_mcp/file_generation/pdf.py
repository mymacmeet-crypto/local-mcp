"""Small text PDF renderer for generated files."""

from __future__ import annotations

import html
import re
import textwrap
from pathlib import Path


PAGE_WIDTH = 612
PAGE_HEIGHT = 792
MARGIN_X = 72
MARGIN_TOP = 72
MARGIN_BOTTOM = 72
FOOTER_Y = 38
BODY_WIDTH = PAGE_WIDTH - (MARGIN_X * 2)


def render_text_pdf(content: str, *, title: str = "") -> bytes:
    """Render Markdown-like text content into a simple, valid PDF document."""
    source_content = content or ""
    if not source_content.strip() and title:
        source_content = f"# {title}"
    lines = _markdown_to_pdf_lines(source_content)
    pages = _paginate(lines)
    page_count = len(pages)
    streams = [
        _build_page_stream(page, page_number=index + 1, page_count=page_count)
        for index, page in enumerate(pages)
    ]
    return _assemble_pdf(streams)


def default_pdf_title(filename: str | Path) -> str:
    stem = Path(filename).stem.replace("_", " ").replace("-", " ").strip()
    return stem.title() if stem else "Generated Document"


def _markdown_to_pdf_lines(content: str) -> list[dict[str, object]]:
    pdf_lines: list[dict[str, object]] = []
    in_code_block = False

    for raw_line in content.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()

        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue

        if in_code_block:
            pdf_lines.extend(_wrap_pdf_text(line or " ", font="F3", size=9, leading=12, indent=12))
            continue

        if not stripped:
            pdf_lines.append(_pdf_line("", leading=8))
            continue

        heading = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading:
            level = len(heading.group(1))
            text = _strip_inline_markdown(heading.group(2))
            size = {1: 18, 2: 15, 3: 13}.get(level, 11.5)
            pdf_lines.extend(
                _wrap_pdf_text(
                    text,
                    font="F2",
                    size=size,
                    leading=size + 6,
                    gap_before=8 if pdf_lines else 0,
                )
            )
            continue

        bullet = re.match(r"^(\s*)[-*+]\s+(.+)$", line)
        if bullet:
            indent = min(len(bullet.group(1)) * 3, 36)
            text = f"- {_strip_inline_markdown(bullet.group(2))}"
            pdf_lines.extend(_wrap_pdf_text(text, indent=indent, hanging_indent=12))
            continue

        numbered = re.match(r"^(\s*)(\d+[.)])\s+(.+)$", line)
        if numbered:
            indent = min(len(numbered.group(1)) * 3, 36)
            text = f"{numbered.group(2)} {_strip_inline_markdown(numbered.group(3))}"
            pdf_lines.extend(_wrap_pdf_text(text, indent=indent, hanging_indent=18))
            continue

        quote = re.match(r"^>\s*(.+)$", stripped)
        if quote:
            pdf_lines.extend(
                _wrap_pdf_text(
                    _strip_inline_markdown(quote.group(1)),
                    font="F1",
                    size=10.5,
                    leading=14,
                    indent=18,
                )
            )
            continue

        if stripped.startswith("|") and stripped.endswith("|"):
            pdf_lines.extend(_wrap_pdf_text(stripped, font="F3", size=8.5, leading=11))
            continue

        pdf_lines.extend(_wrap_pdf_text(_strip_inline_markdown(stripped)))

    if not pdf_lines:
        pdf_lines.append(_pdf_line(""))
    return pdf_lines


def _strip_inline_markdown(text: str) -> str:
    cleaned = html.unescape(text)
    cleaned = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", cleaned)
    cleaned = re.sub(r"`([^`]*)`", r"\1", cleaned)
    cleaned = re.sub(r"</?[^>]+>", "", cleaned)
    for marker in ("**", "__", "*", "_"):
        cleaned = cleaned.replace(marker, "")
    return " ".join(cleaned.split())


def _wrap_pdf_text(
    text: str,
    *,
    font: str = "F1",
    size: float = 10.5,
    leading: float = 14,
    indent: float = 0,
    hanging_indent: float = 0,
    gap_before: float = 0,
) -> list[dict[str, object]]:
    available_width = max(120, BODY_WIDTH - indent)
    average_char_width = size * (0.6 if font == "F3" else 0.52)
    wrap_width = max(20, int(available_width / average_char_width))
    wrapped = textwrap.wrap(
        text or " ",
        width=wrap_width,
        break_long_words=True,
        break_on_hyphens=False,
        replace_whitespace=True,
        drop_whitespace=True,
    )
    if not wrapped:
        wrapped = [""]

    return [
        _pdf_line(
            part,
            font=font,
            size=size,
            leading=leading,
            indent=indent if index == 0 else indent + hanging_indent,
            gap_before=gap_before if index == 0 else 0,
        )
        for index, part in enumerate(wrapped)
    ]


def _pdf_line(
    text: str,
    *,
    font: str = "F1",
    size: float = 10.5,
    leading: float = 14,
    indent: float = 0,
    gap_before: float = 0,
) -> dict[str, object]:
    return {
        "text": text,
        "font": font,
        "size": size,
        "leading": leading,
        "indent": indent,
        "gap_before": gap_before,
    }


def _paginate(lines: list[dict[str, object]]) -> list[list[tuple[dict[str, object], float]]]:
    pages: list[list[tuple[dict[str, object], float]]] = []
    current: list[tuple[dict[str, object], float]] = []
    y = PAGE_HEIGHT - MARGIN_TOP

    for line in lines:
        gap_before = float(line["gap_before"])
        leading = float(line["leading"])
        needed = gap_before + leading
        if current and y - needed < MARGIN_BOTTOM:
            pages.append(current)
            current = []
            y = PAGE_HEIGHT - MARGIN_TOP

        y -= gap_before
        current.append((line, y))
        y -= leading

    pages.append(current)
    return pages


def _build_page_stream(
    page: list[tuple[dict[str, object], float]],
    *,
    page_number: int,
    page_count: int,
) -> bytes:
    operations = ["q"]
    for line, y in page:
        text = str(line["text"])
        if not text:
            continue
        x = MARGIN_X + float(line["indent"])
        font = str(line["font"])
        size = float(line["size"])
        operations.append(f"BT /{font} {size:g} Tf {x:.2f} {y:.2f} Td {_pdf_literal(text)} Tj ET")

    footer = f"Page {page_number} of {page_count}"
    operations.append(f"BT /F1 8 Tf {MARGIN_X:.2f} {FOOTER_Y:.2f} Td {_pdf_literal(footer)} Tj ET")
    operations.append("Q")
    return "\n".join(operations).encode("ascii")


def _pdf_literal(text: str) -> str:
    raw = text.encode("cp1252", errors="replace")
    escaped: list[str] = []
    for value in raw:
        if value in (40, 41, 92):
            escaped.append("\\" + chr(value))
        elif value in (9, 10, 13) or value < 32 or value > 126:
            escaped.append(f"\\{value:03o}")
        else:
            escaped.append(chr(value))
    return "(" + "".join(escaped) + ")"


def _assemble_pdf(page_streams: list[bytes]) -> bytes:
    page_ids = [6 + index * 2 for index in range(len(page_streams))]
    content_ids = [page_id + 1 for page_id in page_ids]
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)

    objects: list[tuple[int, bytes]] = [
        (1, b"<< /Type /Catalog /Pages 2 0 R >>"),
        (2, f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("ascii")),
        (3, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"),
        (4, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>"),
        (5, b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>"),
    ]

    resources = "<< /Font << /F1 3 0 R /F2 4 0 R /F3 5 0 R >> >>"
    for page_id, content_id, stream in zip(page_ids, content_ids, page_streams):
        page_body = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
            f"/Resources {resources} /Contents {content_id} 0 R >>"
        ).encode("ascii")
        content_body = b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream"
        objects.append((page_id, page_body))
        objects.append((content_id, content_body))

    return _write_pdf_objects(objects)


def _write_pdf_objects(objects: list[tuple[int, bytes]]) -> bytes:
    output = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}

    for object_id, body in objects:
        offsets[object_id] = len(output)
        output.extend(f"{object_id} 0 obj\n".encode("ascii"))
        output.extend(body)
        output.extend(b"\nendobj\n")

    max_id = max(offsets)
    startxref = len(output)
    output.extend(f"xref\n0 {max_id + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for object_id in range(1, max_id + 1):
        output.extend(f"{offsets[object_id]:010d} 00000 n \n".encode("ascii"))

    output.extend(
        f"trailer\n<< /Size {max_id + 1} /Root 1 0 R >>\nstartxref\n{startxref}\n%%EOF\n".encode("ascii")
    )
    return bytes(output)
