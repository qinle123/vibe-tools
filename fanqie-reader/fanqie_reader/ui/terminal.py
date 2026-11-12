from __future__ import annotations
import sys
import os
import tty
import termios
import select
import signal
import shutil
import codecs
import time
from collections import deque
from typing import Optional, Tuple, Callable

# ANSI 控制码
CSI = "\033["
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
ITALIC = "\033[3m"
UNDERLINE = "\033[4m"
INVERSE = "\033[7m"

# 颜色
FG_BLACK = "\033[30m"
FG_RED = "\033[31m"
FG_GREEN = "\033[32m"
FG_YELLOW = "\033[33m"
FG_BLUE = "\033[34m"
FG_MAGENTA = "\033[35m"
FG_CYAN = "\033[36m"
FG_WHITE = "\033[37m"
FG_GRAY = "\033[90m"

BG_BLACK = "\033[40m"
BG_RED = "\033[41m"
BG_GREEN = "\033[42m"
BG_YELLOW = "\033[43m"
BG_BLUE = "\033[44m"
BG_MAGENTA = "\033[45m"
BG_CYAN = "\033[46m"
BG_WHITE = "\033[47m"
BG_DARK_GRAY = "\033[100m"

# 按键常量
KEY_UP = "KEY_UP"
KEY_DOWN = "KEY_DOWN"
KEY_LEFT = "KEY_LEFT"
KEY_RIGHT = "KEY_RIGHT"
KEY_PGUP = "KEY_PGUP"
KEY_PGDN = "KEY_PGDN"
KEY_HOME = "KEY_HOME"
KEY_END = "KEY_END"
KEY_ENTER = "KEY_ENTER"
KEY_ESC = "KEY_ESC"
KEY_BACKSPACE = "KEY_BACKSPACE"
KEY_TAB = "KEY_TAB"

class TerminalApp:
    """底层终端驱动：负责原始模式切换、按键事件与清爽绘图"""

    def __init__(self):
        self.old_termios = None
        self._is_raw = False
        self.winch_callback: Optional[Callable[[], None]] = None
        self._char_buffer = deque()
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

    def enter_raw_mode(self) -> None:
        if not sys.stdin.isatty():
            return
        self.old_termios = termios.tcgetattr(sys.stdin)
        tty.setcbreak(sys.stdin.fileno())
        self._is_raw = True

        # 进入备用屏幕缓冲区并隐藏光标
        sys.stdout.write(f"{CSI}?1049h{CSI}?25l")
        sys.stdout.flush()

        # 监听终端大小变化
        signal.signal(signal.SIGWINCH, self._on_sigwinch)

    def restore_mode(self) -> None:
        if self._is_raw and self.old_termios is not None:
            # 显示光标并退出备用缓冲区
            sys.stdout.write(f"{CSI}?25h{CSI}?1049l{RESET}")
            sys.stdout.flush()
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.old_termios)
            self._is_raw = False

    def _on_sigwinch(self, signum, frame):
        if self.winch_callback:
            self.winch_callback()

    def get_size(self) -> Tuple[int, int]:
        """返回 (cols, rows)"""
        size = shutil.get_terminal_size((80, 24))
        return size.columns, size.lines

    def _read_char(self, timeout: Optional[float]) -> Optional[str]:
        """只读文件描述符；select 看不到 TextIOWrapper 预读的内容。"""
        deadline = None if timeout is None else time.monotonic() + timeout
        while not self._char_buffer:
            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            fd = sys.stdin.fileno()
            ready, _, _ = select.select([fd], [], [], remaining)
            if not ready:
                return None
            data = os.read(fd, 4096)
            if not data:
                return None
            # UTF-8 可能跨多次读取，保留尚未完整解码的字节。
            self._char_buffer.extend(self._decoder.decode(data))
        return self._char_buffer.popleft()

    def _read_escape_key(self) -> Optional[str]:
        """完整消费 CSI/SS3；只有单独的 ESC 才触发返回。"""
        ch2 = self._read_char(0.1)
        if ch2 is None:
            return KEY_ESC
        if ch2 not in ('[', 'O'):
            self._char_buffer.appendleft(ch2)
            return KEY_ESC

        seq = ""
        for _ in range(64):
            char = self._read_char(0.1)
            if char is None:
                return None
            if char == '\x1b':
                self._char_buffer.appendleft(char)
                return None
            seq += char
            if '@' <= char <= '~':
                if char == '~':
                    return {
                        '1': KEY_HOME, '7': KEY_HOME,
                        '4': KEY_END, '8': KEY_END,
                        '5': KEY_PGUP, '6': KEY_PGDN, '3': KEY_BACKSPACE,
                    }.get(seq[:-1].split(';')[0])
                return {
                    'A': KEY_UP, 'B': KEY_DOWN,
                    'C': KEY_RIGHT, 'D': KEY_LEFT,
                    'H': KEY_HOME, 'F': KEY_END,
                }.get(char)
        return None

    def _read_key_event(self, timeout: Optional[float]) -> Optional[str]:
        char = self._read_char(timeout)
        if char == '\x1b':
            return self._read_escape_key()
        return {
            '\r': KEY_ENTER, '\n': KEY_ENTER,
            '\t': KEY_TAB, '\x7f': KEY_BACKSPACE, '\x08': KEY_BACKSPACE,
            '\x10': KEY_UP, '\x0e': KEY_DOWN,  # Ctrl+P / Ctrl+N
            '\x02': KEY_LEFT, '\x06': KEY_RIGHT,  # Ctrl+B / Ctrl+F
            '\x01': KEY_HOME, '\x05': KEY_END,  # Ctrl+A / Ctrl+E
        }.get(char, char)

    def read_key(self, timeout: Optional[float] = None, *, text_input: bool = False) -> Optional[str]:
        """导航态逐键返回；输入态可批量返回文本，控制键始终单独分发。"""
        if not sys.stdin.isatty():
            return None

        key = self._read_key_event(timeout)
        if text_input and key and len(key) == 1 and key.isprintable():
            chars = [key]
            while True:
                nxt = self._read_char(0.005)
                if nxt is None:
                    break
                if not nxt.isprintable():
                    self._char_buffer.appendleft(nxt)
                    break
                chars.append(nxt)
            return "".join(chars)
        return key


    def clear(self) -> None:
        sys.stdout.write(f"{CSI}2J{CSI}H")
        sys.stdout.flush()

    def move_cursor(self, col: int, row: int) -> None:
        sys.stdout.write(f"{CSI}{row};{col}H")

    def show_cursor(self) -> None:
        sys.stdout.write(f"{CSI}?25h")
        sys.stdout.flush()

    def hide_cursor(self) -> None:
        sys.stdout.write(f"{CSI}?25l")
        sys.stdout.flush()

    def write(self, s: str) -> None:
        sys.stdout.write(s)

    def flush(self) -> None:
        sys.stdout.flush()
