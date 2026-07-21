import json
import plistlib
import subprocess
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from local_mcp.automations import create_automation_bundle, list_automation_bundles, remove_automation
from local_mcp.automations.scheduler import _cron_to_oncalendar, normalize_schedule
from local_mcp.tools.automation import delete_scheduled_task, list_scheduled_tasks, schedule_task
from local_mcp.tools.simple import create_scheduled_command, remove_scheduled_command


class FakeCrontab:
    """Records crontab invocations and simulates an installed crontab payload."""

    def __init__(self, initial: str = ""):
        self.payload = initial
        self.calls: list[list[str]] = []

    def run(self, cmd, **kwargs):
        self.calls.append(list(cmd))
        if cmd[:2] == ["crontab", "-l"]:
            if self.payload:
                return subprocess.CompletedProcess(cmd, 0, self.payload, "")
            return subprocess.CompletedProcess(cmd, 1, "", "no crontab for user")
        if cmd[:2] == ["crontab", "-"]:
            self.payload = kwargs.get("input", "")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        raise AssertionError(f"Unexpected command: {cmd}")


class AutomationBundleTests(unittest.TestCase):
    def tempdir(self):
        root = Path.cwd() / ".tmp" / "unit-tests" / f"{self._testMethodName}-{uuid.uuid4().hex}"
        root.mkdir(parents=True)
        return str(root)

    def test_normalize_schedule_accepts_aliases_and_cron(self):
        self.assertEqual(normalize_schedule("daily"), "0 9 * * *")
        self.assertEqual(normalize_schedule("every_minute"), "* * * * *")
        self.assertEqual(normalize_schedule("*/15 * * * *"), "*/15 * * * *")

    def test_normalize_schedule_rejects_invalid_values(self):
        with self.assertRaisesRegex(ValueError, "outside allowed range"):
            normalize_schedule("90 * * * *")

        with self.assertRaisesRegex(ValueError, "five-field"):
            normalize_schedule("every morning")

    def test_create_cron_bundle_writes_runner_and_cron_file(self):
        tmp = self.tempdir()

        with patch.dict("os.environ", {"LOCAL_MCP_AUTOMATION_DIR": tmp}, clear=True):
            bundle = create_automation_bundle(
                name="Morning Report",
                command="python report.py",
                schedule="daily",
                scheduler="cron",
                working_directory="/tmp/project",
                environment="FOO=bar\nBAZ=qux",
            )

        script = bundle.files["script"]
        cron_file = bundle.files["cron"]

        self.assertEqual(bundle.slug, "morning-report")
        self.assertEqual(bundle.cron_expression, "0 9 * * *")
        self.assertTrue(script.is_file())
        self.assertTrue(cron_file.is_file())
        self.assertIn("cd -- /tmp/project", script.read_text(encoding="utf-8"))
        self.assertIn("export FOO=bar", script.read_text(encoding="utf-8"))
        self.assertIn("python report.py", script.read_text(encoding="utf-8"))
        self.assertIn("# local-mcp:morning-report", cron_file.read_text(encoding="utf-8"))
        self.assertIn("crontab", bundle.install_command)

    def test_create_launchd_bundle_writes_plist(self):
        tmp = self.tempdir()

        with patch.dict("os.environ", {"LOCAL_MCP_AUTOMATION_DIR": tmp}, clear=True):
            bundle = create_automation_bundle(
                name="Weekday Sync",
                command="bash sync.sh",
                schedule="weekdays",
                scheduler="launchd",
            )

        plist = plistlib.loads(bundle.files["launchd"].read_bytes())

        self.assertEqual(plist["Label"], "local-mcp.weekday-sync")
        self.assertEqual(plist["ProgramArguments"][0], "/bin/bash")
        self.assertIsInstance(plist["StartCalendarInterval"], list)
        self.assertEqual(len(plist["StartCalendarInterval"]), 5)
        self.assertIn("launchctl bootstrap", bundle.install_command)

    def test_create_n8n_bundle_writes_importable_json_template(self):
        tmp = self.tempdir()

        with patch.dict("os.environ", {"LOCAL_MCP_AUTOMATION_DIR": tmp}, clear=True):
            bundle = create_automation_bundle(
                name="Research Digest",
                command="python digest.py",
                schedule="0 7 * * 1",
                scheduler="n8n",
            )

        workflow = json.loads(bundle.files["n8n"].read_text(encoding="utf-8"))

        self.assertEqual(workflow["name"], "local-mcp - Research Digest")
        self.assertFalse(workflow["active"])
        self.assertEqual(workflow["nodes"][0]["type"], "n8n-nodes-base.scheduleTrigger")
        self.assertEqual(
            workflow["nodes"][0]["parameters"]["rule"]["interval"][0]["expression"],
            "0 7 * * 1",
        )
        self.assertEqual(workflow["nodes"][1]["type"], "n8n-nodes-base.executeCommand")

    def test_cron_to_oncalendar_conversion(self):
        self.assertEqual(_cron_to_oncalendar("0 9 * * *"), "*-*-* 09:00:00")
        self.assertEqual(_cron_to_oncalendar("*/15 * * * *"), "*-*-* *:00,15,30,45:00")
        self.assertEqual(_cron_to_oncalendar("0 9 * * 1-5"), "Mon,Tue,Wed,Thu,Fri *-*-* 09:00:00")
        self.assertEqual(_cron_to_oncalendar("30 6 1 * *"), "*-*-01 06:30:00")

    def test_create_systemd_bundle_writes_unit_files(self):
        tmp = self.tempdir()

        with patch.dict("os.environ", {"LOCAL_MCP_AUTOMATION_DIR": tmp}, clear=True):
            bundle = create_automation_bundle(
                name="Journal Sync",
                command="python sync.py",
                schedule="daily",
                scheduler="systemd",
                install=False,
            )

        service = bundle.files["systemd_service"].read_text(encoding="utf-8")
        timer = bundle.files["systemd_timer"].read_text(encoding="utf-8")

        self.assertIn("Type=oneshot", service)
        self.assertIn("run.sh", service)
        self.assertIn("OnCalendar=*-*-* 09:00:00", timer)
        self.assertIn("Persistent=true", timer)
        self.assertIn("systemctl --user enable --now local-mcp-journal-sync.timer", bundle.install_command)

    def test_auto_scheduler_falls_back_to_systemd_without_crontab(self):
        tmp = self.tempdir()

        def which(binary):
            return "/usr/bin/systemctl" if binary == "systemctl" else None

        with patch.dict("os.environ", {"LOCAL_MCP_AUTOMATION_DIR": tmp}, clear=True):
            with patch("local_mcp.automations.scheduler.shutil.which", side_effect=which):
                with patch("local_mcp.automations.scheduler.platform.system", return_value="Linux"):
                    bundle = create_automation_bundle(
                        name="Auto Pick",
                        command="echo hi",
                        schedule="hourly",
                        scheduler="auto",
                        install=False,
                    )

        self.assertEqual(bundle.scheduler, "systemd")
        self.assertIn("systemd_timer", bundle.files)

    def test_install_runs_by_default_and_updates_crontab(self):
        tmp = self.tempdir()
        fake = FakeCrontab()

        with patch.dict("os.environ", {"LOCAL_MCP_AUTOMATION_DIR": tmp}, clear=True):
            with patch("local_mcp.automations.scheduler.subprocess.run", side_effect=fake.run):
                with patch("local_mcp.automations.scheduler.shutil.which", return_value="/usr/bin/crontab"):
                    bundle = create_automation_bundle(
                        name="Install Default",
                        command="echo hi",
                        schedule="hourly",
                        scheduler="cron",
                        install=True,
                    )

        self.assertTrue(bundle.installed)
        self.assertIn("crontab", bundle.install_message)
        self.assertIn("# local-mcp:install-default", fake.payload)
        self.assertIn("0 * * * *", fake.payload)

    def test_install_can_be_disabled_by_environment_variable(self):
        tmp = self.tempdir()

        env = {"LOCAL_MCP_AUTOMATION_DIR": tmp, "LOCAL_MCP_ENABLE_SCHEDULER_INSTALL": "0"}
        with patch.dict("os.environ", env, clear=True):
            bundle = create_automation_bundle(
                name="Install Gated",
                command="echo hi",
                schedule="hourly",
                scheduler="cron",
                install=True,
            )

        self.assertFalse(bundle.installed)
        self.assertIn("LOCAL_MCP_ENABLE_SCHEDULER_INSTALL", bundle.install_message)

    def test_install_reports_missing_crontab_binary(self):
        tmp = self.tempdir()

        with patch.dict("os.environ", {"LOCAL_MCP_AUTOMATION_DIR": tmp}, clear=True):
            with patch("local_mcp.automations.scheduler.shutil.which", return_value=None):
                bundle = create_automation_bundle(
                    name="No Crontab",
                    command="echo hi",
                    schedule="hourly",
                    scheduler="cron",
                    install=True,
                )

        self.assertFalse(bundle.installed)
        self.assertIn("crontab command not found", bundle.install_message)

    def test_remove_automation_deletes_cron_entry_and_files(self):
        tmp = self.tempdir()
        fake = FakeCrontab()

        with patch.dict("os.environ", {"LOCAL_MCP_AUTOMATION_DIR": tmp}, clear=True):
            with patch("local_mcp.automations.scheduler.subprocess.run", side_effect=fake.run):
                with patch("local_mcp.automations.scheduler.shutil.which", return_value="/usr/bin/crontab"):
                    create_automation_bundle(
                        name="Removable Task",
                        command="echo hi",
                        schedule="hourly",
                        scheduler="cron",
                        install=True,
                    )
                    self.assertIn("# local-mcp:removable-task", fake.payload)

                    message = remove_automation("Removable Task", delete_files=True)

        self.assertNotIn("# local-mcp:removable-task", fake.payload)
        self.assertIn("Removed the crontab entry", message)
        self.assertFalse((Path(tmp) / "removable-task").exists())

    def test_list_automation_bundles_reports_installed_state(self):
        tmp = self.tempdir()
        fake = FakeCrontab()

        with patch.dict("os.environ", {"LOCAL_MCP_AUTOMATION_DIR": tmp}, clear=True):
            with patch("local_mcp.automations.scheduler.subprocess.run", side_effect=fake.run):
                with patch("local_mcp.automations.scheduler.shutil.which", return_value="/usr/bin/crontab"):
                    create_automation_bundle(
                        name="Listed Task",
                        command="echo hi",
                        schedule="daily",
                        scheduler="cron",
                        install=True,
                    )
                    bundles = list_automation_bundles()

        self.assertEqual(len(bundles), 1)
        self.assertEqual(bundles[0]["slug"], "listed-task")
        self.assertEqual(bundles[0]["scheduler"], "cron")
        self.assertEqual(bundles[0]["schedule"], "0 9 * * *")
        self.assertTrue(bundles[0]["installed"])


