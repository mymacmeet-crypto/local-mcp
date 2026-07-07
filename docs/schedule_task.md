# `schedule_task`

Create a local scheduled-task bundle for `cron`, `launchd`, or `n8n`.

This tool does not silently modify your scheduler. By default it writes reviewable files:

- `run.sh`: executable runner script.
- `cron/*.cron`: crontab line for Linux/macOS cron.
- `launchd/*.plist`: macOS LaunchAgent plist.
- `n8n/*.workflow.json`: n8n workflow import template.
- `README.md`: task summary and install instructions.

Automatic cron/launchd installation is disabled unless `LOCAL_MCP_ENABLE_SCHEDULER_INSTALL=1` is set.

## Parameters

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `name` | string | required | Human-readable task name. Used to create a safe bundle slug. |
| `command` | string | required | Shell command or script body to run on the schedule. |
| `schedule` | string | required | Five-field cron expression, or alias: `hourly`, `daily`, `weekdays`, `weekly`, `monthly`. |
| `scheduler` | string | `cron` | Scheduler artifact to generate: `cron`, `launchd`, or `n8n`. |
| `description` | string | empty | Optional description written into the generated README. |
| `working_directory` | string | empty | Optional working directory for `run.sh`. |
| `environment` | string | empty | Optional `KEY=VALUE` assignments, newline or comma separated. |
| `overwrite` | boolean | `false` | Replace existing generated files for the same task name. |
| `install` | boolean | `false` | Attempt to install cron/launchd after generating files. Requires `LOCAL_MCP_ENABLE_SCHEDULER_INSTALL=1`. |

## Output Location

Bundles are written under the first configured directory:

```text
LOCAL_MCP_AUTOMATION_DIR
LOCAL_MCP_FILE_OUTPUT_DIR
LOCAL_MCP_DOWNLOAD_DIR
.tmp/automations
```

## Examples

Create cron artifacts for a daily report:

```json
{
  "name": "Morning report",
  "command": "python scripts/morning_report.py",
  "schedule": "daily",
  "scheduler": "cron",
  "working_directory": "/home/nayan/Documents/local-mcp"
}
```

Create a macOS launchd plist:

```json
{
  "name": "Weekday digest",
  "command": "python scripts/digest.py",
  "schedule": "weekdays",
  "scheduler": "launchd"
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

## Installing

Review `run.sh` first:

```bash
sed -n '1,200p' /path/to/task/run.sh
```

Then run the install command returned by the tool.

To allow the tool itself to install cron/launchd when `install=true`:

```env
LOCAL_MCP_ENABLE_SCHEDULER_INSTALL=1
```

For n8n, import the generated workflow JSON manually, review the Execute Command node, then activate the workflow in n8n.

## Safety Notes

- The generated command runs with the permissions of the user account that installs the schedule.
- `install=false` is the default so the user can review files before enabling them.
- `n8n` workflow activation is manual because n8n credentials, host paths, and command execution policy are deployment-specific.
