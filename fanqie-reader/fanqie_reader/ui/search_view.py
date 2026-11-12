from __future__ import annotations
import time
from typing import List, Optional

from ..models import Book
from ..api import FanqieAPI
from ..storage import StorageManager
from ..text_engine import str_visual_width, truncate_to_width, pad_to_width
from .terminal import (
    TerminalApp,
    RESET, BOLD, DIM, INVERSE,
    FG_GREEN, FG_CYAN, FG_YELLOW, FG_WHITE, FG_GRAY, FG_RED,
    BG_BLUE, BG_DARK_GRAY,
    KEY_UP, KEY_DOWN, KEY_PGUP, KEY_PGDN, KEY_HOME, KEY_END,
    KEY_ENTER, KEY_ESC, KEY_BACKSPACE, KEY_TAB
)

class SearchView:
    """小说在线搜索与添加视图（支持精准焦点切换与防折行排版）"""

    def __init__(self, term: TerminalApp, api: FanqieAPI, storage: StorageManager, initial_query: str = ""):
        self.term = term
        self.api = api
        self.storage = storage

        self.query: str = initial_query
        self.results: List[Book] = []
        self.cursor_pos: int = 0
        self.top_offset: int = 0
        self.is_searching: bool = False
        self.error_msg: str = ""
        self.toast_msg: str = ""
        self.toast_time: float = 0.0

        # 焦点控制：'input' 表示正在编辑搜索框，'list' 表示正在浏览选择结果
        self.focus: str = "input"

        if initial_query:
            self._do_search()
            if self.results:
                self.focus = "list"

    def show_toast(self, msg: str) -> None:
        self.toast_msg = msg
        self.toast_time = time.time() + 2.0

    def _do_search(self) -> None:
        if not self.query.strip():
            return
        
        self.is_searching = True
        self.error_msg = ""
        self.render()

        try:
            self.results = self.api.search_books(self.query.strip())
            self.cursor_pos = 0
            self.top_offset = 0
            if not self.results:
                self.error_msg = f"未找到与 '{self.query}' 相关的书籍。"
            self.focus = "input"
        except Exception as e:
            self.results = []
            self.error_msg = f"搜索出错: {e}"
            self.focus = "input"

        self.is_searching = False

    def _adjust_scroll(self, list_height: int) -> None:
        if self.cursor_pos < self.top_offset:
            self.top_offset = self.cursor_pos
        elif self.cursor_pos >= self.top_offset + list_height:
            self.top_offset = self.cursor_pos - list_height + 1

    def render(self) -> None:
        cols, rows = self.term.get_size()
        preview_height = 5
        list_height = max(1, rows - 5 - preview_height)

        buffer = []
        buffer.append("\033[H")

        # 1. 顶部标题栏
        top_title = " 🔍 全网小说搜索"
        top_meta = "番茄官方在线资源库 "
        gap = max(1, cols - str_visual_width(top_title) - str_visual_width(top_meta))
        header = top_title + (" " * gap) + top_meta
        buffer.append(f"{INVERSE}{BOLD}{truncate_to_width(header, cols)}{RESET}\n")

        # 2. 搜索输入框
        prompt = " 输入书名/作者: "
        disp_q = self.query
        if self.focus == "input":
            q_color = f"{FG_YELLOW}{BOLD}"
            if self.results:
                box_hint = "[回车重新搜索 ↵ | ↓ 选书]"
            else:
                box_hint = "[回车搜索 ↵]"
        else:
            q_color = f"{FG_WHITE}"
            box_hint = "[↑/↓ j/k 选书 | Tab 编辑]"

        status_info = "正在搜索..." if self.is_searching else f"共找到 {len(self.results)} 本  {box_hint}"
        
        prefix = prompt
        p_w = str_visual_width(prefix)
        s_w = str_visual_width(status_info)
        avail_q_w = max(10, cols - p_w - s_w - 2)
        q_text = truncate_to_width(disp_q, avail_q_w)
        
        cur_bar_w = p_w + str_visual_width(q_text) + s_w
        s_gap = max(1, cols - cur_bar_w)
        search_bar = prefix + f"{q_color}{q_text}{RESET}" + (" " * s_gap) + f"{FG_GRAY}{status_info}{RESET}"
        buffer.append(f"\033[K{search_bar}\n")
        buffer.append(f"\033[K{FG_GRAY}{'─' * cols}{RESET}\n")

        # 3. 搜索结果列表
        if self.error_msg:
            pad_y = max(1, list_height // 2)
            for _ in range(pad_y):
                buffer.append("\033[K\n")
            buffer.append(f"\033[K  {FG_RED}{self.error_msg}{RESET}\n")
            for _ in range(list_height - pad_y - 1):
                buffer.append("\033[K\n")
        else:
            visible_books = self.results[self.top_offset : self.top_offset + list_height]
            for v_idx in range(list_height):
                if v_idx < len(visible_books):
                    real_idx = self.top_offset + v_idx
                    book = visible_books[v_idx]
                    is_selected = (self.focus == "list" and real_idx == self.cursor_pos)
                    in_shelf = "★已在书架" if self.storage.is_in_shelf(book.book_id) else " +可加入"

                    # 宽度规划，严格防止换行：
                    # 序号占 4 列，状态占 10 列，剩余给 书名 + 作者 + 分类
                    fixed_w = 4 + 10 + 2
                    remain_w = max(20, cols - fixed_w)
                    
                    title_w = int(remain_w * 0.55)
                    author_w = int(remain_w * 0.25)
                    cat_w = remain_w - title_w - author_w

                    idx_str = f" {real_idx + 1:2d}. "
                    title_str = truncate_to_width(book.title, title_w, ellipsis="..")
                    title_pad = pad_to_width(title_str, title_w)

                    author_display = f"[{book.author}]" if book.author else ""
                    author_str = truncate_to_width(author_display, author_w, ellipsis="..")
                    author_pad = pad_to_width(author_str, author_w)

                    cat_display = f"({book.category})" if book.category else ""
                    cat_str = truncate_to_width(cat_display, cat_w, ellipsis="..")
                    cat_pad = pad_to_width(cat_str, cat_w)

                    state_pad = pad_to_width(f" {in_shelf}", 10, align="right")

                    line_content = f"{idx_str}{title_pad} {author_pad} {cat_pad}{state_pad}"
                    # 保证整行宽度绝不超过 cols
                    final_line = truncate_to_width(line_content, cols)
                    final_line = pad_to_width(final_line, cols)

                    if is_selected:
                        buffer.append(f"\033[K{BG_BLUE}{FG_WHITE}{BOLD}{final_line}{RESET}\n")
                    else:
                        buffer.append(f"\033[K{final_line}\n")
                else:
                    buffer.append("\033[K\n")

        # 4. 底部详情预览框
        buffer.append(f"\033[K{FG_GRAY}{'─' * cols}{RESET}\n")
        if self.results and 0 <= self.cursor_pos < len(self.results):
            cur_book = self.results[self.cursor_pos]
            abs_text = cur_book.abstract.replace("\n", " ").strip()
            if not abs_text:
                abs_text = "暂无简介。"
            p1 = truncate_to_width(abs_text, cols - 8)
            remain_abs = abs_text[len(p1):].lstrip()
            p2 = truncate_to_width(remain_abs, cols - 8)
            buffer.append(f"\033[K  {FG_CYAN}简介:{RESET} {p1}\n")
            buffer.append(f"\033[K        {p2}\n")
        else:
            buffer.append("\033[K\n\033[K\n")

        # 5. 底部状态与操作指引
        if self.toast_msg and time.time() < self.toast_time:
            footer = f" {FG_GREEN}✔ {self.toast_msg}{RESET}"
            buffer.append(f"{INVERSE}{pad_to_width(footer, cols)}{RESET}")
        else:
            if self.focus == "input":
                b_left = " [Enter]开始搜索  [↓/Tab]切换到结果列表  [Esc]返回书架"
                b_right = " 模式: 编辑搜索词 "
            else:
                b_left = " [Enter]阅读  [a]加入书架  [↑/↓]选择书籍  [Tab/文字]编辑搜索词"
                b_right = " 模式: 选择结果 "
            
            b_gap = max(1, cols - str_visual_width(b_left) - str_visual_width(b_right))
            footer = b_left + (" " * b_gap) + b_right
            buffer.append(f"{INVERSE}{truncate_to_width(footer, cols)}{RESET}")

        self.term.write("".join(buffer))
        if self.focus == "input":
            # 物理光标定位到输入框文字末尾，使 macOS 系统输入法候选词浮窗精准弹出
            cursor_col = min(cols, 1 + p_w + str_visual_width(self.query))
            self.term.move_cursor(cursor_col, 2)
            self.term.show_cursor()
        else:
            self.term.hide_cursor()
        self.term.flush()

    def run(self) -> Optional[Book]:
        """运行搜索循环，若用户选中开读则返回 Book 对象，否则返回 None"""
        try:
            while True:
                self.render()
                key = self.term.read_key(0.5, text_input=self.focus == "input")
                if not key:
                    continue

                cols, rows = self.term.get_size()
                list_height = max(1, rows - 10)

                # 退出返回书架
                if key == KEY_ESC:
                    return None

                # 无论在哪种焦点下，物理方向下键统一行为：下移列表项
                if key == KEY_DOWN or (self.focus == "list" and key == 'j'):
                    if self.focus == "input":
                        if self.results:
                            self.focus = "list"
                            self.cursor_pos = 0
                            self.top_offset = 0
                    else:
                        if self.cursor_pos < len(self.results) - 1:
                            self.cursor_pos += 1
                            self._adjust_scroll(list_height)
                    continue

                # 方向键只操作结果列表，不隐式切换焦点。
                if key == KEY_UP or (self.focus == "list" and key == 'k'):
                    if self.focus == "list":
                        if self.cursor_pos > 0:
                            self.cursor_pos -= 1
                            self._adjust_scroll(list_height)
                    continue

                if self.focus == "input":
                    # ── 输入框编辑模式 ──
                    if key == KEY_ENTER:
                        self._do_search()

                    elif key == KEY_TAB:
                        if self.results:
                            self.focus = "list"
                            self.cursor_pos = 0
                            self.top_offset = 0

                    elif key == KEY_BACKSPACE:
                        if self.query:
                            self.query = self.query[:-1]

                    elif key == '\x15':  # Ctrl+U 清空搜索框
                        self.query = ""

                    elif not key.startswith("KEY_") and (ord(key[0]) >= 32 or ord(key[0]) > 127):
                        # 文本键入（排除控制键常量，支持输入法批量提交中英文字符）
                        self.query += key

                else:
                    # ── 搜索结果列表浏览模式 ──
                    if key == KEY_PGUP:
                        self.cursor_pos = max(0, self.cursor_pos - list_height)
                        self._adjust_scroll(list_height)

                    elif key == KEY_PGDN:
                        self.cursor_pos = min(max(0, len(self.results) - 1), self.cursor_pos + list_height)
                        self._adjust_scroll(list_height)

                    elif key == KEY_HOME:
                        self.cursor_pos = 0
                        self._adjust_scroll(list_height)

                    elif key == KEY_END:
                        self.cursor_pos = max(0, len(self.results) - 1)
                        self._adjust_scroll(list_height)

                    elif key == KEY_ENTER:
                        # 列表按回车：打开选中的书籍开始阅读！
                        if self.results and 0 <= self.cursor_pos < len(self.results):
                            chosen = self.results[self.cursor_pos]
                            self.storage.add_to_shelf(chosen)
                            return chosen

                    elif key == 'a':
                        # 加入书架
                        if self.results and 0 <= self.cursor_pos < len(self.results):
                            target = self.results[self.cursor_pos]
                            self.storage.add_to_shelf(target)
                            self.show_toast(f"《{target.title}》已加入书架 ★")

                    elif key == KEY_TAB:
                        self.focus = "input"

                    elif key == KEY_BACKSPACE:
                        self.focus = "input"
                        if self.query:
                            self.query = self.query[:-1]

                    elif not key.startswith("KEY_") and (ord(key[0]) >= 32 or ord(key[0]) > 127):
                        # 在列表中直接打字，无缝切回输入框并追加输入内容
                        self.focus = "input"
                        self.query += key
        finally:
            self.term.hide_cursor()
