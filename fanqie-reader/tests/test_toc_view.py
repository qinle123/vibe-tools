import unittest

from fanqie_reader.models import Chapter
from fanqie_reader.ui.toc_view import TOCView
from fanqie_reader.ui.terminal import KEY_DOWN, KEY_ENTER, KEY_UP


class MockTerminal:
    def __init__(self, keys):
        self.keys = list(keys)

    def get_size(self):
        return 80, 24

    def write(self, _value):
        pass

    def flush(self):
        pass

    def read_key(self, _timeout=0.5, *, text_input=False):
        return self.keys.pop(0)


class TestTOCView(unittest.TestCase):
    def test_arrow_keys_move_selection_after_filtering(self):
        chapters = [Chapter(f"c{i}", f"第{i + 1}章") for i in range(3)]
        view = TOCView(MockTerminal(["/", "章", KEY_DOWN, KEY_UP, KEY_DOWN, KEY_ENTER]), chapters)

        self.assertEqual(view.run(), 1)

    def test_j_and_k_navigate_when_filter_is_empty(self):
        chapters = [Chapter("c1", "第一章"), Chapter("c2", "正文含jk字符")]
        view = TOCView(MockTerminal(["j", "k", KEY_ENTER]), chapters)

        self.assertEqual(view.run(), 0)

    def test_j_and_k_remain_search_text_after_filter_starts(self):
        chapters = [Chapter("c1", "第一章"), Chapter("c2", "正文含jk字符")]
        view = TOCView(MockTerminal(["/", "j", "k", KEY_ENTER]), chapters)

        self.assertEqual(view.run(), 1)
        self.assertEqual(view.filter_text, "jk")


if __name__ == "__main__":
    unittest.main()
