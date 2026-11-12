import unittest
import tempfile
import shutil
from pathlib import Path

from fanqie_reader.models import Book, Chapter
from fanqie_reader.storage import StorageManager

class TestStorage(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.storage = StorageManager(base_dir=self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_shelf_crud(self):
        # 初始为空
        self.assertEqual(len(self.storage.load_shelf()), 0)

        # 添加书籍
        b1 = Book(book_id="101", title="万相之王", author="天蚕土豆", chapter_total=800)
        item1 = self.storage.add_to_shelf(b1)
        self.assertTrue(self.storage.is_in_shelf("101"))
        self.assertEqual(len(self.storage.load_shelf()), 1)

        # 更新断点进度
        self.storage.update_progress(
            book_id="101",
            chapter_index=15,
            chapter_id="item_15",
            chapter_title="第16章 进阶",
            line_offset=42,
            book=b1
        )
        loaded = self.storage.get_shelf_item("101")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.last_chapter_index, 15)
        self.assertEqual(loaded.last_chapter_id, "item_15")
        self.assertEqual(loaded.last_chapter_title, "第16章 进阶")
        self.assertEqual(loaded.line_offset, 42)

        # 移除书籍
        removed = self.storage.remove_from_shelf("101")
        self.assertTrue(removed)
        self.assertFalse(self.storage.is_in_shelf("101"))
        self.assertEqual(len(self.storage.load_shelf()), 0)

    def test_chapter_cache(self):
        # 缓存与读取
        self.storage.save_chapter_cache("101", "c_1", "第一章 序幕", "正文内容测试...")
        cached = self.storage.get_chapter_cache("101", "c_1")
        self.assertIsNotNone(cached)
        title, content = cached
        self.assertEqual(title, "第一章 序幕")
        self.assertEqual(content, "正文内容测试...")

    def test_chapters_meta_cache(self):
        chapters = [
            Chapter(item_id="c1", title="第一章", index=0),
            Chapter(item_id="c2", title="第二章", index=1)
        ]
        self.storage.save_chapters_meta("101", chapters)
        loaded = self.storage.get_chapters_meta("101")
        self.assertIsNotNone(loaded)
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[1].title, "第二章")

if __name__ == "__main__":
    unittest.main()
