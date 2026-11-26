import unittest
import tempfile
import shutil
from unittest.mock import patch

from fanqie_reader.sources import SourceManager
from fanqie_reader.storage import StorageManager
from fanqie_reader.text_engine import TextLayoutEngine
from fanqie_reader.models import Book, Chapter, SourceBook, make_local_book_id


class TestCLIWorkflow(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.storage = StorageManager(base_dir=self.test_dir)
        self.source_manager = SourceManager()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_full_local_download_and_resume_flow(self):
        sb = SourceBook(
            source_name="香书小说",
            source_base_url="http://www.ibiqugu.net/",
            book_url="http://www.ibiqugu.net/1/123/",
            title="诡秘测试",
            author="测试作者",
        )
        book = Book(
            book_id=make_local_book_id(sb.title, sb.author),
            title=sb.title,
            author=sb.author,
        )
        chapters = [
            Chapter("ch_00000", "第一章 开端", index=0, source_url="http://www.ibiqugu.net/1/123/1.html"),
            Chapter("ch_00001", "第二章 继续", index=1, source_url="http://www.ibiqugu.net/1/123/2.html"),
        ]

        with patch.object(self.source_manager, "fetch_toc", return_value=chapters), patch.object(
            self.source_manager,
            "fetch_chapter_content",
            side_effect=[
                ("第一章 开端", "这是第一章的正文内容，用于验证下载后一次性分章落盘。" * 20),
                ("第二章 继续", "这是第二章的正文内容。" * 20),
            ],
        ):
            downloaded = self.source_manager.download_book(sb, self.storage, book)

        self.assertEqual(len(downloaded), 2)
        self.assertTrue(self.storage.is_book_downloaded(book.book_id))
        self.assertTrue(self.storage.is_in_shelf(book.book_id))

        title, content = self.storage.get_chapter_cache(book.book_id, "ch_00000")
        engine = TextLayoutEngine(content_width=80)
        lines = engine.layout_chapter(title, content)
        self.assertGreater(len(lines), 3)

        self.storage.update_progress(
            book_id=book.book_id,
            chapter_index=0,
            chapter_id="ch_00000",
            chapter_title=title,
            line_offset=5,
            book=book,
        )
        reloaded = self.storage.get_shelf_item(book.book_id)
        self.assertIsNotNone(reloaded)
        self.assertEqual(reloaded.last_chapter_index, 0)
        self.assertEqual(reloaded.last_chapter_id, "ch_00000")
        self.assertEqual(reloaded.line_offset, 5)


if __name__ == "__main__":
    unittest.main()
