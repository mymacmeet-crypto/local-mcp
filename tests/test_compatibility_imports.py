import unittest


class CompatibilityImportTests(unittest.TestCase):
    def test_server_exports_packaged_entry_points(self):
        import server
        from local_mcp.tools import documents, file_generation, ocr, search, web

        self.assertIs(server.web_fetch, web.web_fetch)
        self.assertIs(server.extract_urls, web.extract_urls)
        self.assertIs(server.extract_content, web.extract_content)
        self.assertIs(server.web_search, search.web_search)
        self.assertIs(server.extract_image_text, ocr.extract_image_text)
        self.assertIs(server.parse_document, documents.parse_document)
        self.assertIs(server.generate_file, file_generation.generate_file)

    def test_legacy_root_modules_forward_to_package_modules(self):
        import document_parser
        import errors
        import extract
        import fetcher
        import ocr
        import searxng
        import sitemap
        from local_mcp.documents import api as document_api
        from local_mcp.ocr import tesseract as packaged_tesseract
        from local_mcp.search import searxng as packaged_searxng
        from local_mcp.shared import errors as packaged_errors
        from local_mcp.web import fetcher as packaged_fetcher
        from local_mcp.web import html as packaged_html
        from local_mcp.web import sitemap as packaged_sitemap

        self.assertIs(fetcher.fetch_static, packaged_fetcher.fetch_static)
        self.assertIs(extract.extract_links, packaged_html.extract_links)
        self.assertIs(sitemap.parse_sitemap, packaged_sitemap.parse_sitemap)
        self.assertIs(searxng.SearchResult, packaged_searxng.SearchResult)
        self.assertIs(ocr.extract_image_text, packaged_tesseract.extract_image_text)
        self.assertIs(errors.tool_error, packaged_errors.tool_error)
        self.assertIs(document_parser.parse_document, document_api.parse_document)


if __name__ == "__main__":
    unittest.main()
