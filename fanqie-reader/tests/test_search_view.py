import unittest
import tempfile
import shutil
from unittest.mock import MagicMock

from fanqie_reader.models import Book, Chapter, SourceBook, make_local_book_id
from fanqie_reader.storage import StorageManager
from fanqie_reader.ui.search_view import SearchView
from fanqie_reader.ui.terminal import (
    KEY_UP, KEY_DOWN, KEY_ENTER, KEY_ESC, KEY_TAB
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
        return KEY_ESC


class TestSearchView(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.storage = StorageManager(base_dir=self.test_dir)
        self.mock_source = MagicMock()
        self.mock_source.rules = [{"name": "香书小说"}]
        self.mock_source.search_all.return_value = [
            SourceBook(
                source_name="香书小说",
                source_base_url="http://www.ibiqugu.net/",
                book_url="http://www.ibiqugu.net/1/1/",
                title="剑来",
                author="烽火戏诸侯",
                category="仙侠",
            ),
            SourceBook(
                source_name="书海阁小说网",
                source_base_url="https://www.shuhaige.net/",
                book_url="https://www.shuhaige.net/2/",
                title="雪中悍刀行",
                author="烽火戏诸侯",
                category="武侠",
            ),
        ]

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_input_text_not_intercepted_by_vim_keys(self):
        keys = ['j', 'i', 'a', 'n', KEY_ENTER, KEY_ESC]
        mock_term = MockTerminal(keys)

        view = SearchView(mock_term, self.mock_source, self.storage)
        chosen = view.run()

        self.assertIsNone(chosen)
        self.assertEqual(view.query, "jian")
        self.mock_source.search_all.assert_called_once()

    def test_arrows_select_results_and_tab_returns_to_input(self):
        keys = [
            'x', KEY_ENTER,     # 搜索 'x' (有结果后自动聚焦到 list)
            KEY_DOWN,           # 下移到第 1 项
            KEY_UP,             # 上移回到第 0 项
            'j', 'k',           # 列表态下 Vim 导航
            'a',                # 列表快捷键：加入书架
            KEY_TAB, 'j', 'k',  # 返回输入框后 j/k 为普通文本
            KEY_ESC
        ]
        mock_term = MockTerminal(keys)
        view = SearchView(mock_term, self.mock_source, self.storage)
        chosen = view.run()

        self.assertIsNone(chosen)
        self.assertEqual(view.focus, "input")
        self.assertEqual(view.query, "xjk")
        self.assertTrue(self.storage.is_in_shelf(make_local_book_id("剑来", "烽火戏诸侯")))

    def test_open_book_from_list_enter_downloads_and_returns_book(self):
        def fake_download(_sb, storage, book, progress_cb=None):
            ch = Chapter("ch_00000", "第一章", index=0)
            storage.save_chapters_meta(book.book_id, [ch])
            storage.save_chapter_cache(book.book_id, ch.item_id, ch.title, "正文内容")
            storage.add_to_shelf(book)
            return [ch]

        self.mock_source.download_book.side_effect = fake_download
        keys = [
            'j', 'i', 'a', 'n', KEY_ENTER,
            KEY_ENTER
        ]
        mock_term = MockTerminal(keys)
        view = SearchView(mock_term, self.mock_source, self.storage)
        chosen = view.run()

        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.title, "剑来")
        self.assertTrue(self.storage.is_book_downloaded(chosen.book_id))


if __name__ == "__main__":
    unittest.main()
