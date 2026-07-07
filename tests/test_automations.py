import json
import plistlib
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from local_mcp.automations import create_automation_bundle
from local_mcp.automations.scheduler import normalize_schedule
from local_mcp.tools.automation import schedule_task
from local_mcp.tools.simple import create_scheduled_command


class AutomationBundleTests(unittest.TestCase):
    def tempdir(self):
        root = Path.cwd() / ".tmp" / "unit-tests" / f"{self._testMethodName}-{uuid.uuid4().hex}"
        root.mkdir(parents=True)
        return str(root)

    def test_normalize_schedule_accepts_aliases_and_cron(self):
        self.assertEqual(normalize_schedule("daily"), "0 9 * * *")
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

    def test_install_flag_is_gated_by_environment_variable(self):
        tmp = self.tempdir()

        with patch.dict("os.environ", {"LOCAL_MCP_AUTOMATION_DIR": tmp}, clear=True):
            bundle = create_automation_bundle(
                name="Install Gated",
                command="echo hi",
                schedule="hourly",
                scheduler="cron",
                install=True,
            )

        self.assertFalse(bundle.installed)
        self.assertIn("LOCAL_MCP_ENABLE_SCHEDULER_INSTALL", bundle.install_message)


class AutomationToolTests(unittest.IsolatedAsyncioTestCase):
    def tempdir(self):
        root = Path.cwd() / ".tmp" / "unit-tests" / f"{self._testMethodName}-{uuid.uuid4().hex}"
        root.mkdir(parents=True)
        return str(root)

    async def test_schedule_task_returns_bundle_summary(self):
        tmp = self.tempdir()

        with patch.dict("os.environ", {"LOCAL_MCP_AUTOMATION_DIR": tmp}, clear=True):
            response = await schedule_task(
                name="Nightly Cleanup",
                command="python cleanup.py",
                schedule="0 2 * * *",
                scheduler="cron",
            )

        self.assertIn("Scheduled task automation generated.", response)
        self.assertIn("nightly-cleanup", response)
        self.assertIn("Install command:", response)

    async def test_simple_create_scheduled_command_uses_cron_defaults(self):
        tmp = self.tempdir()

        with patch.dict("os.environ", {"LOCAL_MCP_AUTOMATION_DIR": tmp}, clear=True):
            response = await create_scheduled_command(
                name="Hourly Ping",
                command="echo ping",
                schedule="hourly",
            )

        self.assertIn("Scheduler: cron", response)
        self.assertIn("hourly-ping", response)


if __name__ == "__main__":
    unittest.main()
