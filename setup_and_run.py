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


def main() -> None:
    _ensure_supported_python()
    venv_python = _ensure_venv()
    _install_core(venv_python)
    _show_external_notes()
    _menu(venv_python)


def _ensure_supported_python() -> None:
    if sys.version_info < MIN_PYTHON:
        required = ".".join(str(part) for part in MIN_PYTHON)
        current = ".".join(str(part) for part in sys.version_info[:3])
        raise SystemExit(f"Python {required}+ is required. Current Python: {current}")


def _ensure_venv() -> Path:
    python_path = _venv_python()
    if python_path.exists():
        print(f"Using existing virtual environment: {VENV_DIR}")
        return python_path

    print(f"Creating virtual environment: {VENV_DIR}")
    venv.EnvBuilder(with_pip=True).create(VENV_DIR)
    return python_path


def _venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _install_core(python_path: Path) -> None:
    print("\nInstalling core dependencies...")
    _run([python_path, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])
    _run([python_path, "-m", "pip", "install", "-r", REQUIREMENTS_FILE])
    _run([python_path, "-m", "pip", "install", "-e", PROJECT_ROOT])
    print("Core install complete.\n")


def _show_external_notes() -> None:
    notes: list[str] = []
    if not _has_tesseract():
        notes.append("Tesseract was not found. Install it or set TESSERACT_CMD before using extract_image_text.")
    if not (os.environ.get("SEARXNG_BASE_URL") or os.environ.get("SEARXNG_URLS") or os.environ.get("LOCAL_MCP_SEARXNG_URLS")):
        notes.append("No SearXNG URL environment variable is set. web_search needs a reachable SearXNG instance.")

    if notes:
        print("External requirement notes:")
        for note in notes:
            print(f"- {note}")
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
        print("local-mcp options")
        print("1. Run MCP over stdio")
        print("2. Run MCP over HTTP at http://127.0.0.1:3002/mcp")
        print("3. Install browser fallback extra: local-mcp[browser]")
        print("4. Install fast document extras: local-mcp[document-fast]")
        print("5. Install all document extras")
        print("6. Run tests")
        print("0. Exit")
        choice = input("Choose an option: ").strip()

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
            _install_extra(python_path, "document-fast,document-structured,document-deep")
        elif choice == "6":
            _run([python_path, "-m", "unittest", "discover", "-s", "tests"], cwd=PROJECT_ROOT)
        elif choice == "0":
            print("Done.")
            return
        else:
            print("Unknown option. Try again.\n")


def _install_extra(python_path: Path, extra: str) -> None:
    package = f"{PROJECT_ROOT}[{extra}]"
    print(f"\nInstalling optional extra: {extra}")
    _run([python_path, "-m", "pip", "install", "-e", package])
    print(f"Optional extra installed: {extra}\n")


def _maybe_run_crawl4ai_setup() -> None:
    setup_exe = VENV_DIR / ("Scripts/crawl4ai-setup.exe" if os.name == "nt" else "bin/crawl4ai-setup")
    if not setup_exe.exists():
        print("crawl4ai-setup was not found in the virtual environment. Skipping browser setup.\n")
        return
    answer = input("Run crawl4ai-setup now? This can download browser assets. [y/N]: ").strip().lower()
    if answer == "y":
        _run([setup_exe], cwd=PROJECT_ROOT)


def _run(command: list[object], *, cwd: Path | None = None) -> None:
    printable = " ".join(str(part) for part in command)
    print(f"> {printable}")
    try:
        subprocess.check_call([str(part) for part in command], cwd=str(cwd or PROJECT_ROOT))
    except subprocess.CalledProcessError as err:
        raise SystemExit(f"Command failed with exit code {err.returncode}: {printable}") from err


if __name__ == "__main__":
    main()
