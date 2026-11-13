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
        # 使用一本固定的书籍测试
        # 6918022276038265863 (诡秘复苏)
        book_id = "6918022276038265863"
        book, chapters = self.api.get_book_detail(book_id)
        self.assertEqual(book.book_id, book_id)
        self.assertIn("诡秘复苏", book.title)
        self.assertGreater(len(chapters), 0)
        self.assertTrue(chapters[0].title)

    def test_get_chapter_content_and_decode(self):
        # 6932207155734905352 (诡秘复苏 第一章)
        item_id = "6932207155734905352"
        title, content = self.api.get_chapter_content(item_id)
        self.assertTrue(bool(title))
        self.assertTrue(bool(content))
        # 验证段落缩进
        self.assertTrue(content.startswith("　　") or "\n\n　　" in content)
        # 验证不包含未解密的 PUA 字符
        pua_chars = [c for c in content if 0xE000 <= ord(c) <= 0xF8FF]
        self.assertEqual(len(pua_chars), 0, f"发现未解密的私有区字符: {pua_chars[:10]}")

    def test_rejects_preview_when_chapter_word_count_exceeds_returned_body(self):
        state = {
            "reader": {
                "chapterData": {
                    "title": "第1033章 男儿有泪（第三更）",
                    "chapterWordNumber": "2071",
                    "content": "<p>“刘虎？”刘峰怔了怔。</p>" * 8,
                }
            }
        }
        with patch.object(self.api, "_fetch", return_value="<html>fixture</html>"), patch.object(
            self.api, "_parse_initial_state", return_value=state
        ):
            with self.assertRaisesRegex(RuntimeError, "试读片段"):
                self.api.get_chapter_content("chapter-preview")

    def test_chapter_request_uses_authenticated_session_cookie(self):
        state = {
            "reader": {
                "chapterData": {
                    "title": "SVIP章节",
                    "chapterWordNumber": "600",
                    "content": "<p>正文内容。</p>" * 100,
                }
            }
        }
        with patch.object(self.api, "_fetch", return_value="<html/>" ) as fetch, patch.object(
            self.api, "_parse_initial_state", return_value=state
        ):
            self.api.get_chapter_content("chapter-full", cookie_header="sessionid=svip-session")

        self.assertEqual(fetch.call_args.kwargs["headers"]["Cookie"], "sessionid=svip-session")

    def test_search_filters_voice_media(self):
        payload = {
            "data": {"ret_data": [
                {"book_id": "text", "title": "文字书", "genre": 0},
                {"book_id": "voice", "title": "有声书", "genre": 4},
            ]}
        }
        with patch.object(self.api, "_fetch", return_value=json.dumps(payload)):
            self.assertEqual([book.book_id for book in self.api.search_books("测试")], ["text"])

    def test_update_cloud_progress_posts_reader_payload(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                pass

            def read(self):
                return b'{"code":0}'

        payload = {"book_id": "101", "item_id": "chapter-2", "index": 1}
        with patch("fanqie_reader.api.urllib.request.urlopen", return_value=Response()) as urlopen:
            self.api.update_cloud_progress(payload, "sessionid=test")

        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(json.loads(request.data), payload)

    def test_update_cloud_progress_accepts_string_success_code(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                pass

            def read(self):
                return b'{"code":"0","message":"ok"}'

        with patch("fanqie_reader.api.urllib.request.urlopen", return_value=Response()):
            self.api.update_cloud_progress({"book_id": "101", "item_id": "chapter-2"}, "sessionid=test")

if __name__ == "__main__":
    unittest.main()
