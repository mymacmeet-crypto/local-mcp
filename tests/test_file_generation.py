import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfReader

from local_mcp.file_generation import append_generated_file, write_generated_file
from local_mcp.search.searxng import SearchResult
from local_mcp.tools.file_generation import generate_file, web_search_to_file


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
                write_generated_file("notes", "content", file_type="docx")

    def test_write_generated_file_creates_pdf_under_env_output_dir(self):
        tmp = self.tempdir()
        with patch.dict("os.environ", {"LOCAL_MCP_FILE_OUTPUT_DIR": tmp, "LOCAL_MCP_DOWNLOAD_DIR": ""}, clear=True):
            result = write_generated_file(
                "reports/summary",
                "# Summary\n\n- First point\n- Second point",
                file_type="pdf",
            )

        expected = Path(tmp).resolve() / "reports" / "summary.pdf"
        self.assertEqual(result.path, expected)
        self.assertEqual(result.file_type, "pdf")
        self.assertGreater(result.bytes_written, 0)
        text = "\n".join(page.extract_text() or "" for page in PdfReader(str(expected)).pages)
        self.assertIn("Summary", text)
        self.assertIn("First point", text)

    def test_write_generated_file_infers_pdf_from_filename_extension(self):
        tmp = self.tempdir()
        with patch.dict("os.environ", {"LOCAL_MCP_FILE_OUTPUT_DIR": tmp, "LOCAL_MCP_DOWNLOAD_DIR": ""}, clear=True):
            result = write_generated_file("reports/inferred.pdf", "PDF body")

        self.assertEqual(result.path, Path(tmp).resolve() / "reports" / "inferred.pdf")
        self.assertEqual(result.file_type, "pdf")

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

    def test_append_generated_file_adds_chunk_to_existing_markdown(self):
        tmp = self.tempdir()
        with patch.dict("os.environ", {"LOCAL_MCP_FILE_OUTPUT_DIR": tmp, "LOCAL_MCP_DOWNLOAD_DIR": ""}, clear=True):
            write_generated_file("chunks", "first")
            result = append_generated_file("chunks", "second")

        expected = Path(tmp).resolve() / "chunks.md"
        self.assertEqual(expected.read_text(encoding="utf-8"), "first\nsecond\n")
        self.assertEqual(result.path, expected)
        self.assertEqual(result.operation, "append")

    def test_append_generated_file_rejects_pdf_output(self):
        tmp = self.tempdir()
        with patch.dict("os.environ", {"LOCAL_MCP_FILE_OUTPUT_DIR": tmp, "LOCAL_MCP_DOWNLOAD_DIR": ""}, clear=True):
            with self.assertRaisesRegex(ValueError, "Appending to PDF output is not supported"):
                append_generated_file("chunks.pdf", "second")


class FileGenerationToolTests(unittest.IsolatedAsyncioTestCase):
    def tempdir(self):
        root = Path.cwd() / ".tmp" / "unit-tests" / f"{self._testMethodName}-{uuid.uuid4().hex}"
        root.mkdir(parents=True)
        return str(root)

    async def test_generate_file_append_mode_supports_chunked_writes(self):
        tmp = self.tempdir()
        with patch.dict("os.environ", {"LOCAL_MCP_FILE_OUTPUT_DIR": tmp, "LOCAL_MCP_DOWNLOAD_DIR": ""}, clear=True):
            await generate_file("report", "# Report", write_mode="write")
            response = await generate_file("report", "Second chunk", write_mode="append")

        expected = Path(tmp).resolve() / "report.md"
        self.assertEqual(expected.read_text(encoding="utf-8"), "# Report\nSecond chunk\n")
        self.assertIn("Write mode: append", response)

    async def test_generate_file_supports_pdf_output(self):
        tmp = self.tempdir()
        with patch.dict("os.environ", {"LOCAL_MCP_FILE_OUTPUT_DIR": tmp, "LOCAL_MCP_DOWNLOAD_DIR": ""}, clear=True):
            response = await generate_file("brief.pdf", "# Brief\n\nGenerated body")

        expected = Path(tmp).resolve() / "brief.pdf"
        self.assertTrue(expected.is_file())
        self.assertIn("PDF file generated.", response)
        self.assertIn("File type: pdf", response)

    async def test_web_search_to_file_writes_search_results_without_content_input(self):
        tmp = self.tempdir()

        async def fake_search(*args, **kwargs):
            return (
                "http://searx.local/",
                [
                    SearchResult(
                        title="Example Result",
                        url="https://example.com/page",
                        content="A useful result summary.",
                        engines=["example"],
                        score=1.0,
                    )
                ],
                ["Short answer"],
                ["related query"],
            )

        with (
            patch.dict("os.environ", {"LOCAL_MCP_FILE_OUTPUT_DIR": tmp, "LOCAL_MCP_DOWNLOAD_DIR": ""}, clear=True),
            patch("local_mcp.tools.file_generation.searxng.search", new=fake_search),
        ):
            response = await web_search_to_file(
                query="test topic",
                filename="research/results",
                limit=1,
                write_mode="write",
            )

        expected = Path(tmp).resolve() / "research" / "results.md"
        content = expected.read_text(encoding="utf-8")
        self.assertIn("## Web Search: test topic", content)
        self.assertIn("[Example Result](https://example.com/page)", content)
        self.assertIn("Short answer", content)
        self.assertIn("Web search results written to file.", response)
        self.assertIn("Results returned: 1", response)
        self.assertIn("File type: md", response)

    async def test_web_search_to_file_supports_pdf_filename(self):
        tmp = self.tempdir()

        async def fake_search(*args, **kwargs):
            return (
                "http://searx.local/",
                [
                    SearchResult(
                        title="PDF Result",
                        url="https://example.com/pdf",
                        content="A result written into a PDF.",
                        engines=["example"],
                        score=2.0,
                    )
                ],
                [],
                [],
            )

        with (
            patch.dict("os.environ", {"LOCAL_MCP_FILE_OUTPUT_DIR": tmp, "LOCAL_MCP_DOWNLOAD_DIR": ""}, clear=True),
            patch("local_mcp.tools.file_generation.searxng.search", new=fake_search),
        ):
            response = await web_search_to_file(
                query="pdf topic",
                filename="research/results.pdf",
                limit=1,
                write_mode="write",
            )

        expected = Path(tmp).resolve() / "research" / "results.pdf"
        self.assertTrue(expected.is_file())
        text = "\n".join(page.extract_text() or "" for page in PdfReader(str(expected)).pages)
        self.assertIn("Web Search: pdf topic", text)
        self.assertIn("PDF Result", text)
        self.assertIn("File type: pdf", response)

    async def test_web_search_to_file_supports_pdf_file_type(self):
        tmp = self.tempdir()

        async def fake_search(*args, **kwargs):
            return ("http://searx.local/", [], ["A direct answer"], [])

        with (
            patch.dict("os.environ", {"LOCAL_MCP_FILE_OUTPUT_DIR": tmp, "LOCAL_MCP_DOWNLOAD_DIR": ""}, clear=True),
            patch("local_mcp.tools.file_generation.searxng.search", new=fake_search),
        ):
            response = await web_search_to_file(
                query="answer topic",
                filename="research/answers",
                file_type="pdf",
                write_mode="write",
            )

        expected = Path(tmp).resolve() / "research" / "answers.pdf"
        text = "\n".join(page.extract_text() or "" for page in PdfReader(str(expected)).pages)
        self.assertIn("A direct answer", text)
        self.assertIn("File type: pdf", response)


if __name__ == "__main__":
    unittest.main()
