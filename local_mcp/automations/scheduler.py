"""Create local cron, launchd, and n8n automation bundles."""

from __future__ import annotations

import itertools
import json
import os
import platform
import plistlib
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from local_mcp.file_generation.markdown import DOWNLOAD_DIR_ENV, OUTPUT_DIR_ENV

AUTOMATION_DIR_ENV = "LOCAL_MCP_AUTOMATION_DIR"
SCHEDULER_INSTALL_ENV = "LOCAL_MCP_ENABLE_SCHEDULER_INSTALL"
SUPPORTED_SCHEDULERS = {"cron", "launchd", "systemd", "n8n"}

_ALIASES = {
    "every_minute": "* * * * *",
    "minutely": "* * * * *",
    "@hourly": "0 * * * *",
    "hourly": "0 * * * *",
    "every_hour": "0 * * * *",
    "midnight": "0 0 * * *",
    "nightly": "0 2 * * *",
    "@daily": "0 9 * * *",
    "daily": "0 9 * * *",
    "every_day": "0 9 * * *",
    "weekday": "0 9 * * 1-5",
    "weekdays": "0 9 * * 1-5",
    "weekdays_morning": "0 9 * * 1-5",
    "@weekly": "0 9 * * 1",
    "weekly": "0 9 * * 1",
    "@monthly": "0 9 1 * *",
    "monthly": "0 9 1 * *",
}


@dataclass(frozen=True)
class AutomationBundle:
    name: str
    slug: str
    description: str
    scheduler: str
    schedule: str
    cron_expression: str
    command: str
    root: Path
    files: dict[str, Path]
    install_command: str
    installed: bool
    install_message: str


def create_automation_bundle(
    *,
    name: str,
    command: str,
    schedule: str,
    scheduler: str = "cron",
    description: str = "",
    working_directory: str = "",
    environment: str = "",
    overwrite: bool = False,
    install: bool = False,
) -> AutomationBundle:
    """Create a runnable automation bundle for cron, launchd, or n8n."""
    clean_name = _require_text(name, "name")
    clean_command = _require_text(command, "command")
    clean_scheduler = _normalize_scheduler(scheduler)
    cron_expression = normalize_schedule(schedule)
    slug = _slugify(clean_name)
    env_vars = parse_environment(environment)
    root = (_automation_root() / slug).resolve()
    logs_dir = root / "logs"
    script_path = root / "run.sh"

    files: dict[str, Path] = {}
    logs_dir.mkdir(parents=True, exist_ok=True)
    _write_text(
        script_path,
        _render_shell_script(
            name=clean_name,
            command=clean_command,
            working_directory=working_directory,
            environment=env_vars,
        ),
        overwrite=overwrite,
    )
    script_path.chmod(0o755)
    files["script"] = script_path

    if clean_scheduler == "cron":
        cron_path = root / "cron" / f"{slug}.cron"
        _write_text(
            cron_path,
            _render_cron_file(cron_expression, script_path, root / "logs" / f"{slug}.log", slug),
            overwrite=overwrite,
        )
        files["cron"] = cron_path
        install_command = _cron_install_command(cron_path, slug)
    elif clean_scheduler == "launchd":
        launchd_path = root / "launchd" / f"local-mcp.{slug}.plist"
        _write_bytes(
            launchd_path,
            _render_launchd_plist(
                slug=slug,
                cron_expression=cron_expression,
                script_path=script_path,
                log_path=root / "logs" / f"{slug}.log",
                error_log_path=root / "logs" / f"{slug}.err.log",
                working_directory=working_directory,
                environment=env_vars,
            ),
            overwrite=overwrite,
        )
        files["launchd"] = launchd_path
        install_command = _launchd_install_command(launchd_path)
    elif clean_scheduler == "systemd":
        unit_dir = root / "systemd"
        service_path = unit_dir / f"local-mcp-{slug}.service"
        timer_path = unit_dir / f"local-mcp-{slug}.timer"
        calendar = _cron_to_oncalendar(cron_expression)
        _write_text(
            service_path,
            _render_systemd_service(
                name=clean_name,
                script_path=script_path,
                log_path=root / "logs" / f"{slug}.log",
                error_log_path=root / "logs" / f"{slug}.err.log",
            ),
            overwrite=overwrite,
        )
        _write_text(
            timer_path,
            _render_systemd_timer(name=clean_name, calendar=calendar),
            overwrite=overwrite,
        )
        files["systemd_service"] = service_path
        files["systemd_timer"] = timer_path
        install_command = _systemd_install_command(service_path, timer_path, slug)
    else:
        workflow_path = root / "n8n" / f"{slug}.workflow.json"
        _write_text(
            workflow_path,
            _render_n8n_workflow(clean_name, clean_command, cron_expression, script_path),
            overwrite=overwrite,
        )
        files["n8n"] = workflow_path
        install_command = f"Import {shlex.quote(str(workflow_path))} in n8n, review the Execute Command node, then activate the workflow."

    readme_path = root / "README.md"
    _write_text(
        readme_path,
        _render_readme(
            name=clean_name,
            slug=slug,
            description=description,
            scheduler=clean_scheduler,
            schedule=schedule,
            cron_expression=cron_expression,
            command=clean_command,
            script_path=script_path,
            files=files,
            install_command=install_command,
        ),
        overwrite=overwrite,
    )
    files["readme"] = readme_path

    installed = False
    install_message = "Install not requested."
    if install:
        installed, install_message = _install_scheduler(
            scheduler=clean_scheduler,
            slug=slug,
            cron_expression=cron_expression,
            script_path=script_path,
            log_path=root / "logs" / f"{slug}.log",
            files=files,
        )

    return AutomationBundle(
        name=clean_name,
        slug=slug,
        description=(description or "").strip(),
        scheduler=clean_scheduler,
        schedule=(schedule or "").strip(),
        cron_expression=cron_expression,
        command=clean_command,
        root=root,
        files=files,
        install_command=install_command,
        installed=installed,
        install_message=install_message,
    )


