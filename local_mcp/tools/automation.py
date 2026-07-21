"""MCP tool handlers for scheduled tasks and automation bundles."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from local_mcp.automations import (
    AutomationBundle,
    create_automation_bundle,
    list_automation_bundles,
    remove_automation,
)
from local_mcp.shared.errors import tool_error

Scheduler = Literal["auto", "cron", "launchd", "systemd", "n8n"]


async def schedule_task(
    name: Annotated[
        str,
        Field(description="Human-readable task name, used to create a safe local bundle slug."),
    ],
    command: Annotated[
        str,
        Field(description="Shell command or script body to run on the schedule."),
    ],
    schedule: Annotated[
        str,
        Field(description="Five-field cron expression, or alias: hourly, daily, weekdays, weekly, monthly."),
    ],
    scheduler: Annotated[
        Scheduler,
        Field(
            description=(
                "Scheduler to use: auto, cron, launchd, systemd, or n8n. auto picks the best "
                "available scheduler on this host (cron, systemd user timers on Linux, launchd on macOS)."
            )
        ),
    ] = "auto",
    description: Annotated[
        str,
        Field(description="Optional task description written into the generated README."),
    ] = "",
    working_directory: Annotated[
        str,
        Field(description="Optional working directory for the generated runner script."),
    ] = "",
    environment: Annotated[
        str,
        Field(description="Optional environment variables as KEY=VALUE lines or comma-separated assignments."),
    ] = "",
    overwrite: Annotated[
        bool,
        Field(description="Replace existing generated files for this task."),
    ] = False,
    install: Annotated[
        bool,
        Field(
            description=(
                "Install the schedule after generating files (default true). Set false to only "
                "generate reviewable files. Set LOCAL_MCP_ENABLE_SCHEDULER_INSTALL=0 on the server "
                "to disallow installs. n8n is always manual import."
            )
        ),
    ] = True,
) -> str:
    """Create and install a cron, launchd, or n8n scheduled task for a recurring command."""
    try:
        bundle = create_automation_bundle(
            name=name,
            command=command,
            schedule=schedule,
            scheduler=scheduler,
            description=description,
            working_directory=working_directory,
            environment=environment,
            overwrite=overwrite,
            install=install,
        )
    except Exception as err:
        raise tool_error(str(err))

    return _format_bundle(bundle)


async def list_scheduled_tasks() -> str:
    """List scheduled tasks created by this server and whether each is installed."""
    try:
        bundles = list_automation_bundles()
    except Exception as err:
        raise tool_error(str(err))

    if not bundles:
        return "No scheduled tasks found."

    lines = ["Scheduled tasks:"]
    for bundle in bundles:
        status = "installed" if bundle["installed"] else "not installed"
        schedule = bundle["schedule"] or "-"
        lines.append(
            f"- {bundle['slug']}: scheduler={bundle['scheduler']}, schedule={schedule}, "
            f"status={status}, bundle={bundle['root']}"
        )
    return "\n".join(lines)


async def delete_scheduled_task(
    name: Annotated[
        str,
        Field(description="Task name or slug used when the task was created."),
    ],
    delete_files: Annotated[
        bool,
        Field(description="Also delete the generated bundle files, not just the installed schedule."),
    ] = True,
) -> str:
    """Uninstall a scheduled task created by schedule_task and optionally delete its files."""
    try:
        return remove_automation(name, delete_files=delete_files)
    except Exception as err:
        raise tool_error(str(err))


def _format_bundle(bundle: AutomationBundle) -> str:
    if bundle.installed:
        return "\n".join(
            [
                f"Scheduled task '{bundle.name}' is installed and active.",
                f"- Schedule (cron): {bundle.cron_expression}",
                f"- Command: {bundle.command}",
                f"- Scheduler: {bundle.scheduler}",
                f"- Logs: {bundle.root / 'logs'}",
                f"- Bundle directory: {bundle.root}",
                "",
                "The schedule is live. No terminal commands are needed.",
                "Use list_scheduled_tasks to review it or delete_scheduled_task to remove it.",
            ]
        )

    lines = [
        f"Scheduled task '{bundle.name}' was generated but is NOT installed yet.",
        f"- Reason: {bundle.install_message}",
        f"- Schedule (cron): {bundle.cron_expression}",
        f"- Command: {bundle.command}",
        f"- Scheduler: {bundle.scheduler}",
        f"- Bundle directory: {bundle.root}",
        "",
        "Files:",
    ]
    for label, path in sorted(bundle.files.items()):
        lines.append(f"- {label}: {path}")
    lines.append("")
    if bundle.scheduler == "n8n":
        lines.append(bundle.install_command)
    else:
        lines.extend(
            [
                "To activate it manually, the user can run:",
                f"```bash\n{bundle.install_command}\n```",
            ]
        )
    return "\n".join(lines)
