# `schedule_task`

Create and install a local scheduled task for `cron`, `systemd` user timers, `launchd`, or `n8n`.

The tool always writes a reviewable bundle first:

- `run.sh`: executable runner script.
- `cron/*.cron`: crontab line for Linux/macOS cron.
- `systemd/local-mcp-*.service` + `.timer`: systemd user units for Linux.
- `launchd/*.plist`: macOS LaunchAgent plist.
- `n8n/*.workflow.json`: n8n workflow import template.
- `README.md`: task summary and install instructions.

Then, by default (`install=true`), it installs the schedule:

- `cron`: adds a marker-tagged line to the current user's crontab.
- `systemd`: copies the units into `~/.config/systemd/user/` and runs `systemctl --user enable --now` (Linux only, no root needed).
- `launchd`: copies the plist into `~/Library/LaunchAgents` and bootstraps it (macOS only).
- `n8n`: never installed automatically; import the workflow JSON manually.

The default `scheduler` is `auto`: cron when `crontab` exists, otherwise systemd user timers on Linux or launchd on macOS. This means scheduling works out of the box on Fedora-like systems that ship without cronie.

The response says plainly whether the schedule is **installed and active** or **NOT installed** with the reason (install disabled, `crontab` binary missing, non-macOS launchd, n8n) and the manual step for the user.

Set `LOCAL_MCP_ENABLE_SCHEDULER_INSTALL=0` on the server to disallow automatic installs entirely; the tool then only generates files.

## Parameters

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `name` | string | required | Human-readable task name. Used to create a safe bundle slug. |
| `command` | string | required | Shell command or script body to run on the schedule. |
| `schedule` | string | required | Five-field cron expression, or alias: `hourly`, `daily`, `weekdays`, `weekly`, `monthly`, `nightly`, `midnight`, `every_minute`, `every_hour`. |
| `scheduler` | string | `auto` | Scheduler to use: `auto`, `cron`, `launchd`, `systemd`, or `n8n`. |
| `description` | string | empty | Optional description written into the generated README. |
| `working_directory` | string | empty | Optional working directory for `run.sh`. |
| `environment` | string | empty | Optional `KEY=VALUE` assignments, newline or comma separated. |
| `overwrite` | boolean | `false` | Replace existing generated files for the same task name. |
| `install` | boolean | `true` | Install the schedule after generating files. Set `false` to only generate reviewable files. |

## Companion tools

| Tool | Description |
| --- | --- |
| `list_scheduled_tasks` | List generated tasks with scheduler, cron expression, and installed status. |
| `delete_scheduled_task` | Uninstall a task by name and optionally delete its bundle files (`delete_files`, default `true`). |

The `simple` tool profile exposes the same functionality as `create_scheduled_command`, `list_scheduled_commands`, and `remove_scheduled_command` for weaker tool-calling models. `create_scheduled_command` uses the `auto` scheduler, installs immediately, and overwrites existing files for the same name so retries succeed.

## Output Location

Bundles are written under the first configured directory:

```text
LOCAL_MCP_AUTOMATION_DIR
LOCAL_MCP_FILE_OUTPUT_DIR
LOCAL_MCP_DOWNLOAD_DIR
.tmp/automations
```

## Examples

Create and install a daily cron report:

```json
{
  "name": "Morning report",
  "command": "python scripts/morning_report.py",
  "schedule": "daily",
  "scheduler": "cron",
  "working_directory": "/home/nayan/Documents/local-mcp"
}
```

Generate reviewable files only, without installing:

```json
{
  "name": "Weekday digest",
  "command": "python scripts/digest.py",
  "schedule": "weekdays",
  "scheduler": "cron",
  "install": false
}
```

Create an n8n import template:

```json
{
  "name": "Weekly research workflow",
  "command": "python scripts/research_digest.py",
  "schedule": "0 8 * * 1",
  "scheduler": "n8n"
}
```

Remove a task:

```json
{
  "name": "Morning report",
  "delete_files": true
}
```

## Requirements

- `cron` install needs the `crontab` binary. On Fedora: `sudo dnf install cronie && sudo systemctl enable --now crond`. On Debian/Ubuntu: `sudo apt install cron`. If it is missing, the tool reports it instead of failing — and `auto` avoids it entirely by using systemd.
- `systemd` install needs `systemctl` and a Linux user session (present on all modern Fedora/Ubuntu desktops). Timers use `Persistent=true`, so missed runs fire after wake/boot.
- `launchd` install only works on macOS.

## Safety Notes

- The generated command runs with the permissions of the user account that installs the schedule.
- Every crontab entry is tagged with a `# local-mcp:<slug>` marker, so `delete_scheduled_task` removes exactly what was installed and re-installing the same task never duplicates entries.
- The bundle (`run.sh`, README) is always written to disk for review, even when the schedule is installed automatically.
- Set `LOCAL_MCP_ENABLE_SCHEDULER_INSTALL=0` to force review-only behavior.
- `n8n` workflow activation is manual because n8n credentials, host paths, and command execution policy are deployment-specific.
