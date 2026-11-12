import unittest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock

from fanqie_reader.models import Book
from fanqie_reader.storage import StorageManager
from fanqie_reader.ui.search_view import SearchView
from fanqie_reader.ui.terminal import (
    KEY_UP, KEY_DOWN, KEY_ENTER, KEY_ESC, KEY_TAB, KEY_BACKSPACE
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
        self.mock_api = MagicMock()
        self.mock_api.search_books.return_value = [
            Book(book_id="b1", title="剑来", author="烽火戏诸侯", category="仙侠"),
            Book(book_id="b2", title="雪中悍刀行", author="烽火戏诸侯", category="武侠"),
        ]

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_input_text_not_intercepted_by_vim_keys(self):
        # 用户输入包含 'k', 'j', 'a' 的搜索词并按回车
        keys = ['j', 'i', 'a', 'n', KEY_ENTER, KEY_ESC]
        mock_term = MockTerminal(keys)

        view = SearchView(mock_term, self.mock_api, self.storage)
        chosen = view.run()

        self.assertIsNone(chosen)
        self.assertEqual(view.query, "jian")
        self.mock_api.search_books.assert_called_with("jian")
        # 搜索完成后焦点保持在 input 状态，未强制变成 list
        self.assertEqual(view.focus, "input")

    def test_arrows_select_results_without_moving_focus_and_letters_return_to_input(self):
        keys = [
            'x', KEY_ENTER,     # 搜索 'x'
            KEY_DOWN,           # 聚焦到 list 选中第 0 项
            KEY_DOWN,           # 下移到第 1 项
            KEY_UP,             # 上移回到第 0 项
            KEY_UP,             # 到达顶部仍保持列表焦点
            'j', 'k',           # 非输入态下兼容 Vim 导航
            'a',                # 列表快捷键：加入书架
            KEY_TAB, 'j', 'k',   # 返回输入框后 j/k 为普通文本
            KEY_ESC
        ]
        mock_term = MockTerminal(keys)
        view = SearchView(mock_term, self.mock_api, self.storage)
        chosen = view.run()

        self.assertIsNone(chosen)
        self.assertEqual(view.focus, "input")
        self.assertEqual(view.query, "xjk")

    def test_open_book_from_list_enter(self):
        # 搜索后按 KEY_DOWN 进入列表，然后按 KEY_ENTER 选书开读
        keys = [
            'j', 'i', 'a', 'n', KEY_ENTER, # 搜索
            KEY_DOWN,                      # 进入列表第 0 项
            KEY_ENTER                      # 回车选书
        ]
        mock_term = MockTerminal(keys)
        view = SearchView(mock_term, self.mock_api, self.storage)
        chosen = view.run()

        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.book_id, "b1")
        self.assertTrue(self.storage.is_in_shelf("b1"))

if __name__ == "__main__":
    unittest.main()
