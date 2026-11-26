import unittest
import json
from unittest.mock import patch
from fanqie_reader.api import FanqieAPI


class TestAPIIntegration(unittest.TestCase):
    def setUp(self):
        self.api = FanqieAPI()

    def test_search_books(self):
        results = self.api.search_books("剑来", count=5)
        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0)
        book = results[0]
        self.assertTrue(bool(book.book_id))
        self.assertTrue(bool(book.title))

    def test_get_book_detail_and_chapters(self):
        book_id = "6918022276038265863"
        book, chapters = self.api.get_book_detail(book_id)
        self.assertEqual(book.book_id, book_id)
        self.assertIn("诡秘复苏", book.title)
        self.assertGreater(len(chapters), 0)
        self.assertTrue(chapters[0].title)

    def test_search_filters_voice_media(self):
        payload = {
            "data": {"ret_data": [
                {"book_id": "text", "title": "文字书", "genre": 0},
                {"book_id": "voice", "title": "有声书", "genre": 4},
            ]}
        }
        with patch.object(self.api, "_fetch", return_value=json.dumps(payload)):
            self.assertEqual([book.book_id for book in self.api.search_books("测试")], ["text"])


if __name__ == "__main__":
    unittest.main()