def normalize_schedule(schedule: str) -> str:
    """Normalize aliases and validate a five-field cron expression."""
    clean = _require_text(schedule, "schedule").strip().lower()
    cron_expression = _ALIASES.get(clean, clean)
    fields = cron_expression.split()
    if len(fields) != 5:
        raise ValueError("schedule must be a five-field cron expression or an alias like hourly, daily, weekly, or monthly.")

    ranges = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))
    for field, (minimum, maximum) in zip(fields, ranges):
        _expand_cron_field(field, minimum, maximum)
    return " ".join(fields)


def parse_environment(environment: str) -> dict[str, str]:
    """Parse newline or comma separated KEY=VALUE environment assignments."""
    env: dict[str, str] = {}
    if not (environment or "").strip():
        return env

    chunks = re.split(r"[\n,]+", environment)
    for raw_chunk in chunks:
        chunk = raw_chunk.strip()
        if not chunk:
            continue
        if "=" not in chunk:
            raise ValueError("environment entries must use KEY=VALUE syntax.")
        key, value = chunk.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ValueError(f"Invalid environment variable name: {key!r}.")
        env[key] = value.strip()
    return env


def _normalize_scheduler(scheduler: str) -> str:
    normalized = (scheduler or "auto").strip().lower()
    if normalized in {"auto", "", "default"}:
        return _default_scheduler()
    if normalized not in SUPPORTED_SCHEDULERS:
        raise ValueError("scheduler must be one of: auto, cron, launchd, systemd, n8n.")
    return normalized


def _default_scheduler() -> str:
    """Pick the scheduler most likely to install successfully on this host."""
    if platform.system() == "Darwin":
        return "cron" if shutil.which("crontab") else "launchd"
    if shutil.which("crontab"):
        return "cron"
    if shutil.which("systemctl"):
        return "systemd"
    return "cron"


def _automation_root() -> Path:
    configured = (
        os.environ.get(AUTOMATION_DIR_ENV)
        or os.environ.get(OUTPUT_DIR_ENV)
        or os.environ.get(DOWNLOAD_DIR_ENV)
        or ".tmp/automations"
    )
    root = Path(configured).expanduser()
    if not root.is_absolute():
        root = Path.cwd() / root
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9_.-]+", "-", name.lower()).strip("-._")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        raise ValueError("name must contain at least one letter or number.")
    return slug[:80]


def _require_text(value: str, label: str) -> str:
    clean = (value or "").strip()
    if not clean:
        raise ValueError(f"{label} is required.")
    if "\x00" in clean:
        raise ValueError(f"{label} cannot contain null bytes.")
    return clean


