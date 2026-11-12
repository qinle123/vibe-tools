import os
import pty
import sys
import tty
import unittest
from unittest.mock import patch

from fanqie_reader.ui.terminal import KEY_DOWN, KEY_ESC, KEY_UP, TerminalApp


class TestTerminal(unittest.TestCase):
    def _read_keys(self, data, count, text_input=False):
        master, slave = pty.openpty()
        try:
            tty.setcbreak(slave)
            with os.fdopen(slave, "r", encoding="utf-8") as stdin:
                os.write(master, data)
                with patch.object(sys, "stdin", stdin):
                    term = TerminalApp()
                    return [term.read_key(0.5, text_input=text_input) for _ in range(count)]
        finally:
            os.close(master)

    def test_real_pty_arrow_is_not_misread_as_escape(self):
        self.assertEqual(self._read_keys(b"\x1b[B", 1), [KEY_DOWN])

    def test_application_cursor_sequence_and_escape_after_text(self):
        self.assertEqual(
            self._read_keys("剑来\x1bOA\x1b".encode(), 3, text_input=True),
            ["剑来", KEY_UP, KEY_ESC],
        )

    def test_navigation_mode_preserves_repeated_vim_keys(self):
        self.assertEqual(self._read_keys(b"jkl", 3), ["j", "k", "l"])


if __name__ == "__main__":
    unittest.main()
