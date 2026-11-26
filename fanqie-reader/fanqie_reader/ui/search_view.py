from __future__ import annotations
import time
from typing import List, Optional

from ..models import Book, SourceBook, make_local_book_id
from ..sources import SourceManager
from ..storage import StorageManager
from ..text_engine import str_visual_width, truncate_to_width, pad_to_width
from .terminal import (
    TerminalApp,
    RESET, BOLD, INVERSE,
    FG_GREEN, FG_CYAN, FG_YELLOW, FG_WHITE, FG_GRAY, FG_RED,
    BG_BLUE,
    KEY_UP, KEY_DOWN, KEY_PGUP, KEY_PGDN, KEY_HOME, KEY_END,
    KEY_ENTER, KEY_ESC, KEY_BACKSPACE, KEY_TAB
)


class SearchView:
    """全网书源聚合搜索与直接下载视图"""

    def __init__(
        self,
        term: TerminalApp,
        source_manager: SourceManager,
        storage: StorageManager,
        initial_query: str = "",
    ):
        self.term = term
        self.source_manager = source_manager
        self.storage = storage

        self.query: str = initial_query
        self.results: List[SourceBook] = []
        self.cursor_pos: int = 0
        self.top_offset: int = 0
        self.is_searching: bool = False
        self.search_status: str = ""
        self.error_msg: str = ""
        self.toast_msg: str = ""
        self.toast_time: float = 0.0

        self.focus: str = "input"

        if initial_query:
            self._do_search()
            if self.results:
                self.focus = "list"

    def show_toast(self, msg: str) -> None:
        self.toast_msg = msg
        self.toast_time = time.time() + 2.5

    def _find_or_build_book(self, sb: SourceBook) -> Book:
        """If a book with the same title+author is already in shelf, reuse its book_id."""
        for item in self.storage.load_shelf():
            if item.book.title.strip() == sb.title.strip() and (
                not item.book.author or not sb.author or item.book.author.strip() == sb.author.strip()
            ):
                b = item.book
                b.source_name = sb.source_name
                b.source_url = sb.book_url
                if not b.author and sb.author:
                    b.author = sb.author
                if not b.abstract and sb.intro:
                    b.abstract = sb.intro
                return b

        return Book(
            book_id=make_local_book_id(sb.title, sb.author),
            title=sb.title,
            author=sb.author,
            abstract=sb.intro,
            category=sb.category,
            source_name=sb.source_name,
            source_url=sb.book_url,
        )

    def _do_search(self) -> None:
        if not self.query.strip():
            return

        self.is_searching = True
        self.error_msg = ""
        self.search_status = "正在检索可用书源..."
        self.render()

        def _on_progress(done: int, total: int, src_name: str) -> None:
            self.search_status = f"正在搜索 ({done}/{total}): {src_name}..."
            self.render()

        try:
            self.results = self.source_manager.search_all(
                self.query.strip(),
                on_progress=_on_progress,
            )
            self.cursor_pos = 0
            self.top_offset = 0
            if not self.results:
                self.error_msg = f"未在可用书源中找到与 '{self.query}' 相关的书籍。"
            self.focus = "list" if self.results else "input"
        except Exception as e:
            self.results = []
            self.error_msg = f"搜索出错: {e}"
            self.focus = "input"

        self.is_searching = False
        self.search_status = ""

    def _download_and_open(self, sb: SourceBook) -> Optional[Book]:
        book = self._find_or_build_book(sb)
        if self.storage.is_book_downloaded(book.book_id) and book.source_url == sb.book_url:
            self.storage.add_to_shelf(book)
            return book

        self.is_searching = True
        self.error_msg = ""
        self.search_status = f"正在从 [{sb.source_name}] 获取《{sb.title}》目录..."
        self.render()

        last_render = [0.0]

        def _on_dl_progress(done: int, total: int, ch_title: str, failed: int) -> None:
            now = time.monotonic()
            if done == total or now - last_render[0] >= 0.15:
                pct = int(done / max(1, total) * 100)
                fail_note = f" (失败 {failed})" if failed else ""
                self.search_status = f"下载分章 [{sb.source_name}] {done}/{total} ({pct}%){fail_note}"
                self.render()
                last_render[0] = now

        try:
            self.source_manager.download_book(sb, self.storage, book, progress_cb=_on_dl_progress)
            self.is_searching = False
            self.search_status = ""
            return book
        except Exception as e:
            self.is_searching = False
            self.search_status = ""
            self.show_toast(f"下载失败: {e}")
            return None

    def _adjust_scroll(self, list_height: int) -> None:
        if self.cursor_pos < self.top_offset:
            self.top_offset = self.cursor_pos
        elif self.cursor_pos >= self.top_offset + list_height:
            self.top_offset = self.cursor_pos - list_height + 1

    def render(self) -> None:
        cols, rows = self.term.get_size()
        preview_height = 5
        list_height = max(1, rows - 5 - preview_height)

        buffer = ["\033[H"]

        # 1. 顶部标题栏
        top_title = " 🔍 全网小说搜索下载"
        top_meta = f"so-novel 多书源 ({len(self.source_manager.rules)}源) "
        gap = max(1, cols - str_visual_width(top_title) - str_visual_width(top_meta))
        header = top_title + (" " * gap) + top_meta
        buffer.append(f"{INVERSE}{BOLD}{truncate_to_width(header, cols)}{RESET}\n")

        # 2. 搜索输入框
        prompt = " 输入书名/作者: "
        disp_q = self.query
        if self.focus == "input":
            q_color = f"{FG_YELLOW}{BOLD}"
            box_hint = "[回车重新搜索 ↵ | ↓ 选书]" if self.results else "[回车搜索 ↵]"
        else:
            q_color = f"{FG_WHITE}"
            box_hint = "[↑/↓ j/k 选书 | Tab 编辑]"

        status_info = self.search_status if self.is_searching else f"共找到 {len(self.results)} 条  {box_hint}"

        p_w = str_visual_width(prompt)
        s_w = str_visual_width(status_info)
        avail_q_w = max(10, cols - p_w - s_w - 2)
        q_text = truncate_to_width(disp_q, avail_q_w)

        s_gap = max(1, cols - p_w - str_visual_width(q_text) - s_w)
        search_bar = prompt + f"{q_color}{q_text}{RESET}" + (" " * s_gap) + f"{FG_GRAY}{status_info}{RESET}"
        buffer.append(f"\033[K{search_bar}\n")
        buffer.append(f"\033[K{FG_GRAY}{'─' * cols}{RESET}\n")

        # 3. 搜索结果列表
        if self.error_msg:
            pad_y = max(1, list_height // 2)
            for _ in range(pad_y):
                buffer.append("\033[K\n")
            buffer.append(f"\033[K  {FG_RED}{self.error_msg}{RESET}\n")
            for _ in range(max(0, list_height - pad_y - 1)):
                buffer.append("\033[K\n")
        else:
            visible_books = self.results[self.top_offset : self.top_offset + list_height]
            for v_idx in range(list_height):
                if v_idx < len(visible_books):
                    real_idx = self.top_offset + v_idx
                    sb = visible_books[v_idx]
                    is_selected = (self.focus == "list" and real_idx == self.cursor_pos)

                    cand_id = make_local_book_id(sb.title, sb.author)
                    if self.storage.is_book_downloaded(cand_id):
                        in_shelf = "★已下载"
                    elif self.storage.is_in_shelf(cand_id):
                        in_shelf = "☆在书架"
                    else:
                        in_shelf = "+可下载"

                    fixed_w = 4 + 10 + 2
                    remain_w = max(20, cols - fixed_w)

                    title_w = int(remain_w * 0.42)
                    author_w = int(remain_w * 0.23)
                    src_w = remain_w - title_w - author_w

                    idx_str = f" {real_idx + 1:2d}. "
                    title_pad = pad_to_width(truncate_to_width(sb.title, title_w, ellipsis=".."), title_w)
                    author_display = f"[{sb.author}]" if sb.author else ""
                    author_pad = pad_to_width(truncate_to_width(author_display, author_w, ellipsis=".."), author_w)
                    src_display = f"({sb.source_name})"
                    src_pad = pad_to_width(truncate_to_width(src_display, src_w, ellipsis=".."), src_w)
                    state_pad = pad_to_width(f" {in_shelf}", 10, align="right")

                    line_content = f"{idx_str}{title_pad} {author_pad} {src_pad}{state_pad}"
                    final_line = pad_to_width(truncate_to_width(line_content, cols), cols)

                    if is_selected:
                        buffer.append(f"\033[K{BG_BLUE}{FG_WHITE}{BOLD}{final_line}{RESET}\n")
                    else:
                        buffer.append(f"\033[K{final_line}\n")
                else:
                    buffer.append("\033[K\n")

        # 4. 底部详情预览框
        buffer.append(f"\033[K{FG_GRAY}{'─' * cols}{RESET}\n")
        if self.results and 0 <= self.cursor_pos < len(self.results):
            cur = self.results[self.cursor_pos]
            latest_line = f"书源: {cur.source_name}  最新: {cur.latest_chapter or '未知'}  更新: {cur.last_update_time or '未知'}"
            abs_text = (cur.intro or "").replace("\n", " ").strip() or "选中后按 Enter 自动下载并分章阅读。"
            buffer.append(f"\033[K  {FG_CYAN}来源:{RESET} {truncate_to_width(latest_line, cols - 8)}\n")
            buffer.append(f"\033[K  {FG_GRAY}简介:{RESET} {truncate_to_width(abs_text, cols - 8)}\n")
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
                b_left = " [Enter]下载并阅读  [a]加入书架  [↑/↓]选择书籍  [Tab]编辑搜索词"
                b_right = " 模式: 选择结果 "

            b_gap = max(1, cols - str_visual_width(b_left) - str_visual_width(b_right))
            footer = b_left + (" " * b_gap) + b_right
            buffer.append(f"{INVERSE}{truncate_to_width(footer, cols)}{RESET}")

        self.term.write("".join(buffer))
        if self.focus == "input":
            cursor_col = min(cols, 1 + p_w + str_visual_width(self.query))
            self.term.move_cursor(cursor_col, 2)
            self.term.show_cursor()
        else:
            self.term.hide_cursor()
        self.term.flush()

    def run(self) -> Optional[Book]:
        """运行搜索循环，若用户选中下载并开读则返回 Book 对象，否则返回 None"""
        try:
            while True:
                self.render()
                key = self.term.read_key(0.5, text_input=self.focus == "input")
                if not key:
                    continue

                _, rows = self.term.get_size()
                list_height = max(1, rows - 10)

                if key == KEY_ESC:
                    return None

                if key == KEY_DOWN or (self.focus == "list" and key == "j"):
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

                if key == KEY_UP or (self.focus == "list" and key == "k"):
                    if self.focus == "list" and self.cursor_pos > 0:
                        self.cursor_pos -= 1
                        self._adjust_scroll(list_height)
                    continue

                if self.focus == "input":
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
                    elif key == "\x15":
                        self.query = ""
                    elif not key.startswith("KEY_") and (ord(key[0]) >= 32 or ord(key[0]) > 127):
                        self.query += key
                else:
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
                    elif key == KEY_TAB:
                        self.focus = "input"
                    elif key == KEY_ENTER:
                        if self.results and 0 <= self.cursor_pos < len(self.results):
                            chosen = self.results[self.cursor_pos]
                            book = self._download_and_open(chosen)
                            if book:
                                return book
                    elif key == "a":
                        if self.results and 0 <= self.cursor_pos < len(self.results):
                            target = self.results[self.cursor_pos]
                            book = self._find_or_build_book(target)
                            self.storage.add_to_shelf(book)
                            self.show_toast(f"《{book.title}》已加入书架 ★")
        finally:
            self.term.hide_cursor()