def _write_text(path: Path, content: str, *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise ValueError(f"{path} already exists. Set overwrite=true to replace it.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def _write_bytes(path: Path, content: bytes, *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise ValueError(f"{path} already exists. Set overwrite=true to replace it.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _render_shell_script(
    *,
    name: str,
    command: str,
    working_directory: str,
    environment: dict[str, str],
) -> str:
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        f"# Generated by local-mcp for: {name}",
    ]
    clean_workdir = (working_directory or "").strip()
    if clean_workdir:
        lines.append(f"cd -- {shlex.quote(clean_workdir)}")
    for key, value in sorted(environment.items()):
        lines.append(f"export {key}={shlex.quote(value)}")
    lines.extend(["", command.strip(), ""])
    return "\n".join(lines)


def _render_cron_file(cron_expression: str, script_path: Path, log_path: Path, slug: str) -> str:
    line = _cron_line(cron_expression, script_path, log_path, slug)
    return "\n".join(
        [
            f"# local-mcp:{slug} cron entry",
            f"# local-mcp:{slug} task",
            f"# local-mcp:{slug} install with the command shown by schedule_task, or paste the line below into crontab -e.",
            line,
            "",
        ]
    )


def _cron_line(cron_expression: str, script_path: Path, log_path: Path, slug: str) -> str:
    return f"{cron_expression} {shlex.quote(str(script_path))} >> {shlex.quote(str(log_path))} 2>&1 # local-mcp:{slug}"


def _cron_install_command(cron_path: Path, slug: str) -> str:
    quoted = shlex.quote(str(cron_path))
    marker = shlex.quote(f"# local-mcp:{slug}")
    return f"(crontab -l 2>/dev/null | grep -v {marker}; cat {quoted}) | crontab -"


def _render_launchd_plist(
    *,
    slug: str,
    cron_expression: str,
    script_path: Path,
    log_path: Path,
    error_log_path: Path,
    working_directory: str,
    environment: dict[str, str],
) -> bytes:
    plist: dict[str, object] = {
        "Label": f"local-mcp.{slug}",
        "ProgramArguments": ["/bin/bash", str(script_path)],
        "RunAtLoad": False,
        "StandardOutPath": str(log_path),
        "StandardErrorPath": str(error_log_path),
    }
    clean_workdir = (working_directory or "").strip()
    if clean_workdir:
        plist["WorkingDirectory"] = clean_workdir
    if environment:
        plist["EnvironmentVariables"] = environment

    plist.update(_launchd_schedule(cron_expression))
    return plistlib.dumps(plist, sort_keys=True)


def _launchd_schedule(cron_expression: str) -> dict[str, object]:
    minute, hour, day, month, weekday = cron_expression.split()
    if minute == "*" and hour == "*" and day == "*" and month == "*" and weekday == "*":
        return {"StartInterval": 60}
    if minute.startswith("*/") and hour == "*" and day == "*" and month == "*" and weekday == "*":
        minutes = int(minute[2:])
        return {"StartInterval": minutes * 60}

    specs = {
        "Minute": _expand_cron_field(minute, 0, 59),
        "Hour": _expand_cron_field(hour, 0, 23),
        "Day": _expand_cron_field(day, 1, 31),
        "Month": _expand_cron_field(month, 1, 12),
        "Weekday": _normalize_launchd_weekdays(_expand_cron_field(weekday, 0, 7)),
    }
    value_lists = {
        key: values
        for key, values in specs.items()
        if values is not None
    }
    if not value_lists:
        return {"StartInterval": 60}

    keys = list(value_lists)
    intervals: list[dict[str, int]] = []
    for combination in itertools.product(*(value_lists[key] for key in keys)):
        intervals.append(dict(zip(keys, combination)))
        if len(intervals) > 512:
            raise ValueError("launchd schedule expands to too many calendar intervals. Use a simpler cron expression.")

    if len(intervals) == 1:
        return {"StartCalendarInterval": intervals[0]}
    return {"StartCalendarInterval": intervals}


def _normalize_launchd_weekdays(values: list[int] | None) -> list[int] | None:
    if values is None:
        return None
    return sorted({0 if value == 7 else value for value in values})


def _launchd_install_command(launchd_path: Path) -> str:
    quoted = shlex.quote(str(launchd_path))
    return f"launchctl bootstrap gui/$(id -u) {quoted}"


_WEEKDAY_NAMES = {0: "Sun", 1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat"}


def _cron_to_oncalendar(cron_expression: str) -> str:
    """Convert a five-field cron expression to a systemd OnCalendar value."""
    minute, hour, day, month, weekday = cron_expression.split()

    def fmt(values: list[int] | None) -> str:
        if values is None:
            return "*"
        return ",".join(f"{value:02d}" for value in values)

    minutes = fmt(_expand_cron_field(minute, 0, 59))
    hours = fmt(_expand_cron_field(hour, 0, 23))
    days = fmt(_expand_cron_field(day, 1, 31))
    months = fmt(_expand_cron_field(month, 1, 12))
    calendar = f"*-{months}-{days} {hours}:{minutes}:00"

    weekdays = _normalize_launchd_weekdays(_expand_cron_field(weekday, 0, 7))
    if weekdays is not None:
        names = ",".join(_WEEKDAY_NAMES[value] for value in weekdays)
        calendar = f"{names} {calendar}"
    return calendar


def _render_systemd_service(*, name: str, script_path: Path, log_path: Path, error_log_path: Path) -> str:
    return "\n".join(
        [
            "[Unit]",
            f"Description=local-mcp scheduled task: {name}",
            "",
            "[Service]",
            "Type=oneshot",
            f"ExecStart=/bin/bash {script_path}",
            f"StandardOutput=append:{log_path}",
            f"StandardError=append:{error_log_path}",
            "",
        ]
    )


def _render_systemd_timer(*, name: str, calendar: str) -> str:
    return "\n".join(
        [
            "[Unit]",
            f"Description=local-mcp timer: {name}",
            "",
            "[Timer]",
            f"OnCalendar={calendar}",
            "Persistent=true",
            "",
            "[Install]",
            "WantedBy=timers.target",
            "",
        ]
    )


def _systemd_unit_dir() -> Path:
    return Path.home() / ".config" / "systemd" / "user"


def _systemd_install_command(service_path: Path, timer_path: Path, slug: str) -> str:
    unit_dir = _systemd_unit_dir()
    return (
        f"mkdir -p {shlex.quote(str(unit_dir))} && "
        f"cp {shlex.quote(str(service_path))} {shlex.quote(str(timer_path))} {shlex.quote(str(unit_dir))}/ && "
        f"systemctl --user daemon-reload && "
        f"systemctl --user enable --now local-mcp-{slug}.timer"
    )


def _install_systemd(*, slug: str, files: dict[str, Path]) -> tuple[bool, str]:
    service_path = files.get("systemd_service")
    timer_path = files.get("systemd_timer")
    if service_path is None or timer_path is None:
        return False, "systemd install skipped because no unit files were generated."
    if platform.system() != "Linux":
        return False, "systemd install skipped because this host is not Linux."
    if shutil.which("systemctl") is None:
        return False, "systemctl command not found on this host."

    unit_dir = _systemd_unit_dir()
    unit_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(service_path, unit_dir / service_path.name)
    shutil.copy2(timer_path, unit_dir / timer_path.name)
    try:
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True, capture_output=True, text=True)
        subprocess.run(
            ["systemctl", "--user", "enable", "--now", timer_path.name],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as err:
        detail = (err.stderr or "").strip()
        return False, f"systemctl failed: {detail or err}"
    return True, f"Installed and started systemd user timer {timer_path.name}."


def _render_n8n_workflow(name: str, command: str, cron_expression: str, script_path: Path) -> str:
    workflow = {
        "name": f"local-mcp - {name}",
        "active": False,
        "settings": {"executionOrder": "v1"},
        "nodes": [
            {
                "parameters": {
                    "rule": {
                        "interval": [
                            {
                                "field": "cronExpression",
                                "expression": cron_expression,
                            }
                        ]
                    }
                },
                "id": "schedule-trigger",
                "name": "Schedule Trigger",
                "type": "n8n-nodes-base.scheduleTrigger",
                "typeVersion": 1.2,
                "position": [0, 0],
            },
            {
                "parameters": {"command": str(script_path)},
                "id": "run-command",
                "name": "Run Command",
                "type": "n8n-nodes-base.executeCommand",
                "typeVersion": 1,
                "position": [260, 0],
                "notes": f"Generated command body:\n{command.strip()}",
            },
        ],
        "connections": {
            "Schedule Trigger": {
                "main": [[{"node": "Run Command", "type": "main", "index": 0}]]
            }
        },
    }
    return json.dumps(workflow, ensure_ascii=False, indent=2) + "\n"


def _render_readme(
    *,
    name: str,
    slug: str,
    description: str,
    scheduler: str,
    schedule: str,
    cron_expression: str,
    command: str,
    script_path: Path,
    files: dict[str, Path],
    install_command: str,
) -> str:
    lines = [
        f"# {name}",
        "",
        "Generated by local-mcp.",
        "",
        f"- Slug: `{slug}`",
        f"- Scheduler: `{scheduler}`",
        f"- Schedule input: `{schedule}`",
        f"- Cron expression: `{cron_expression}`",
        f"- Runner script: `{script_path}`",
    ]
    if description.strip():
        lines.append(f"- Description: {description.strip()}")
    lines.extend(["", "## Files"])
    for label, path in sorted(files.items()):
        lines.append(f"- `{label}`: `{path}`")
    lines.extend(
        [
            "",
            "## Install",
            "",
            "Review the script before installing:",
            "",
            "```bash",
            f"sed -n '1,200p' {shlex.quote(str(script_path))}",
            "```",
            "",
            "Install command:",
            "",
            "```bash",
            install_command,
            "```",
            "",
            "## Command",
            "",
            "```bash",
            command.strip(),
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def _install_scheduler(
    *,
    scheduler: str,
    slug: str,
    cron_expression: str,
    script_path: Path,
    log_path: Path,
    files: dict[str, Path],
) -> tuple[bool, str]:
    if not scheduler_install_allowed():
        return False, (
            f"Install disabled by {SCHEDULER_INSTALL_ENV}. Unset it or set it to 1 to allow local scheduler changes."
        )
    if scheduler == "cron":
        if shutil.which("crontab") is None:
            return False, (
                "crontab command not found on this host. Install cron first (for example "
                "`sudo dnf install cronie` on Fedora or `sudo apt install cron` on Debian/Ubuntu), "
                "then re-run schedule_task with overwrite=true."
            )
        try:
            _install_cron(cron_expression, script_path, log_path, slug)
        except subprocess.CalledProcessError as err:
            detail = (err.stderr or "").strip()
            return False, f"crontab update failed: {detail or err}"
        return True, "Installed into the current user's crontab."
    if scheduler == "systemd":
        return _install_systemd(slug=slug, files=files)
    if scheduler == "launchd":
        launchd_path = files.get("launchd")
        if platform.system() != "Darwin":
            return False, "launchd install skipped because this host is not macOS."
        if launchd_path is None:
            return False, "launchd install skipped because no plist was generated."
        destination = Path.home() / "Library" / "LaunchAgents" / launchd_path.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(launchd_path, destination)
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(destination)], capture_output=True, text=True)
        try:
            subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(destination)], check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as err:
            detail = (err.stderr or "").strip()
            return False, f"launchctl bootstrap failed: {detail or err}"
        return True, f"Installed launchd agent at {destination}."
    return False, "n8n workflows cannot be installed automatically. Import the generated workflow JSON in n8n."


def scheduler_install_allowed() -> bool:
    """Installs are allowed unless LOCAL_MCP_ENABLE_SCHEDULER_INSTALL is explicitly disabled."""
    value = (os.environ.get(SCHEDULER_INSTALL_ENV) or "").strip().lower()
    if not value:
        return True
    return value not in {"0", "false", "no", "off"}


def list_automation_bundles() -> list[dict[str, object]]:
    """List generated automation bundles and whether each is installed in cron."""
    root = _automation_root()
    installed = _installed_cron_slugs()
    bundles: list[dict[str, object]] = []
    for path in sorted(root.iterdir()):
        if not path.is_dir() or not (path / "run.sh").is_file():
            continue
        slug = path.name
        scheduler_name = next(
            (candidate for candidate in ("cron", "launchd", "systemd", "n8n") if (path / candidate).is_dir()),
            "unknown",
        )
        cron_expression = ""
        cron_file = path / "cron" / f"{slug}.cron"
        if cron_file.is_file():
            for line in cron_file.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    cron_expression = " ".join(stripped.split()[:5])
                    break
        timer_file = path / "systemd" / f"local-mcp-{slug}.timer"
        if not cron_expression and timer_file.is_file():
            for line in timer_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("OnCalendar="):
                    cron_expression = line.removeprefix("OnCalendar=")
                    break
        is_installed = slug in installed
        if scheduler_name == "systemd":
            is_installed = (_systemd_unit_dir() / f"local-mcp-{slug}.timer").is_file()
        bundles.append(
            {
                "slug": slug,
                "scheduler": scheduler_name,
                "schedule": cron_expression,
                "root": path,
                "installed": is_installed,
            }
        )
    return bundles


def remove_automation(name: str, *, delete_files: bool = False) -> str:
    """Uninstall a scheduled task by name or slug and optionally delete its bundle files."""
    slug = _slugify(name)
    marker = f"# local-mcp:{slug}"
    actions: list[str] = []

    if shutil.which("crontab") is not None:
        existing = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        if existing.returncode == 0 and marker in existing.stdout:
            kept = [line for line in existing.stdout.splitlines() if marker not in line]
            payload = "\n".join(kept).rstrip()
            payload = payload + "\n" if payload else ""
            subprocess.run(["crontab", "-"], input=payload, text=True, check=True, capture_output=True)
            actions.append("Removed the crontab entry.")

    if platform.system() == "Darwin":
        agent = Path.home() / "Library" / "LaunchAgents" / f"local-mcp.{slug}.plist"
        if agent.exists():
            subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(agent)], capture_output=True, text=True)
            agent.unlink()
            actions.append(f"Removed launchd agent {agent}.")

    unit_dir = _systemd_unit_dir()
    timer_unit = unit_dir / f"local-mcp-{slug}.timer"
    service_unit = unit_dir / f"local-mcp-{slug}.service"
    if timer_unit.exists() or service_unit.exists():
        if shutil.which("systemctl") is not None:
            subprocess.run(
                ["systemctl", "--user", "disable", "--now", timer_unit.name],
                capture_output=True,
                text=True,
            )
        for unit in (timer_unit, service_unit):
            if unit.exists():
                unit.unlink()
        if shutil.which("systemctl") is not None:
            subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True, text=True)
        actions.append(f"Removed systemd user timer {timer_unit.name}.")

    bundle_dir = _automation_root() / slug
    if delete_files and bundle_dir.is_dir():
        shutil.rmtree(bundle_dir)
        actions.append(f"Deleted bundle directory {bundle_dir}.")

    if not actions:
        return f"No installed schedule or generated files found for '{slug}'."
    return f"Scheduled task '{slug}' removed. " + " ".join(actions)


