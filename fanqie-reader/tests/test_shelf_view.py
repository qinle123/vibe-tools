import unittest
import tempfile
import shutil
import time
from unittest.mock import MagicMock, patch

from fanqie_reader.models import Book, Chapter, ShelfItem
from fanqie_reader.storage import StorageManager
from fanqie_reader.ui.shelf_view import ShelfView
from fanqie_reader.ui.terminal import (
    KEY_UP, KEY_DOWN, KEY_ENTER, KEY_ESC, KEY_BACKSPACE
)

class MockTerminal:
    def __init__(self, key_sequence):
        self.keys = list(key_sequence)
        self.output = []

    def get_size(self):
        return 80, 24

    def write(self, s: str):
        self.output.append(s)

    def flush(self):
        pass

    def move_cursor(self, col: int, row: int):
        pass

    def show_cursor(self):
        pass

    def hide_cursor(self):
        pass

    def read_key(self, timeout=None, *, text_input=False):
        if self.keys:
            return self.keys.pop(0)
        return 'q'

class TestShelfView(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.storage = StorageManager(base_dir=self.test_dir)
        self.mock_api = MagicMock()
        self.mock_auth = MagicMock()
        self.mock_auth.is_logged_in.return_value = False
        self.mock_auth.get_display_name.return_value = "未登录"

        # 添加几本不同时间的测试书籍
        b1 = Book(book_id="101", title="诡舍", author="夜来风雨声", updated_at=100.0)
        b2 = Book(book_id="102", title="全球大佬团宠后", author="晚风似火", updated_at=200.0)
        b3 = Book(book_id="103", title="西游奸臣", author="龙秋源", updated_at=300.0)

        # 按顺序添加
        self.storage.add_to_shelf(b1)
        self.storage.add_to_shelf(b2)
        self.storage.add_to_shelf(b3)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_reverse_order(self):
        # 验证倒序排列：最新添加/更新的书籍排在最前面
        items = self.storage.load_shelf()
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0].book.title, "西游奸臣")
        self.assertEqual(items[1].book.title, "全球大佬团宠后")
        self.assertEqual(items[2].book.title, "诡舍")

    def test_voice_books_are_hidden_from_shelf(self):
        voice = Book(book_id="voice", title="有声书", media_genre=4)
        self.storage.add_to_shelf(voice)
        stale_voice = Book(book_id="7237435769856494652", title="金军围城，重生宋钦宗")
        self.storage.add_to_shelf(stale_voice)
        shelf = ShelfView(MockTerminal([]), self.mock_api, self.storage, self.mock_auth)
        visible_ids = [item.book.book_id for item in shelf._get_display_items()]
        self.assertNotIn("voice", visible_ids)
        self.assertNotIn(stale_voice.book_id, visible_ids)

    def test_enter_opens_highlighted_visible_book_when_hidden_audiobook_precedes_it(self):
        voice = Book("voice-first", "有声版", media_genre=4)
        self.storage.add_to_shelf(voice, added_at=9999999999)
        visible = self.storage.get_shelf_item("103")
        shelf = ShelfView(MockTerminal([KEY_ENTER, "q"]), self.mock_api, self.storage, self.mock_auth)

        with patch.object(shelf, "_open_book_reader") as open_reader:
            shelf.run()

        open_reader.assert_called_once()
        self.assertEqual(open_reader.call_args.args[0].book.book_id, visible.book.book_id)

    def test_open_prefers_cloud_chapter_id_even_when_local_timestamp_is_newer(self):
        book = Book("101", "诡舍", chapter_total=2)
        item = self.storage.add_to_shelf(book)
        self.storage.save_chapters_meta("101", [
            Chapter("c1", "第一章", index=0),
            Chapter("c2", "第二章", index=1),
        ])
        self.storage.update_progress("101", 0, "c1", "第一章", 0, book)
        self.mock_auth.is_logged_in.return_value = True
        self.mock_api.get_cloud_progress.return_value = [{
            "book_id": "101", "item_id": "c2", "index": "0", "read_timestamp": "100",
        }]
        term = MagicMock()
        term.get_size.return_value = (80, 24)
        shelf = ShelfView(term, self.mock_api, self.storage, self.mock_auth)

        with patch("fanqie_reader.ui.shelf_view.ReaderView") as reader_view:
            shelf._open_book_reader(item)

        self.assertEqual(reader_view.call_args.kwargs["initial_chapter_index"], 1)

    def test_filter_mode_with_physical_arrows(self):
        # 测试在书架按 '/' 进行过滤，并用物理上下键挑选书籍
        keys = [
            '/',            # 进入过滤模式
            '诡',           # 过滤 '诡'
            KEY_DOWN,       # 物理下键
            KEY_UP,         # 物理上键
            KEY_ESC,        # 退出过滤模式
            'q'             # 退出书架
        ]
        term = MockTerminal(keys)
        shelf = ShelfView(term, self.mock_api, self.storage, self.mock_auth)
        shelf.run()

        # 运行完毕无异常，过滤模式已退出
        self.assertFalse(shelf.filter_mode)

    def test_arrows_and_vim_keys_move_shelf_selection(self):
        shelf = ShelfView(
            MockTerminal([KEY_DOWN, "j", "k", "q"]),
            self.mock_api,
            self.storage,
            self.mock_auth,
        )

        shelf.run()

        self.assertEqual(shelf.cursor_pos, 1)

    def test_esc_does_not_crash_or_quit_in_normal_shelf(self):
        # 在普通书架模式下，按 KEY_ESC 绝不退出程序（只有按 'q' 才会退出）
        keys = [
            KEY_UP,
            KEY_ESC,
            KEY_DOWN,
            KEY_ESC,
            'q'
        ]
        term = MockTerminal(keys)
        shelf = ShelfView(term, self.mock_api, self.storage, self.mock_auth)
        shelf.run()
        self.assertEqual(len(shelf.shelf_items), 3)

if __name__ == "__main__":
    unittest.main()
