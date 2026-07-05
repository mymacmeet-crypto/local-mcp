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
        from local_mcp.tools import documents, file_generation, ocr, search, web

        for handler in (
            web.web_fetch,
            web.web_summarize,
            web.extract_urls,
            search.web_search,
            ocr.extract_image_text,
            documents.parse_document,
            file_generation.generate_file,
            file_generation.web_search_to_file,
        ):
            self.assertTrue(callable(handler))


if __name__ == "__main__":
    unittest.main()
