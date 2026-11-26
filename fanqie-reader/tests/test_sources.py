import tempfile
import unittest
from unittest.mock import patch

from fanqie_reader.models import Book, SourceBook
from fanqie_reader.sources import SourceManager, score_match, _decode_html
from fanqie_reader.storage import StorageManager


class TestSourcesEngine(unittest.TestCase):
    def test_builtin_rules_loaded(self):
        mgr = SourceManager()
        self.assertGreaterEqual(len(mgr.rules), 10)
        self.assertIsNotNone(mgr.get_rule_by_name("香书小说"))

    def test_decode_html_gbk_and_utf8(self):
        gbk_bytes = "<html><meta charset='gbk'><body>测试中文</body></html>".encode("gbk")
        self.assertIn("测试中文", _decode_html(gbk_bytes))
        utf8_bytes = "<html><body>UTF8中文</body></html>".encode("utf-8")
        self.assertIn("UTF8中文", _decode_html(utf8_bytes, "text/html; charset=utf-8"))

    def test_score_match_prioritizes_same_title_and_author(self):
        exact = SourceBook("A", "", "http://a", "剑来", "烽火戏诸侯")
        same_title = SourceBook("B", "", "http://b", "剑来", "其他人")
        partial = SourceBook("C", "", "http://c", "剑来外传", "烽火戏诸侯")

        self.assertGreater(
            score_match(exact, "剑来", "烽火戏诸侯"),
            score_match(same_title, "剑来", "烽火戏诸侯"),
        )
        self.assertGreater(
            score_match(same_title, "剑来", "烽火戏诸侯"),
            score_match(partial, "剑来", "烽火戏诸侯"),
        )

    def test_fetch_toc_and_chapter_cleaning(self):
        rule = {
            "name": "测试源",
            "url": "https://example.com/",
            "toc": {"item": "#list > dl > dd > a"},
            "chapter": {
                "title": "h1",
                "content": "#content",
                "paragraphTagClosed": False,
                "filterTag": "script, .ad",
                "filterTxt": r"广告：[^\n]+",
            },
        }
        toc_html = """
        <div id="list"><dl>
          <dd><a href="/book/1/1.html">第一章 初入</a></dd>
          <dd><a href="/book/1/2.html">第二章 进阶</a></dd>
        </dl></div>
        """
        ch_html = """
        <html><body>
          <h1>第一章 初入</h1>
          <div id="content">
            <div class="ad">弹窗广告</div>
            <script>alert(1)</script>
            第一段正文。<br><br>
            广告：请记住本站域名<br>
            第二段正文。
          </div>
        </body></html>
        """
        mgr = SourceManager()
        with patch.object(mgr, "_http_get", return_value=(toc_html, "https://example.com/book/1/")):
            chapters = mgr.fetch_toc(rule, "https://example.com/book/1/")
        self.assertEqual(len(chapters), 2)
        self.assertEqual(chapters[0].source_url, "https://example.com/book/1/1.html")

        with patch.object(mgr, "_http_get", return_value=(ch_html, "https://example.com/book/1/1.html")):
            title, content = mgr.fetch_chapter_content(rule, "https://example.com/book/1/1.html")
        self.assertEqual(title, "第一章 初入")
        self.assertEqual(content, "第一段正文。\n第二段正文。")

    def test_download_book_splits_chapters_and_clears_old_cache_on_switch(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = StorageManager(tmp)
            book = Book("b1", "测试书", author="作者")
            storage.save_chapter_cache("b1", "stale_ch", "旧章节", "旧内容")

            mgr = SourceManager()
            sb = SourceBook("香书小说", "http://www.ibiqugu.net/", "http://www.ibiqugu.net/1/", "测试书", "作者")
            fake_chapters = [
                type("Ch", (), {"item_id": "ch_00000", "title": "第一章", "index": 0, "source_url": "http://u/1", "to_dict": lambda self: {"item_id": "ch_00000", "title": "第一章", "volume_name": "", "index": 0, "source_url": "http://u/1"}})(),
                type("Ch", (), {"item_id": "ch_00001", "title": "第二章", "index": 1, "source_url": "http://u/2", "to_dict": lambda self: {"item_id": "ch_00001", "title": "第二章", "volume_name": "", "index": 1, "source_url": "http://u/2"}})(),
            ]
            with patch.object(mgr, "fetch_toc", return_value=fake_chapters), patch.object(
                mgr, "fetch_chapter_content", side_effect=[("第一章", "正文1"), ("第二章", "正文2")]
            ):
                mgr.download_book(sb, storage, book)

            self.assertIsNone(storage.get_chapter_cache("b1", "stale_ch"))
            self.assertEqual(storage.get_chapter_cache("b1", "ch_00000"), ("第一章", "正文1"))
            self.assertEqual(storage.get_chapter_cache("b1", "ch_00001"), ("第二章", "正文2"))
            self.assertTrue(storage.is_book_downloaded("b1"))

    def test_start_download_and_cancel_all_downloads(self):
        import threading
        import time

        with tempfile.TemporaryDirectory() as tmp:
            storage = StorageManager(tmp)
            book = Book("b2", "后台书", author="作者")
            sb = SourceBook("香书小说", "http://www.ibiqugu.net/", "http://www.ibiqugu.net/2/", "后台书", "作者")
            mgr = SourceManager()

            gate = threading.Event()
            fake_chapters = [
                type("Ch", (), {"item_id": f"ch_{i:05d}", "title": f"第{i}章", "index": i, "source_url": f"http://u/{i}", "to_dict": lambda self, i=i: {"item_id": f"ch_{i:05d}", "title": f"第{i}章", "volume_name": "", "index": i, "source_url": f"http://u/{i}"}})()
                for i in range(4)
            ]

            def slow_fetch(_rule, _url):
                gate.wait(timeout=2.0)
                return "章节", "正文"

            with patch.object(mgr, "fetch_toc", return_value=fake_chapters), patch.object(
                mgr, "fetch_chapter_content", side_effect=slow_fetch
            ):
                task = mgr.start_download(sb, storage, book, max_workers=1)
                deadline = time.monotonic() + 1.0
                while task.status == "fetching_toc" and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertEqual(mgr.get_download_task("b2"), task)
                mgr.cancel_all_downloads()
                gate.set()
                self.assertTrue(task.done_event.wait(timeout=2.0))
                self.assertEqual(task.status, "cancelled")


if __name__ == "__main__":
    unittest.main()