class AutomationToolTests(unittest.IsolatedAsyncioTestCase):
    def tempdir(self):
        root = Path.cwd() / ".tmp" / "unit-tests" / f"{self._testMethodName}-{uuid.uuid4().hex}"
        root.mkdir(parents=True)
        return str(root)

    async def test_schedule_task_installs_by_default(self):
        tmp = self.tempdir()
        fake = FakeCrontab()

        with patch.dict("os.environ", {"LOCAL_MCP_AUTOMATION_DIR": tmp}, clear=True):
            with patch("local_mcp.automations.scheduler.subprocess.run", side_effect=fake.run):
                with patch("local_mcp.automations.scheduler.shutil.which", return_value="/usr/bin/crontab"):
                    response = await schedule_task(
                        name="Nightly Cleanup",
                        command="python cleanup.py",
                        schedule="0 2 * * *",
                        scheduler="cron",
                    )

        self.assertIn("installed and active", response)
        self.assertIn("No terminal commands are needed", response)
        self.assertIn("# local-mcp:nightly-cleanup", fake.payload)

    async def test_schedule_task_reports_manual_step_when_not_installed(self):
        tmp = self.tempdir()

        with patch.dict("os.environ", {"LOCAL_MCP_AUTOMATION_DIR": tmp}, clear=True):
            response = await schedule_task(
                name="Review First",
                command="python cleanup.py",
                schedule="0 2 * * *",
                scheduler="cron",
                install=False,
            )

        self.assertIn("NOT installed", response)
        self.assertIn("Install not requested", response)
        self.assertIn("crontab", response)

    async def test_simple_create_scheduled_command_installs_and_allows_retry(self):
        tmp = self.tempdir()
        fake = FakeCrontab()

        with patch.dict("os.environ", {"LOCAL_MCP_AUTOMATION_DIR": tmp}, clear=True):
            with patch("local_mcp.automations.scheduler.subprocess.run", side_effect=fake.run):
                with patch("local_mcp.automations.scheduler.shutil.which", return_value="/usr/bin/crontab"):
                    first = await create_scheduled_command(
                        name="Hourly Ping",
                        command="echo ping",
                        schedule="hourly",
                    )
                    second = await create_scheduled_command(
                        name="Hourly Ping",
                        command="echo ping",
                        schedule="hourly",
                    )

        self.assertIn("installed and active", first)
        self.assertIn("installed and active", second)
        self.assertEqual(fake.payload.count("# local-mcp:hourly-ping"), 1)

    async def test_list_and_delete_scheduled_task_tools(self):
        tmp = self.tempdir()
        fake = FakeCrontab()

        with patch.dict("os.environ", {"LOCAL_MCP_AUTOMATION_DIR": tmp}, clear=True):
            with patch("local_mcp.automations.scheduler.subprocess.run", side_effect=fake.run):
                with patch("local_mcp.automations.scheduler.shutil.which", return_value="/usr/bin/crontab"):
                    await schedule_task(
                        name="Daily Digest",
                        command="python digest.py",
                        schedule="daily",
                    )

                    listing = await list_scheduled_tasks()
                    self.assertIn("daily-digest", listing)
                    self.assertIn("status=installed", listing)

                    removal = await delete_scheduled_task(name="Daily Digest")
                    self.assertIn("Removed the crontab entry", removal)

                    empty = await list_scheduled_tasks()

        self.assertEqual(empty, "No scheduled tasks found.")

    async def test_simple_remove_scheduled_command_handles_missing_task(self):
        tmp = self.tempdir()

        with patch.dict("os.environ", {"LOCAL_MCP_AUTOMATION_DIR": tmp}, clear=True):
            with patch("local_mcp.automations.scheduler.shutil.which", return_value=None):
                response = await remove_scheduled_command(name="Never Created")

        self.assertIn("No installed schedule or generated files found", response)


if __name__ == "__main__":
    unittest.main()
