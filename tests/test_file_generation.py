import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from local_mcp.file_generation import write_generated_file


class FileGenerationTests(unittest.TestCase):
    def tempdir(self):
        root = Path.cwd() / ".tmp" / "unit-tests" / f"{self._testMethodName}-{uuid.uuid4().hex}"
        root.mkdir(parents=True)
        return str(root)

    def test_write_generated_file_creates_markdown_under_env_output_dir(self):
        tmp = self.tempdir()
        with patch.dict("os.environ", {"LOCAL_MCP_FILE_OUTPUT_DIR": tmp, "LOCAL_MCP_DOWNLOAD_DIR": ""}, clear=True):
            result = write_generated_file("notes/report", "# Title")

        expected = Path(tmp).resolve() / "notes" / "report.md"
        self.assertEqual(result.path, expected)
        self.assertEqual(expected.read_text(encoding="utf-8"), "# Title\n")
        self.assertEqual(result.file_type, "md")
        self.assertFalse(result.overwritten)

    def test_write_generated_file_refuses_existing_file_without_overwrite(self):
        tmp = self.tempdir()
        target = Path(tmp) / "notes.md"
        target.write_text("old", encoding="utf-8")

        with patch.dict("os.environ", {"LOCAL_MCP_FILE_OUTPUT_DIR": tmp, "LOCAL_MCP_DOWNLOAD_DIR": ""}, clear=True):
            with self.assertRaises(ValueError):
                write_generated_file("notes.md", "new")

            result = write_generated_file("notes.md", "new", overwrite=True)
        self.assertTrue(result.overwritten)
        self.assertEqual(target.read_text(encoding="utf-8"), "new\n")

    def test_write_generated_file_rejects_path_traversal(self):
        tmp = self.tempdir()
        with patch.dict("os.environ", {"LOCAL_MCP_FILE_OUTPUT_DIR": tmp, "LOCAL_MCP_DOWNLOAD_DIR": ""}, clear=True):
            with self.assertRaises(ValueError):
                write_generated_file("../escape", "content")

    def test_write_generated_file_rejects_non_markdown_suffix(self):
        tmp = self.tempdir()
        with patch.dict("os.environ", {"LOCAL_MCP_FILE_OUTPUT_DIR": tmp, "LOCAL_MCP_DOWNLOAD_DIR": ""}, clear=True):
            with self.assertRaises(ValueError):
                write_generated_file("notes.txt", "content")

    def test_write_generated_file_rejects_unsupported_file_type(self):
        tmp = self.tempdir()
        with patch.dict("os.environ", {"LOCAL_MCP_FILE_OUTPUT_DIR": tmp, "LOCAL_MCP_DOWNLOAD_DIR": ""}, clear=True):
            with self.assertRaises(ValueError):
                write_generated_file("notes", "content", file_type="pdf")

    def test_write_generated_file_requires_env_download_path(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(ValueError, "Download path not defined"):
                write_generated_file("notes", "content")

    def test_write_generated_file_uses_env_output_dir(self):
        tmp = self.tempdir()
        with patch.dict("os.environ", {"LOCAL_MCP_FILE_OUTPUT_DIR": tmp, "LOCAL_MCP_DOWNLOAD_DIR": ""}, clear=True):
            result = write_generated_file("env-note", "content")

        self.assertEqual(result.path, Path(tmp).resolve() / "env-note.md")

    def test_file_output_env_takes_precedence_over_download_env(self):
        file_output = self.tempdir()
        download = self.tempdir()
        with patch.dict(
            "os.environ",
            {
                "LOCAL_MCP_FILE_OUTPUT_DIR": file_output,
                "LOCAL_MCP_DOWNLOAD_DIR": download,
            },
            clear=True,
        ):
            result = write_generated_file("preferred-env", "content")

        self.assertEqual(result.path, Path(file_output).resolve() / "preferred-env.md")

    def test_write_generated_file_uses_download_env_alias(self):
        tmp = self.tempdir()
        with patch.dict("os.environ", {"LOCAL_MCP_FILE_OUTPUT_DIR": "", "LOCAL_MCP_DOWNLOAD_DIR": tmp}, clear=True):
            result = write_generated_file("download-env-note", "content")

        self.assertEqual(result.path, Path(tmp).resolve() / "download-env-note.md")


if __name__ == "__main__":
    unittest.main()
