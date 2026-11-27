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

    def test_is_in_shelf_and_is_book_downloaded_use_stat_cache(self):
        from unittest.mock import patch

        book = Book(book_id="202", title="缓存测试")
        self.storage.add_to_shelf(book)
        self.assertTrue(self.storage.is_in_shelf("202"))
        with patch.object(self.storage, "load_shelf", side_effect=AssertionError("should hit cache")):
            self.assertTrue(self.storage.is_in_shelf("202"))
            self.assertFalse(self.storage.is_in_shelf("999"))

        self.storage.save_chapters_meta("202", [Chapter(item_id="c1", title="第一章", index=0)])
        self.storage.save_chapter_cache("202", "c1", "第一章", "正文")
        self.assertTrue(self.storage.is_book_downloaded("202"))
        with patch.object(self.storage, "get_chapters_meta", side_effect=AssertionError("should hit cache")):
            self.assertTrue(self.storage.is_book_downloaded("202"))

        self.storage.clear_book_cache("202")
        self.assertFalse(self.storage.is_book_downloaded("202"))

    def test_shelf_sort_recent_opened_first(self):
        b1 = Book(book_id="b1", title="较早加入但刚读", updated_at=100.0)
        b2 = Book(book_id="b2", title="最新加入但未读", updated_at=500.0)
        b3 = Book(book_id="b3", title="昨天读过", updated_at=200.0)
        self.storage.add_to_shelf(b1, added_at=100.0)
        self.storage.add_to_shelf(b2, added_at=500.0)
        self.storage.add_to_shelf(b3, added_at=200.0)

        self.storage.update_cloud_progress("b3", 1, "c1", "第2章", read_time=1000.0)
        self.storage.update_progress("b1", 2, "c2", "第3章", 10, b1)

        shelf = self.storage.load_shelf()
        self.assertEqual([item.book.book_id for item in shelf], ["b1", "b3", "b2"])

    def test_apply_cloud_shelf_order_marks_cloud_and_local_books(self):
        self.storage.add_to_shelf(Book(book_id="cloud_1", title="番茄书", updated_at=100.0))
        self.storage.add_to_shelf(Book(book_id="local_1", title="本地书", updated_at=200.0))
        self.storage.apply_cloud_shelf_order([{"book_id": "cloud_1", "last_operate_time": 300.0}])

        cloud_item = self.storage.get_shelf_item("cloud_1")
        local_item = self.storage.get_shelf_item("local_1")
        self.assertTrue(cloud_item.is_cloud_book())
        self.assertFalse(local_item.is_cloud_book())

if __name__ == "__main__":
    unittest.main()