def _installed_cron_slugs() -> set[str]:
    if shutil.which("crontab") is None:
        return set()
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    if result.returncode != 0:
        return set()
    return set(re.findall(r"# local-mcp:([A-Za-z0-9_.-]+)", result.stdout))


def _install_cron(cron_expression: str, script_path: Path, log_path: Path, slug: str) -> None:
    existing = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    lines = existing.stdout.splitlines() if existing.returncode == 0 else []
    marker = f"# local-mcp:{slug}"
    updated = [line for line in lines if marker not in line]
    updated.append(_cron_line(cron_expression, script_path, log_path, slug))
    payload = "\n".join(updated).rstrip() + "\n"
    subprocess.run(["crontab", "-"], input=payload, text=True, check=True, capture_output=True)


def _expand_cron_field(field: str, minimum: int, maximum: int) -> list[int] | None:
    clean = field.strip()
    if clean == "*":
        return None
    values: set[int] = set()
    for part in clean.split(","):
        values.update(_expand_cron_part(part.strip(), minimum, maximum))
    if not values:
        raise ValueError(f"Invalid cron field: {field!r}.")
    return sorted(values)


def _expand_cron_part(part: str, minimum: int, maximum: int) -> list[int]:
    if not part:
        raise ValueError("Cron fields cannot contain empty list entries.")

    step = 1
    base = part
    if "/" in part:
        base, step_value = part.split("/", 1)
        if not step_value.isdigit() or int(step_value) <= 0:
            raise ValueError(f"Invalid cron step in {part!r}.")
        step = int(step_value)

    if base == "*":
        start, end = minimum, maximum
    elif "-" in base:
        start_value, end_value = base.split("-", 1)
        if not start_value.isdigit() or not end_value.isdigit():
            raise ValueError(f"Invalid cron range in {part!r}.")
        start, end = int(start_value), int(end_value)
    elif base.isdigit():
        start = end = int(base)
    else:
        raise ValueError(f"Invalid cron value {part!r}; use numbers, *, ranges, lists, or steps.")

    if start < minimum or end > maximum or start > end:
        raise ValueError(f"Cron value {part!r} is outside allowed range {minimum}-{maximum}.")
    return list(range(start, end + 1, step))
