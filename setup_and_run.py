"""Offer local-mcp setup, dependency, and run commands.

Run from the repository root:

    python setup_and_run.py

The script opens a terminal menu first. Dependency installation only happens
after the user chooses an install command.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
VENV_DIR = PROJECT_ROOT / ".venv"
REQUIREMENTS_FILE = PROJECT_ROOT / "requirements.txt"
SEARXNG_SETTINGS_FILE = PROJECT_ROOT / "searxng-settings.yml"
SEARXNG_CONTAINER_NAME = "local-searxng"
SEARXNG_IMAGE = "searxng/searxng:latest"
SEARXNG_HOST_PORT = "8888"
SEARXNG_CONTAINER_PORT = "8080"
MIN_PYTHON = (3, 10)
USE_COLOR = False


class Style:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    BLUE = "\033[34m"
    CYAN = "\033[36m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    WHITE = "\033[37m"


def main() -> None:
    try:
        _configure_terminal()
        _ensure_supported_python()
        _menu()
    except KeyboardInterrupt:
        raise SystemExit(_paint("\nCancelled by user.", Style.YELLOW))


def _configure_terminal() -> None:
    global USE_COLOR
    if os.environ.get("NO_COLOR"):
        USE_COLOR = False
        return
    _enable_windows_ansi()
    USE_COLOR = sys.stdout.isatty()


def _enable_windows_ansi() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass


def _paint(text: str, *styles: str) -> str:
    if not USE_COLOR:
        return text
    return "".join(styles) + text + Style.RESET


def _heading(text: str) -> None:
    print()
    print(_paint(text, Style.BOLD, Style.CYAN))
    print(_paint("-" * 72, Style.DIM))


def _info(text: str) -> None:
    print(_paint(text, Style.CYAN))


def _success(text: str) -> None:
    print(_paint(text, Style.GREEN))


def _warning(text: str) -> None:
    print(_paint(text, Style.YELLOW))


def _error(text: str) -> str:
    return _paint(text, Style.RED)


def _menu_item(number: str, label: str, detail: str = "") -> None:
    prefix = _paint(f"{number}.", Style.YELLOW, Style.BOLD)
    if detail:
        print(f"{prefix} {_paint(label, Style.WHITE)} {_paint(detail, Style.DIM)}")
    else:
        print(f"{prefix} {_paint(label, Style.WHITE)}")


def _ensure_supported_python() -> None:
    if sys.version_info < MIN_PYTHON:
        required = ".".join(str(part) for part in MIN_PYTHON)
        current = ".".join(str(part) for part in sys.version_info[:3])
        raise SystemExit(f"Python {required}+ is required. Current Python: {current}")


def _ensure_venv() -> Path:
    python_path = _venv_python()
    if python_path.exists():
        _info(f"Using existing virtual environment: {VENV_DIR}")
        return python_path

    _info(f"Creating virtual environment: {VENV_DIR}")
    venv.EnvBuilder(with_pip=True).create(VENV_DIR)
    return python_path


def _venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _install_core(python_path: Path) -> None:
    _heading("Installing core dependencies")
    _run([python_path, "-m", "pip", "install", "-r", REQUIREMENTS_FILE])
    _run([python_path, "-m", "pip", "install", "-e", PROJECT_ROOT])
    _success("Core install complete.")


def _menu() -> None:
    while True:
        python_path = _venv_python()
        _heading("local-mcp control panel")
        print(f"{_paint('Project', Style.DIM)}  {_paint(str(PROJECT_ROOT), Style.CYAN)}")
        print(f"{_paint('Python ', Style.DIM)}  {_paint(_venv_label(python_path), Style.CYAN)}")
        print()
        _menu_item("1", "Run MCP over stdio")
        _menu_item("2", "Run MCP over HTTP", "http://127.0.0.1:3002/mcp")
        _menu_item("3", "Install core dependencies", "required")
        _menu_item("4", "Install browser dependency", "Crawl4AI")
        _menu_item("5", "Install fast document parsers", "PyMuPDF4LLM + pdfplumber")
        _menu_item("6", "Install structured document parser", "Docling")
        _menu_item("7", "Install Marker parser", "conflicts with MinerU")
        _menu_item("8", "Install MinerU parser", "conflicts with Marker")
        _menu_item("9", "Install recommended bundle", "core + browser + fast docs + Docling")
        _menu_item("10", "Show installed tool status")
        _menu_item("11", "Run tests")
        _menu_item("12", "Restart SearXNG Docker", f"http://127.0.0.1:{SEARXNG_HOST_PORT}")
        _menu_item("0", "Exit")
        print()
        choice = input(_paint("Choose an option: ", Style.BOLD, Style.GREEN)).strip()

        if choice == "1":
            if python_path := _require_venv():
                _run([python_path, "-m", "local_mcp"], cwd=PROJECT_ROOT)
        elif choice == "2":
            if python_path := _require_venv():
                _run([python_path, "-m", "local_mcp", "--http"], cwd=PROJECT_ROOT)
        elif choice == "3":
            _install_core(_ensure_venv())
        elif choice == "4":
            _install_extra(_ensure_venv(), "browser")
            _maybe_run_crawl4ai_setup()
        elif choice == "5":
            _install_extra(_ensure_venv(), "document-fast")
        elif choice == "6":
            _install_extra(_ensure_venv(), "document-structured")
        elif choice == "7":
            _install_extra(_ensure_venv(), "document-deep-marker")
        elif choice == "8":
            _install_extra(_ensure_venv(), "document-deep-mineru")
        elif choice == "9":
            _install_recommended_bundle()
        elif choice == "10":
            _show_tool_status(_venv_python())
        elif choice == "11":
            if python_path := _require_venv():
                _run([python_path, "-m", "unittest", "discover", "-s", "tests"], cwd=PROJECT_ROOT)
        elif choice == "12":
            _restart_searxng_docker()
        elif choice == "0":
            _success("Done.")
            return
        else:
            _warning("Unknown option. Try again.\n")


def _venv_label(python_path: Path) -> str:
    suffix = "ready" if python_path.exists() else "not created"
    return f"{python_path} ({suffix})"


def _require_venv() -> Path | None:
    python_path = _venv_python()
    if python_path.exists():
        return python_path
    _warning("Virtual environment not found. Choose option 3 to install core dependencies first.\n")
    return None


def _install_extra(python_path: Path, extra: str) -> None:
    package = f"{PROJECT_ROOT}[{extra}]"
    _heading(f"Installing optional extra: {extra}")
    _run([python_path, "-m", "pip", "install", "-e", package])
    _success(f"Optional extra installed: {extra}")


def _install_recommended_bundle() -> None:
    python_path = _ensure_venv()
    _install_core(python_path)
    _install_extra(python_path, "browser")
    _maybe_run_crawl4ai_setup()
    _install_extra(python_path, "document-fast")
    _install_extra(python_path, "document-structured")
    _success("Recommended dependency bundle installed.")


def _maybe_run_crawl4ai_setup() -> None:
    setup_exe = VENV_DIR / ("Scripts/crawl4ai-setup.exe" if os.name == "nt" else "bin/crawl4ai-setup")
    if not setup_exe.exists():
        _warning("crawl4ai-setup was not found in the virtual environment. Skipping browser setup.\n")
        return
    prompt = _paint("Run crawl4ai-setup now? This can download browser assets. [y/N]: ", Style.BOLD, Style.YELLOW)
    answer = input(prompt).strip().lower()
    if answer == "y":
        _run([setup_exe], cwd=PROJECT_ROOT)


def _restart_searxng_docker() -> None:
    _heading("Restarting SearXNG Docker")
    if not SEARXNG_SETTINGS_FILE.is_file():
        _warning(f"Missing SearXNG settings file: {SEARXNG_SETTINGS_FILE}")
        return
    if not shutil.which("docker"):
        _warning("Docker CLI was not found. Install and start Docker Desktop, then try again.")
        return

    volume = f"{SEARXNG_SETTINGS_FILE.resolve().as_posix()}:/etc/searxng/settings.yml:ro"
    _run(["docker", "rm", "-f", SEARXNG_CONTAINER_NAME], cwd=PROJECT_ROOT, check=False)
    _run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            SEARXNG_CONTAINER_NAME,
            "-p",
            f"{SEARXNG_HOST_PORT}:{SEARXNG_CONTAINER_PORT}",
            "-v",
            volume,
            SEARXNG_IMAGE,
        ],
        cwd=PROJECT_ROOT,
    )
    _success(f"SearXNG is running at http://127.0.0.1:{SEARXNG_HOST_PORT}")
    _info(f"Set SEARXNG_BASE_URL=http://127.0.0.1:{SEARXNG_HOST_PORT} for web_search.")


def _show_tool_status(python_path: Path) -> None:
    _heading("Installed tool status")
    print(f"{_paint('Python', Style.DIM)}  {_paint(str(python_path), Style.CYAN)}")
    print()

    rows = [
        ("Core", "Virtual environment", python_path.exists(), "option 3"),
        ("Core", "local-mcp package", _python_module_available(python_path, "local_mcp"), "option 3"),
        ("Web", "crawl4ai browser fallback", _python_module_available(python_path, "crawl4ai"), "option 4"),
        ("Search", "Docker CLI", bool(shutil.which("docker")), "option 12"),
        ("Search", "SearXNG settings file", SEARXNG_SETTINGS_FILE.is_file(), "searxng-settings.yml"),
        ("Search", "SearXNG URL configured", _has_searxng_config(), f"set SEARXNG_BASE_URL=http://127.0.0.1:{SEARXNG_HOST_PORT}"),
        ("OCR", "Pillow", _python_module_available(python_path, "PIL"), "core dependency"),
        ("OCR", "pytesseract", _python_module_available(python_path, "pytesseract"), "core dependency"),
        ("OCR", "Tesseract executable", bool(_command_location("tesseract", "TESSERACT_CMD")), "install native Tesseract"),
        ("Documents", "pypdf", _python_module_available(python_path, "pypdf"), "core dependency"),
        ("Documents", "pymupdf4llm", _python_module_available(python_path, "pymupdf4llm"), "option 5"),
        ("Documents", "pdfplumber", _python_module_available(python_path, "pdfplumber"), "option 5"),
        ("Documents", "docling", _python_module_available(python_path, "docling"), "option 6"),
        ("Documents", "Marker CLI (marker_single)", bool(_command_location("marker_single", "LOCAL_MCP_MARKER_CMD")), "option 7"),
        ("Documents", "MinerU CLI (mineru)", bool(_command_location("mineru", "LOCAL_MCP_MINERU_CMD")), "option 8"),
        ("Files", "Markdown file generation", True, "built in"),
    ]

    print(f"{'Area':<12} {'Status':<16} {'Name':<32} Hint")
    print("-" * 78)
    for area, name, installed, hint in rows:
        status = _paint("installed", Style.GREEN) if installed else _paint("not installed", Style.YELLOW)
        print(f"{area:<12} {status:<16} {name:<32} {hint}")
    print()


def _python_module_available(python_path: Path, module_name: str) -> bool:
    script = (
        "import importlib.util, sys; "
        f"sys.exit(0 if importlib.util.find_spec({module_name!r}) else 1)"
    )
    try:
        completed = subprocess.run(
            [str(python_path), "-c", script],
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _has_searxng_config() -> bool:
    return bool(os.environ.get("SEARXNG_BASE_URL") or os.environ.get("SEARXNG_URLS") or os.environ.get("LOCAL_MCP_SEARXNG_URLS"))


def _command_location(command: str, env_var: str | None = None) -> str:
    if env_var and os.environ.get(env_var):
        configured = os.environ[env_var].strip()
        if _path_or_command_exists(configured):
            return configured
        return ""

    for candidate in _venv_command_candidates(command):
        if candidate.is_file():
            return str(candidate)

    discovered = shutil.which(command)
    if discovered:
        return discovered

    if command == "tesseract" and os.name == "nt":
        for base_dir in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
            if not base_dir:
                continue
            candidate = Path(base_dir) / "Tesseract-OCR" / "tesseract.exe"
            if candidate.is_file():
                return str(candidate)

    return ""


def _path_or_command_exists(value: str) -> bool:
    if not value:
        return False
    path = Path(value).expanduser()
    return path.is_file() or shutil.which(value) is not None


def _venv_command_candidates(command: str) -> list[Path]:
    scripts_dir = VENV_DIR / ("Scripts" if os.name == "nt" else "bin")
    if os.name == "nt":
        return [scripts_dir / f"{command}{suffix}" for suffix in (".exe", ".cmd", ".bat", "")]
    return [scripts_dir / command]


def _run(command: list[object], *, cwd: Path | None = None, check: bool = True) -> int:
    printable = " ".join(str(part) for part in command)
    print(_paint("> ", Style.GREEN, Style.BOLD) + _paint(printable, Style.CYAN))
    try:
        completed = subprocess.run([str(part) for part in command], cwd=str(cwd or PROJECT_ROOT), check=False)
    except KeyboardInterrupt:
        raise SystemExit(_paint("\nCancelled by user.", Style.YELLOW))
    except OSError as err:
        raise SystemExit(_error(f"Command failed to start: {printable}\n{err}")) from err

    if check and completed.returncode != 0:
        raise SystemExit(_error(f"Command failed with exit code {completed.returncode}: {printable}"))
    return completed.returncode


if __name__ == "__main__":
    main()
