"""MCP tool handlers for scheduled tasks and automation bundles."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from local_mcp.automations import AutomationBundle, create_automation_bundle
from local_mcp.shared.errors import tool_error

Scheduler = Literal["cron", "launchd", "n8n"]


async def schedule_task(
    name: Annotated[
        str,
        Field(description="Human-readable task name, used to create a safe local bundle slug."),
    ],
    command: Annotated[
        str,
        Field(description="Shell command or script body to run on the schedule. Review before installing."),
    ],
    schedule: Annotated[
        str,
        Field(description="Five-field cron expression, or alias: hourly, daily, weekdays, weekly, monthly."),
    ],
    scheduler: Annotated[
        Scheduler,
        Field(description="Scheduler artifact to generate: cron, launchd, or n8n."),
    ] = "cron",
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
                "Attempt to install cron/launchd after generating files. Requires "
                "LOCAL_MCP_ENABLE_SCHEDULER_INSTALL=1. n8n is always manual import."
            )
        ),
    ] = False,
) -> str:
    """Create a local cron, launchd, or n8n automation bundle for a recurring command."""
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


def _format_bundle(bundle: AutomationBundle) -> str:
    lines = [
        "Scheduled task automation generated.",
        f"- Name: {bundle.name}",
        f"- Slug: {bundle.slug}",
        f"- Scheduler: {bundle.scheduler}",
        f"- Schedule: {bundle.cron_expression}",
        f"- Bundle directory: {bundle.root}",
        f"- Installed: {'yes' if bundle.installed else 'no'}",
        f"- Install status: {bundle.install_message}",
        "",
        "Files:",
    ]
    for label, path in sorted(bundle.files.items()):
        lines.append(f"- {label}: {path}")
    lines.extend(
        [
            "",
            "Install command:",
            f"```bash\n{bundle.install_command}\n```",
            "Review the generated run.sh before enabling the schedule.",
        ]
    )
    return "\n".join(lines)
