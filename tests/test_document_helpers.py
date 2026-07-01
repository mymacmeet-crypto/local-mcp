import json
import unittest

from local_mcp.documents.formatting import format_result
from local_mcp.documents.models import ParseResult
from local_mcp.documents.parsers import marker_page_range, parse_page_selection


class DocumentHelperTests(unittest.TestCase):
    def test_parse_page_selection_is_one_based_and_deduplicated(self):
        self.assertEqual(parse_page_selection("1-3,3,5", 5), [0, 1, 2, 4])

    def test_marker_page_range_preserves_existing_zero_based_behavior(self):
        self.assertEqual(marker_page_range("1-3,5"), "0-2,4")

    def test_format_result_truncates_with_warning_in_json(self):
        result = ParseResult("text", "json", "abcdef", "sample.txt", {"bytes": 6})

        payload = json.loads(format_result(result, include_metadata=True, max_chars=3))

        self.assertEqual(payload["content"], "abc")
        self.assertIn("Content truncated to 3 characters.", payload["warnings"])


if __name__ == "__main__":
    unittest.main()
