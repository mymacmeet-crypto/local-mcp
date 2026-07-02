"""Bootstrap local-mcp dependencies and offer run options.

Run from the repository root:

    python setup_and_run.py

The script creates or reuses `.venv`, installs the core runtime requirements
and this package, then shows a terminal menu for running the MCP server.
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
        venv_python = _ensure_venv()
        _install_core(venv_python)
        _show_external_notes()
        _menu(venv_python)
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


def _show_external_notes() -> None:
    notes: list[str] = []
    if not _has_tesseract():
        notes.append("Tesseract was not found. Install it or set TESSERACT_CMD before using extract_image_text.")
    if not (os.environ.get("SEARXNG_BASE_URL") or os.environ.get("SEARXNG_URLS") or os.environ.get("LOCAL_MCP_SEARXNG_URLS")):
        notes.append("No SearXNG URL environment variable is set. web_search needs a reachable SearXNG instance.")

    if notes:
        _heading("External requirement notes")
        for note in notes:
            _warning(f"- {note}")
        print()


def _has_tesseract() -> bool:
    if os.environ.get("TESSERACT_CMD"):
        return True
    if shutil.which("tesseract"):
        return True
    if os.name == "nt":
        for base_dir in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
            if base_dir and (Path(base_dir) / "Tesseract-OCR" / "tesseract.exe").is_file():
                return True
    return False


def _menu(python_path: Path) -> None:
    while True:
        _heading("local-mcp control panel")
        print(f"{_paint('Project', Style.DIM)}  {_paint(str(PROJECT_ROOT), Style.CYAN)}")
        print(f"{_paint('Python ', Style.DIM)}  {_paint(str(python_path), Style.CYAN)}")
        print()
        _menu_item("1", "Run MCP over stdio")
        _menu_item("2", "Run MCP over HTTP", "http://127.0.0.1:3002/mcp")
        _menu_item("3", "Install browser fallback extra", "local-mcp[browser]")
        _menu_item("4", "Install fast document extras", "local-mcp[document-fast]")
        _menu_item("5", "Install structured document extras", "local-mcp[document-structured]")
        _menu_item("6", "Install deep document extras (Marker)", "local-mcp[document-deep-marker]")
        _menu_item("7", "Install deep document extras (MinerU)", "local-mcp[document-deep-mineru]")
        _menu_item("8", "Upgrade pip, setuptools, and wheel")
        _menu_item("9", "Run tests")
        _menu_item("0", "Exit")
        print()
        choice = input(_paint("Choose an option: ", Style.BOLD, Style.GREEN)).strip()

        if choice == "1":
            _run([python_path, "server.py"], cwd=PROJECT_ROOT)
        elif choice == "2":
            _run([python_path, "server.py", "--http"], cwd=PROJECT_ROOT)
        elif choice == "3":
            _install_extra(python_path, "browser")
            _maybe_run_crawl4ai_setup()
        elif choice == "4":
            _install_extra(python_path, "document-fast")
        elif choice == "5":
            _install_extra(python_path, "document-structured")
        elif choice == "6":
            _install_extra(python_path, "document-deep-marker")
        elif choice == "7":
            _install_extra(python_path, "document-deep-mineru")
        elif choice == "8":
            _upgrade_packaging_tools(python_path)
        elif choice == "9":
            _run([python_path, "-m", "unittest", "discover", "-s", "tests"], cwd=PROJECT_ROOT)
        elif choice == "0":
            _success("Done.")
            return
        else:
            _warning("Unknown option. Try again.\n")


def _install_extra(python_path: Path, extra: str) -> None:
    package = f"{PROJECT_ROOT}[{extra}]"
    _heading(f"Installing optional extra: {extra}")
    _run([python_path, "-m", "pip", "install", "-e", package])
    _success(f"Optional extra installed: {extra}")


def _upgrade_packaging_tools(python_path: Path) -> None:
    _heading("Upgrading pip, setuptools, and wheel")
    _run([python_path, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])
    _success("Packaging tools upgraded.")


def _maybe_run_crawl4ai_setup() -> None:
    setup_exe = VENV_DIR / ("Scripts/crawl4ai-setup.exe" if os.name == "nt" else "bin/crawl4ai-setup")
    if not setup_exe.exists():
        _warning("crawl4ai-setup was not found in the virtual environment. Skipping browser setup.\n")
        return
    prompt = _paint("Run crawl4ai-setup now? This can download browser assets. [y/N]: ", Style.BOLD, Style.YELLOW)
    answer = input(prompt).strip().lower()
    if answer == "y":
        _run([setup_exe], cwd=PROJECT_ROOT)


def _run(command: list[object], *, cwd: Path | None = None) -> None:
    printable = " ".join(str(part) for part in command)
    print(_paint("> ", Style.GREEN, Style.BOLD) + _paint(printable, Style.CYAN))
    try:
        subprocess.check_call([str(part) for part in command], cwd=str(cwd or PROJECT_ROOT))
    except KeyboardInterrupt:
        raise SystemExit(_paint("\nCancelled by user.", Style.YELLOW))
    except subprocess.CalledProcessError as err:
        raise SystemExit(_error(f"Command failed with exit code {err.returncode}: {printable}")) from err


if __name__ == "__main__":
    main()
