from __future__ import annotations
import time
from typing import List, Optional, Tuple

from ..models import Book, Chapter, SourceBook
from ..sources import SourceManager
from ..storage import StorageManager
from ..text_engine import str_visual_width, truncate_to_width, pad_to_width
from .terminal import (
    TerminalApp,
    RESET, BOLD, INVERSE,
    FG_GREEN, FG_CYAN, FG_YELLOW, FG_WHITE, FG_GRAY, FG_RED,
    BG_BLUE,
    KEY_UP, KEY_DOWN, KEY_PGUP, KEY_PGDN, KEY_HOME, KEY_END,
    KEY_ENTER, KEY_ESC, KEY_BACKSPACE,
)


class DownloadView:
    """首次下载引导与换源选择视图（基于 so-novel 书源聚合检索）"""

    def __init__(
        self,
        term: TerminalApp,
        source_manager: SourceManager,
        storage: StorageManager,
        book: Book,
        is_switch_source: bool = False,
    ):
        self.term = term
        self.source_manager = source_manager
        self.storage = storage
        self.book = book
        self.is_switch_source = is_switch_source

        self.query: str = book.title
        self.results: List[SourceBook] = []
        self.cursor_pos: int = 0
        self.top_offset: int = 0

        self.editing_query: bool = False
        self.status_msg: str = ""
        self.error_msg: str = ""
        self.is_busy: bool = False
        self._last_render_state = None

    def _adjust_scroll(self, list_height: int) -> None:
        if not self.results:
            self.cursor_pos = 0
            self.top_offset = 0
            return
        self.cursor_pos = max(0, min(self.cursor_pos, len(self.results) - 1))
        if self.cursor_pos < self.top_offset:
            self.top_offset = self.cursor_pos
        elif self.cursor_pos >= self.top_offset + list_height:
            self.top_offset = self.cursor_pos - list_height + 1

    def _search_sources(self) -> None:
        if not self.query.strip():
            return
        self.is_busy = True
        self.error_msg = ""
        self.status_msg = f"正在全网书源搜索《{self.query}》..."
        self.render()

        def _on_progress(done: int, total: int, source_name: str) -> None:
            self.status_msg = f"正在检索书源 ({done}/{total}): {source_name}..."
            self.render()

        try:
            self.results = self.source_manager.search_all(
                self.query.strip(),
                target_title=self.book.title,
                target_author=self.book.author,
                on_progress=_on_progress,
            )
            self.cursor_pos = 0
            self.top_offset = 0
            if not self.results:
                self.error_msg = f"未在可用书源中找到《{self.query}》，可按 [/] 修改关键词重试。"
            else:
                self.status_msg = f"共找到 {len(self.results)} 个书源结果（已按同名同作者优先排序）"
        except Exception as e:
            self.results = []
            self.error_msg = f"搜索书源失败: {e}"
        finally:
            self.is_busy = False

    def _download_selected(self) -> Tuple[Optional[Tuple[Book, List[Chapter]]], bool]:
        """Download selected source. Returns (result_or_none, backgrounded)."""
        if not (0 <= self.cursor_pos < len(self.results)):
            return None, False
        chosen = self.results[self.cursor_pos]
        self.storage.add_to_shelf(self.book)
        task = self.source_manager.start_download(chosen, self.storage, self.book)

        self.is_busy = True
        self.error_msg = ""
        try:
            while not task.done_event.wait(0.1):
                if task.status == "fetching_toc":
                    self.status_msg = f"正在从 [{chosen.source_name}] 获取目录... (按 Esc/q 转后台静默下载)"
                else:
                    fail_note = f" (失败 {task.failed})" if task.failed else ""
                    self.status_msg = (
                        f"下载分章 [{chosen.source_name}] {task.done}/{task.total} ({task.percent}%){fail_note}"
                        f" · {task.current_chapter} [Esc转后台]"
                    )
                self.render()
                key = self.term.read_key(0.05)
                if key in ("q", KEY_ESC):
                    return None, True

            if task.status == "done":
                return (self.book, task.chapters), False
            if task.status == "error":
                self.error_msg = f"下载失败 [{chosen.source_name}]: {task.error}"
            return None, False
        finally:
            self.is_busy = False

    def render(self) -> None:
        cols, rows = self.term.get_size()
        cols, rows = max(1, cols), max(1, rows)
        safe_width = max(1, cols - 1)
        list_height = max(1, rows - 5)

        render_state = (
            cols,
            rows,
            self.query,
            self.editing_query,
            self.cursor_pos,
            self.top_offset,
            self.status_msg,
            self.error_msg,
            self.is_busy,
            id(self.results),
            len(self.results),
        )
        if self._last_render_state == render_state:
            return

        buffer = ["\033[H"]

        # 1. 顶部栏
        mode_label = "换源下载" if self.is_switch_source else "首次下载引导"
        author_label = f" · {self.book.author}" if self.book.author else ""
        cur_src = f"当前源: {self.book.source_name} " if self.book.source_name else "本地未下载 "
        top_title = f" ⬇ {mode_label}: 《{self.book.title}》{author_label}"
        gap = max(1, safe_width - str_visual_width(top_title) - str_visual_width(cur_src))
        header = top_title + (" " * gap) + cur_src
        buffer.append(f"\033[K{INVERSE}{BOLD}{pad_to_width(truncate_to_width(header, safe_width), safe_width)}{RESET}\n")

        # 2. 搜索词 / 状态栏
        if self.editing_query:
            prompt = " 修改搜索词: "
            hint = "[Enter重搜 | Esc取消]"
            avail_q = max(4, safe_width - str_visual_width(prompt) - str_visual_width(hint) - 1)
            q_disp = truncate_to_width(self.query, avail_q)
            q_gap = max(1, safe_width - str_visual_width(prompt) - str_visual_width(q_disp) - str_visual_width(hint))
            line2 = f"{prompt}{FG_YELLOW}{BOLD}{q_disp}{RESET}{' ' * q_gap}{FG_GRAY}{hint}{RESET}"
            buffer.append(f"\033[K{line2}\n")
        else:
            status_txt = truncate_to_width(self.status_msg or "请选择书源并按 Enter 下载", max(1, safe_width - 1))
            buffer.append(f"\033[K {FG_CYAN}{status_txt}{RESET}\n")
        buffer.append(f"\033[K{FG_GRAY}{'─' * safe_width}{RESET}\n")

        # 3. 书源列表
        if self.error_msg:
            pad_y = max(0, list_height // 2)
            for _ in range(pad_y):
                buffer.append("\033[K\n")
            buffer.append(f"\033[K  {FG_RED}{truncate_to_width(self.error_msg, max(1, safe_width - 4))}{RESET}\n")
            for _ in range(max(0, list_height - pad_y - 1)):
                buffer.append("\033[K\n")
        else:
            visible = self.results[self.top_offset : self.top_offset + list_height]
            for v_idx in range(list_height):
                if v_idx < len(visible):
                    real_idx = self.top_offset + v_idx
                    sb = visible[v_idx]
                    is_selected = (real_idx == self.cursor_pos)

                    if sb.match_score >= 200:
                        badge = "[同名同作者]"
                    elif sb.match_score >= 120:
                        badge = "[同名]"
                    else:
                        badge = "[相似]"

                    src_tag = f"[{sb.source_name}]"
                    author_tag = f"({sb.author})" if sb.author else ""
                    latest_tag = f" · {sb.latest_chapter}" if sb.latest_chapter else ""
                    line_txt = f" {real_idx + 1:2d}. {badge} {src_tag} 《{sb.title}》{author_tag}{latest_tag}"
                    line_txt = pad_to_width(truncate_to_width(line_txt, safe_width), safe_width)

                    if is_selected:
                        buffer.append(f"\033[K{BG_BLUE}{FG_WHITE}{BOLD}{line_txt}{RESET}\n")
                    elif sb.match_score >= 200:
                        buffer.append(f"\033[K{FG_GREEN}{line_txt}{RESET}\n")
                    else:
                        buffer.append(f"\033[K{line_txt}\n")
                else:
                    buffer.append("\033[K\n")

        # 4. 底部操作栏
        buffer.append(f"\033[K{FG_GRAY}{'─' * safe_width}{RESET}\n")
        if self.editing_query:
            b_left = " [Enter]重新搜索  [Esc]取消编辑"
        else:
            b_left = " [Enter]下载分章  [↑/↓]选源  [/]改词  [r]刷新"
        b_right = " [Esc/q]返回 "
        if str_visual_width(b_left) + str_visual_width(b_right) + 1 > safe_width:
            b_right = ""
        b_gap = max(0, safe_width - str_visual_width(b_left) - str_visual_width(b_right))
        footer = b_left + (" " * b_gap) + b_right
        buffer.append(f"\033[K{INVERSE}{pad_to_width(truncate_to_width(footer, safe_width), safe_width)}{RESET}\033[J")

        self.term.write("".join(buffer))
        if self.editing_query:
            cur_col = min(safe_width, 1 + str_visual_width(" 修改搜索词: ") + str_visual_width(self.query))
            self.term.move_cursor(cur_col, 2)
            self.term.show_cursor()
        else:
            self.term.hide_cursor()
        self.term.flush()
        self._last_render_state = render_state

    def run(self) -> Optional[Tuple[Book, List[Chapter]]]:
        """运行下载引导流程，下载成功返回 (Book, Chapters)，取消返回 None"""
        try:
            self._search_sources()
            while True:
                self.render()
                key = self.term.read_key(2.0, text_input=self.editing_query)
                if not key:
                    continue

                _, rows = self.term.get_size()
                list_height = max(1, rows - 5)

                if self.editing_query:
                    if key == KEY_ESC:
                        self.editing_query = False
                    elif key == KEY_ENTER:
                        self.editing_query = False
                        self._search_sources()
                    elif key == KEY_BACKSPACE:
                        self.query = self.query[:-1]
                    elif key == "\x15":
                        self.query = ""
                    elif not key.startswith("KEY_") and (ord(key[0]) >= 32 or ord(key[0]) > 127):
                        self.query += key
                    continue

                if key in ("q", KEY_ESC):
                    return None
                elif key in (KEY_UP, "k"):
                    if self.cursor_pos > 0:
                        self.cursor_pos -= 1
                        self._adjust_scroll(list_height)
                elif key in (KEY_DOWN, "j"):
                    if self.results and self.cursor_pos < len(self.results) - 1:
                        self.cursor_pos += 1
                        self._adjust_scroll(list_height)
                elif key == KEY_PGUP:
                    self.cursor_pos = max(0, self.cursor_pos - list_height)
                    self._adjust_scroll(list_height)
                elif key == KEY_PGDN:
                    if self.results:
                        self.cursor_pos = min(len(self.results) - 1, self.cursor_pos + list_height)
                        self._adjust_scroll(list_height)
                elif key == KEY_HOME:
                    self.cursor_pos = 0
                    self._adjust_scroll(list_height)
                elif key == KEY_END:
                    if self.results:
                        self.cursor_pos = max(0, len(self.results) - 1)
                        self._adjust_scroll(list_height)
                elif key == "/":
                    self.editing_query = True
                elif key == "r":
                    self._search_sources()
                elif key == KEY_ENTER:
                    res, backgrounded = self._download_selected()
                    if res is not None:
                        return res
                    if backgrounded:
                        return None
        finally:
            self.term.hide_cursor()
