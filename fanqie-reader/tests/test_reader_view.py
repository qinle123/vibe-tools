import tempfile
import unittest
import re
from unittest.mock import MagicMock, patch

from fanqie_reader.models import Book, Chapter
from fanqie_reader.storage import StorageManager
from fanqie_reader.ui.reader_view import ReaderView
from fanqie_reader.ui.terminal import BG_YELLOW, KEY_UP, KEY_DOWN
from fanqie_reader.text_engine import str_visual_width


class MockTerminal:
    def __init__(self, keys=None, size=(80, 12)):
        self.output = []
        self.keys = list(keys or [])
        self.size = size

    def get_size(self):
        return self.size

    def write(self, value):
        self.output.append(value)

    def flush(self):
        pass

    def read_key(self, _timeout=0.5):
        return self.keys.pop(0) if self.keys else None


class TestReaderView(unittest.TestCase):
    def test_loading_screen_does_not_reset_saved_reading_offset(self):
        with tempfile.TemporaryDirectory() as directory:
            terminal = MockTerminal()
            storage = StorageManager(directory)
            storage.save_chapter_cache("101", "c1", "第一章", "阅读正文。" * 1000)
            reader = ReaderView(terminal, storage, Book("101", "测试书"),
                                [Chapter("c1", "第一章")], initial_line_offset=30)
            reader._prefetch_next_chapter = MagicMock()
            reader.load_current_chapter()
            self.assertEqual(reader.line_offset, 30)

    def test_reading_frame_stays_inside_narrow_terminal(self):
        with tempfile.TemporaryDirectory() as directory:
            for cols in (24, 40, 65, 80, 120):
                with self.subTest(cols=cols):
                    terminal = MockTerminal(size=(cols, 12))
                    reader = ReaderView(
                        terminal, StorageManager(directory),
                        Book("101", "很长的中文书名" * 10),
                        [Chapter("c1", "很长的章节标题" * 10)],
                    )
                    reader.formatted_lines = reader.layout_engine.layout_chapter(
                        "章节标题", "正文内容检查翻行，标点与中文。" * 30,
                    )
                    reader.render()
                    for row in re.split(r"\x1b\[\d+;1H|\n", terminal.output[-1]):
                        text = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", row)
                        self.assertLessEqual(str_visual_width(text), cols - 1)

    def test_render_does_not_scroll_screen_or_repaint_when_idle(self):
        with tempfile.TemporaryDirectory() as directory:
            terminal = MockTerminal()
            reader = ReaderView(terminal, StorageManager(directory),
                                Book("101", "测试书"), [Chapter("c1", "第一章")])
            reader.formatted_lines = [f"正文行{i}" for i in range(30)]
            reader.render()
            self.assertNotIn("\n", terminal.output[-1])
            self.assertIn("\x1b[12;1H", terminal.output[-1])
            reader.render()
            self.assertEqual(len(terminal.output), 1)

    def test_one_line_scroll_preserves_layout_and_overlapping_screen_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            terminal = MockTerminal(size=(65, 12))
            storage = StorageManager(directory)
            storage.save_chapter_cache("101", "c1", "第一章", "".join(f"第{i}段阅读正文。\n" for i in range(80)))
            reader = ReaderView(terminal, storage,
                                Book("101", "测试书"), [Chapter("c1", "第一章")])
            reader._prefetch_next_chapter = MagicMock()
            reader.load_current_chapter(reset_offset=True)
            reader.render()
            original = list(reader.formatted_lines)
            with patch.object(reader.layout_engine, "layout_chapter", wraps=reader.layout_engine.layout_chapter) as layout:
                for _ in range(8):
                    reader.line_offset += 1
                    reader.render()
                layout.assert_not_called()
            self.assertEqual(reader.formatted_lines, original)
            screen = {}
            for frame in terminal.output:
                parts = re.split(r"\x1b\[(\d+);1H", frame)
                for index in range(1, len(parts), 2):
                    screen[int(parts[index])] = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", parts[index + 1])
            for row in range(2, 12):
                self.assertEqual(screen[row].strip(), original[reader.line_offset + row - 2].strip())
                self.assertNotIn("帮助", screen[row])

    def test_resize_reflows_in_memory_and_preserves_reading_anchor(self):
        with tempfile.TemporaryDirectory() as directory:
            terminal = MockTerminal(size=(100, 12))
            storage = StorageManager(directory)
            storage.save_chapter_cache("101", "c1", "第一章", "\n".join(f"段{i:03d}：" + "阅读正文。" * 30 for i in range(30)))
            reader = ReaderView(terminal, storage,
                                Book("101", "测试书"), [Chapter("c1", "第一章")])
            reader._prefetch_next_chapter = MagicMock()
            reader.load_current_chapter(reset_offset=True)
            reader.line_offset = 30
            anchor = sum(len(line.strip()) for line in reader.formatted_lines[:reader.line_offset])
            terminal.size = (40, 12)
            reader.render()
            consumed = sum(len(line.strip()) for line in reader.formatted_lines[:reader.line_offset])
            self.assertLessEqual(consumed, anchor)
            self.assertLess(anchor - consumed, reader.layout_engine.content_width)
            self.assertLessEqual(max(map(str_visual_width, reader.formatted_lines)), 38)

    def test_switching_width_uses_loaded_content_without_refetch(self):
        with tempfile.TemporaryDirectory() as directory:
            terminal = MockTerminal(keys=["w", "q"], size=(120, 12))
            storage = StorageManager(directory)
            storage.save_chapter_cache("101", "c1", "第一章", "阅读正文。" * 1000)
            reader = ReaderView(terminal, storage,
                                Book("101", "测试书"), [Chapter("c1", "第一章")])
            reader._prefetch_next_chapter = MagicMock()
            reader.run()
            self.assertEqual(reader.layout_engine.content_width, 100)

    def test_small_help_and_long_toast_do_not_overflow_or_leave_help_residue(self):
        with tempfile.TemporaryDirectory() as directory:
            terminal = MockTerminal(keys=[KEY_DOWN, KEY_UP, "x"], size=(24, 6))
            reader = ReaderView(terminal, StorageManager(directory),
                                Book("101", "测试书"), [Chapter("c1", "第一章")])
            reader.formatted_lines = [f"正文行{i}" for i in range(12)]
            reader.render()
            reader.show_help_modal()
            self.assertEqual(reader.line_offset, 0)
            reader.show_toast("超长提示文字" * 30)
            reader.render()
            for frame in terminal.output:
                self.assertNotIn("\n", frame)
                parts = re.split(r"\x1b\[(\d+);1H", frame)
                for index in range(1, len(parts), 2):
                    self.assertLessEqual(int(parts[index]), 6)
                    text = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", parts[index + 1])
                    self.assertLessEqual(str_visual_width(text), 23)

    def test_arrows_scroll_without_changing_chapter_and_h_l_navigate_chapters(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = StorageManager(directory)
            book = Book("101", "测试书")
            storage.add_to_shelf(book)
            storage.save_chapter_cache("101", "c1", "第一章", "第一章正文。" * 40)
            storage.save_chapter_cache("101", "c2", "第二章", "第二章正文。" * 40)
            terminal = MockTerminal(keys=[KEY_UP, "j", "k", KEY_DOWN, "l", "h", "q"])
            reader = ReaderView(
                terminal, storage, book,
                [Chapter("c1", "第一章"), Chapter("c2", "第二章")],
            )
            reader._prefetch_next_chapter = MagicMock()

            reader.run()

            self.assertEqual(reader.chapter_index, 0)
            self.assertEqual(reader.line_offset, 0)

    def test_missing_local_cache_shows_download_hint(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = StorageManager(directory)
            book = Book("101", "测试书")
            storage.add_to_shelf(book)
            reader = ReaderView(
                MockTerminal(), storage, book, [Chapter("c1", "第一章")]
            )

            reader.load_current_chapter(reset_offset=True)

            self.assertTrue(any("暂不可用" in line for line in reader.formatted_lines))
            self.assertTrue(any("c" in line for line in reader.formatted_lines))

    def test_c_switches_source_and_reloads_chapter(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = StorageManager(directory)
            book = Book("101", "测试书", source_name="旧源")
            storage.add_to_shelf(book)
            storage.save_chapter_cache("101", "c1", "第一章", "旧源正文。" * 10)
            new_book = Book("101", "测试书", source_name="新源")
            new_chapters = [Chapter("c1", "第一章(新)")]

            def switch_cb(_book):
                storage.save_chapter_cache("101", "c1", "第一章(新)", "新源正文内容。")
                return new_book, new_chapters

            terminal = MockTerminal(keys=["c", "q"])
            reader = ReaderView(
                terminal, storage, book, [Chapter("c1", "第一章")],
                on_switch_source=switch_cb,
            )
            reader.run()

            self.assertEqual(reader.book.source_name, "新源")
            self.assertTrue(any("新源正文内容" in line for line in reader.formatted_lines))

    def test_d_and_u_scroll_half_view_and_flash_new_reading_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = StorageManager(directory)
            book = Book("101", "测试书")
            storage.add_to_shelf(book)
            reader = ReaderView(
                MockTerminal(), storage, book,
                [Chapter("c1", "第一章")],
            )
            reader.formatted_lines = [f"line{i}" for i in range(1, 31)]

            reader.scroll_half_page(1)
            self.assertEqual(reader.line_offset, 5)
            self.assertEqual(reader.highlight_line, 10)
            reader.render()
            self.assertIn(BG_YELLOW, "".join(reader.term.output))
            self.assertIn("line11", "".join(reader.term.output))

            reader.scroll_half_page(-1)
            self.assertEqual(reader.line_offset, 0)


if __name__ == "__main__":
    unittest.main()
