"""Image OCR helpers backed by Tesseract."""

from __future__ import annotations

import asyncio
import base64
import binascii
import os
import re
import shutil
from io import BytesIO
from pathlib import Path
from urllib.parse import ParseResult, unquote, urlparse

import httpx

from errors import describe_fetch_error, tool_error
from fetcher import TIMEOUT_S, USER_AGENT

MAX_IMAGE_BYTES = int(os.environ.get("LOCAL_MCP_OCR_MAX_IMAGE_BYTES", str(20 * 1024 * 1024)))
TESSERACT_CONFIG = os.environ.get("LOCAL_MCP_TESSERACT_CONFIG", "")
BASE64_RE = re.compile(r"^[A-Za-z0-9+/=\s]+$")
LANG_RE = re.compile(r"^[A-Za-z0-9_+-]+$")
WINDOWS_DRIVE_PATH_RE = re.compile(r"^/[A-Za-z]:([\\/]|$)")
MODULE_DIR = Path(__file__).resolve().parent


async def extract_image_text(image: str, *, lang: str = "eng") -> str:
    """Extract text from an image source and return only OCR text."""
    language = _validate_language(lang)
    image_bytes = await _load_image_bytes(image)
    text = await asyncio.to_thread(_run_tesseract, image_bytes, language)
    return text.replace("\r\n", "\n").strip()


def _validate_language(lang: str) -> str:
    value = (lang or "").strip()
    if not value or not LANG_RE.fullmatch(value):
        raise tool_error("Tesseract language must be a language code like 'eng' or 'eng+hin'.")
    return value


async def _load_image_bytes(image: str) -> bytes:
    source = _clean_image_source(image)
    if not source:
        raise tool_error("Image path, URL, data URL, or base64 content is required.")

    parsed = urlparse(source)
    if parsed.scheme in ("http", "https"):
        return await _fetch_image(source)
    if parsed.scheme == "data":
        return _decode_data_url(source)

    image_bytes = _read_local_image(source, parsed)
    if image_bytes is not None:
        return image_bytes

    if _looks_like_base64(source):
        return _decode_base64(source)

    raise tool_error(f"Image not found or unsupported image source: {source}")


def _clean_image_source(image: str) -> str:
    source = (image or "").strip()
    if len(source) >= 2 and source[0] == source[-1] and source[0] in ("'", '"'):
        return source[1:-1].strip()
    return source


def _read_local_image(source: str, parsed: ParseResult) -> bytes | None:
    for path in _local_path_candidates(source, parsed):
        try:
            if not path.is_file():
                continue
            size = path.stat().st_size
            if size > MAX_IMAGE_BYTES:
                raise tool_error(f"Image is too large. Maximum size is {MAX_IMAGE_BYTES} bytes.")
            return path.read_bytes()
        except OSError as err:
            raise tool_error(f"Could not read image file: {err}")
    return None


def _local_path_candidates(source: str, parsed: ParseResult) -> list[Path]:
    if parsed.scheme == "file":
        path_source = _file_uri_to_path(parsed)
    else:
        path_source = source

    path = Path(path_source).expanduser()
    candidates = [path]
    if not path.is_absolute():
        candidates.append(Path.cwd() / path)
        candidates.append(MODULE_DIR / path)
    return _unique_paths(candidates)


def _file_uri_to_path(parsed: ParseResult) -> str:
    path = unquote(parsed.path)
    host = unquote(parsed.netloc)

    if os.name == "nt":
        if host and host.lower() != "localhost":
            if re.fullmatch(r"[A-Za-z]:", host):
                path = f"{host}{path}"
            else:
                path = f"//{host}{path}"
        if WINDOWS_DRIVE_PATH_RE.match(path):
            path = path[1:]
        return path

    if host and host.lower() != "localhost":
        raise tool_error("Only local file:// image URLs are supported.")
    return path


def _unique_paths(paths: list[Path]) -> list[Path]:
    unique_paths: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique_paths.append(path)
    return unique_paths


async def _fetch_image(url: str) -> bytes:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "image/*,*/*;q=0.8",
    }
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=TIMEOUT_S, headers=headers) as client:
            response = await client.get(url)
        response.raise_for_status()
    except Exception as err:
        raise tool_error(describe_fetch_error(err, url))

    content = response.content
    if len(content) > MAX_IMAGE_BYTES:
        raise tool_error(f"Image is too large. Maximum size is {MAX_IMAGE_BYTES} bytes.")
    return content


def _decode_data_url(source: str) -> bytes:
    header, separator, payload = source.partition(",")
    if not separator or ";base64" not in header.lower():
        raise tool_error("Only base64 image data URLs are supported.")
    return _decode_base64(payload)


def _looks_like_base64(source: str) -> bool:
    compact = "".join(source.split())
    return len(compact) >= 32 and len(compact) % 4 == 0 and bool(BASE64_RE.fullmatch(source))


def _decode_base64(payload: str) -> bytes:
    compact_payload = "".join(payload.split())
    try:
        data = base64.b64decode(compact_payload, validate=True)
    except binascii.Error:
        raise tool_error("Image base64 content is invalid.")
    if len(data) > MAX_IMAGE_BYTES:
        raise tool_error(f"Image is too large. Maximum size is {MAX_IMAGE_BYTES} bytes.")
    return data


def _run_tesseract(image_bytes: bytes, lang: str) -> str:
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except ImportError as err:
        raise RuntimeError("Pillow is required for image OCR. Install dependencies from requirements.txt.") from err

    try:
        import pytesseract
    except ImportError as err:
        raise RuntimeError("pytesseract is required for image OCR. Install dependencies from requirements.txt.") from err

    tesseract_cmd = os.environ.get("TESSERACT_CMD") or _find_tesseract_cmd()
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    try:
        with Image.open(BytesIO(image_bytes)) as image:
            prepared_image = ImageOps.exif_transpose(image)
            if prepared_image.mode not in ("RGB", "L"):
                prepared_image = prepared_image.convert("RGB")
            return pytesseract.image_to_string(prepared_image, lang=lang, config=TESSERACT_CONFIG)
    except pytesseract.TesseractNotFoundError as err:
        raise RuntimeError(
            "Tesseract OCR executable was not found. Install Tesseract or set TESSERACT_CMD to its executable path."
        ) from err
    except pytesseract.TesseractError as err:
        raise RuntimeError(f"Tesseract OCR failed: {err}") from err
    except UnidentifiedImageError as err:
        raise RuntimeError("The provided content is not a readable image.") from err
    except OSError as err:
        raise RuntimeError(f"Could not read image: {err}") from err


def _find_tesseract_cmd() -> str | None:
    discovered = shutil.which("tesseract")
    if discovered:
        return discovered

    candidate_dirs = [
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramFiles(x86)"),
        os.environ.get("LOCALAPPDATA"),
    ]
    for base_dir in candidate_dirs:
        if not base_dir:
            continue
        candidate = Path(base_dir) / "Tesseract-OCR" / "tesseract.exe"
        if candidate.is_file():
            return str(candidate)

    return None
