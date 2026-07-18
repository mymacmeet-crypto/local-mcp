import unittest


class PackageImportTests(unittest.TestCase):
    def test_package_entry_points_import(self):
        import local_mcp.__main__ as module_entry
        from local_mcp.app import app, mcp
        from local_mcp.cli import main

        self.assertIs(module_entry.main, main)
        self.assertIsNotNone(app)
        self.assertIsNotNone(mcp)

    def test_tool_handlers_import_from_package(self):
        from local_mcp.tools import documents, file_generation, ocr, search, simple, web

        for handler in (
            web.web_fetch,
            web.extract_urls,
            search.web_search,
            ocr.extract_image_text,
            documents.parse_document,
            file_generation.generate_file,
            simple.fetch_web_page,
            simple.list_page_urls,
            simple.read_document,
            simple.read_image_text,
        ):
            self.assertTrue(callable(handler))

    def test_tool_profile_selection(self):
        from local_mcp.tools import _tools_for_profile

        full_names = [tool.__name__ for tool in _tools_for_profile("full")]
        simple_names = [tool.__name__ for tool in _tools_for_profile("qwen")]
        both_names = [tool.__name__ for tool in _tools_for_profile("both")]

        self.assertIn("web_search", full_names)
        self.assertIn("generate_file", full_names)
        self.assertNotIn("web_search_to_file", full_names)
        self.assertNotIn("fetch_web_page", full_names)
        self.assertEqual(
            simple_names,
            [
                "fetch_web_page",
                "list_page_urls",
                "read_document",
                "read_image_text",
                "generate_file",
            ],
        )
        self.assertIn("fetch_web_page", both_names)
        self.assertIn("web_search", both_names)
        self.assertEqual(both_names.count("generate_file"), 1)


if __name__ == "__main__":
    unittest.main()
