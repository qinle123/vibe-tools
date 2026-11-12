import unittest
import tempfile
import shutil
from pathlib import Path

from fanqie_reader.api import FanqieAPI
from fanqie_reader.storage import StorageManager
from fanqie_reader.text_engine import TextLayoutEngine
from fanqie_reader.models import Book, Chapter

class TestCLIWorkflow(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.storage = StorageManager(base_dir=self.test_dir)
        self.api = FanqieAPI()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_full_user_flow(self):
        # 1. 模拟搜索
        results = self.api.search_books("诡秘", count=3)
        self.assertGreater(len(results), 0)
        book = results[0]

        # 2. 加入书架
        shelf_item = self.storage.add_to_shelf(book)
        self.assertTrue(self.storage.is_in_shelf(book.book_id))

        # 3. 获取书籍详情与目录
        detail_book, chapters = self.api.get_book_detail(book.book_id)
        self.assertGreater(len(chapters), 0)
        self.storage.save_chapters_meta(book.book_id, chapters)

        # 4. 模拟阅读第 1 章并更新断点
        first_ch = chapters[0]
        title, content = self.api.get_chapter_content(first_ch.item_id)
        self.storage.save_chapter_cache(book.book_id, first_ch.item_id, title, content)

        # 排版
        engine = TextLayoutEngine(content_width=80)
        lines = engine.layout_chapter(title, content)
        self.assertGreater(len(lines), 5)

        # 断点续读到第 15 行
        self.storage.update_progress(
            book_id=book.book_id,
            chapter_index=0,
            chapter_id=first_ch.item_id,
            chapter_title=title,
            line_offset=15,
            book=detail_book
        )

        # 5. 重新打开书架，验证断点完美保存
        reloaded = self.storage.get_shelf_item(book.book_id)
        self.assertIsNotNone(reloaded)
        self.assertEqual(reloaded.last_chapter_index, 0)
        self.assertEqual(reloaded.last_chapter_id, first_ch.item_id)
        self.assertEqual(reloaded.line_offset, 15)

if __name__ == "__main__":
    unittest.main()
