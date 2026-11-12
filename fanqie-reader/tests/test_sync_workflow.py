import contextlib
import io
import tempfile
import unittest

from fanqie_reader.cli import headless_sync
from fanqie_reader.models import Book, Chapter
from fanqie_reader.storage import StorageManager


class FakeAuth:
    def is_logged_in(self):
        return True

    def get_display_name(self):
        return "test"

    def get_cookie_header(self):
        return "session=test"


class FakeAPI:
    def get_cloud_bookshelf(self, _cookie):
        return [
            {"book_id": "new", "last_operate_time": 300},
            {"book_id": "new", "last_operate_time": 320},
        ]

    def get_cloud_progress(self, _cookie):
        return [{
            "book_id": "existing",
            "item_id": "chapter-1031",
            "index": "0",
            "read_timestamp": "200",
        }]

    def get_book_info(self, book_id):
        return Book(book_id=book_id, title="新书", updated_at=999)


class TestSyncWorkflow(unittest.TestCase):
    def test_sync_keeps_cloud_shelf_order_and_uses_chapter_id_for_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = StorageManager(directory)
            old = storage.add_to_shelf(Book("existing", "旧书", updated_at=100))
            old.last_read_time = 500
            storage.save_shelf([old])
            chapters = [Chapter(f"chapter-{i}", f"第{i}章", index=i - 1) for i in range(1, 1032)]
            storage.save_chapters_meta("existing", chapters)

            with contextlib.redirect_stdout(io.StringIO()):
                headless_sync(FakeAPI(), storage, FakeAuth())

            shelf = storage.load_shelf()
            new = next(item for item in shelf if item.book.book_id == "new")
            resumed = next(item for item in shelf if item.book.book_id == "existing")
            self.assertEqual(new.added_at, 320)
            self.assertEqual(resumed.last_chapter_index, 1030)
            self.assertEqual(resumed.last_chapter_id, "chapter-1031")
            self.assertEqual(resumed.last_read_time, 200)

    def test_phone_order_uses_latest_duplicate_operation(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = StorageManager(directory)
            storage.add_to_shelf(Book("a", "较早", updated_at=100))
            storage.add_to_shelf(Book("b", "较新", updated_at=200))
            storage.apply_cloud_shelf_order([
                {"book_id": "a", "last_operate_time": 300},
                {"book_id": "b", "last_operate_time": 400},
                {"book_id": "a", "last_operate_time": 500},
            ])
            self.assertEqual([item.book.book_id for item in storage.load_shelf()], ["a", "b"])

    def test_phone_order_is_newest_first(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = StorageManager(directory)
            storage.add_to_shelf(Book("old", "旧书", updated_at=10))
            storage.add_to_shelf(Book("new", "新书", updated_at=20))
            storage.apply_cloud_shelf_order([
                {"book_id": "old", "last_operate_time": 100},
                {"book_id": "new", "last_operate_time": 200},
            ])
            self.assertEqual([item.book.book_id for item in storage.load_shelf()], ["new", "old"])


if __name__ == "__main__":
    unittest.main()
