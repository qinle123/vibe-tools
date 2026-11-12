import unittest
import time
from fanqie_reader.models import Book, Chapter, ShelfItem

class TestModels(unittest.TestCase):
    def test_chapter_serialization(self):
        ch = Chapter(item_id="12345", title="第一章 觉醒", volume_name="正文卷", index=0)
        d = ch.to_dict()
        ch2 = Chapter.from_dict(d)
        self.assertEqual(ch.item_id, ch2.item_id)
        self.assertEqual(ch.title, ch2.title)
        self.assertEqual(ch.volume_name, ch2.volume_name)
        self.assertEqual(ch.index, ch2.index)

    def test_book_serialization(self):
        b = Book(
            book_id="999",
            title="仙逆",
            author="耳根",
            abstract="顺为凡，逆则仙...",
            category="仙侠",
            chapter_total=1000
        )
        d = b.to_dict()
        b2 = Book.from_dict(d)
        self.assertEqual(b.book_id, b2.book_id)
        self.assertEqual(b.title, b2.title)
        self.assertEqual(b.author, b2.author)
        self.assertEqual(b.chapter_total, b2.chapter_total)

    def test_shelf_item_progress(self):
        b = Book(book_id="1", title="测试书", chapter_total=200)
        item = ShelfItem(book=b, last_chapter_index=49)
        # (49 + 1) / 200 = 25.0%
        self.assertAlmostEqual(item.progress_percent(), 25.0)

        # 边界条件：总章节数为0
        b0 = Book(book_id="2", title="测试书0", chapter_total=0)
        item0 = ShelfItem(book=b0, last_chapter_index=0)
        self.assertEqual(item0.progress_percent(), 0.0)

if __name__ == "__main__":
    unittest.main()
