from __future__ import annotations
from typing import List, Optional

from ..models import Chapter
from ..text_engine import str_visual_width, truncate_to_width, pad_to_width
from .terminal import (
    TerminalApp,
    RESET, BOLD, DIM, INVERSE,
    FG_GREEN, FG_CYAN, FG_YELLOW, FG_WHITE, FG_GRAY, FG_BLUE,
    BG_BLUE, BG_DARK_GRAY,
    KEY_UP, KEY_DOWN, KEY_PGUP, KEY_PGDN, KEY_HOME, KEY_END,
    KEY_ENTER, KEY_ESC, KEY_BACKSPACE
)

class TOCView:
    """章节目录浏览与快速检索视图"""

    def __init__(self, term: TerminalApp, chapters: List[Chapter], current_index: int = 0):
        self.term = term
        self.chapters = chapters
        self.current_index = current_index

        # 搜索过滤文本
        self.filter_text: str = ""
        self.filter_mode = False
        self.filtered_indices: List[int] = list(range(len(chapters)))

        # 光标选中项在 filtered_indices 中的位置
        self.cursor_pos: int = 0
        if current_index in self.filtered_indices:
            self.cursor_pos = self.filtered_indices.index(current_index)
        
        self.top_offset: int = 0

    def _update_filter(self) -> None:
        if not self.filter_text.strip():
            self.filtered_indices = list(range(len(self.chapters)))
        else:
            q = self.filter_text.lower().strip()
            self.filtered_indices = [
                i for i, ch in enumerate(self.chapters)
                if q in ch.title.lower() or q in ch.volume_name.lower() or q in str(i + 1)
            ]
        self.cursor_pos = min(self.cursor_pos, max(0, len(self.filtered_indices) - 1))
        self._adjust_scroll()

    def _adjust_scroll(self) -> None:
        _, rows = self.term.get_size()
        list_height = max(1, rows - 4)  # 顶部标题+搜索框2行，底部提示1行，预留空间

        if self.cursor_pos < self.top_offset:
            self.top_offset = self.cursor_pos
        elif self.cursor_pos >= self.top_offset + list_height:
            self.top_offset = self.cursor_pos - list_height + 1

    def render(self) -> None:
        cols, rows = self.term.get_size()
        list_height = max(1, rows - 4)

        buffer = []
        buffer.append("\033[H")

        # 1. 顶部标题栏
        top_title = " 📑 章节目录导航"
        top_meta = f"共 {len(self.chapters)} 章 (当前: 第 {self.current_index + 1} 章) "
        t_gap = max(1, cols - str_visual_width(top_title) - str_visual_width(top_meta))
        header = top_title + (" " * t_gap) + top_meta
        if str_visual_width(header) > cols:
            header = header[:cols]
        buffer.append(f"{INVERSE}{BOLD}{header}{RESET}\n")

        # 2. 搜索框
        search_prompt = " 🔍 过滤/跳转: "
        disp_filter = self.filter_text + "█"
        match_info = f"匹配 {len(self.filtered_indices)} 章 "
        s_gap = max(1, cols - str_visual_width(search_prompt) - str_visual_width(self.filter_text) - 1 - str_visual_width(match_info))
        search_line = search_prompt + f"{FG_YELLOW}{BOLD}{disp_filter}{RESET}" + (" " * s_gap) + f"{FG_GRAY}{match_info}{RESET}"
        buffer.append(f"\033[K{search_line}\n")
        buffer.append(f"\033[K{FG_GRAY}{'─' * cols}{RESET}\n")

        # 3. 目录列表项
        visible_indices = self.filtered_indices[self.top_offset : self.top_offset + list_height]
        for v_idx in range(list_height):
            if v_idx < len(visible_indices):
                real_idx = visible_indices[v_idx]
                ch = self.chapters[real_idx]
                is_selected = (self.top_offset + v_idx == self.cursor_pos)
                is_current = (real_idx == self.current_index)

                prefix = "▶ " if is_current else "  "
                num_str = f"[{real_idx + 1:4d}] "
                vol_str = f"({ch.volume_name}) " if ch.volume_name else ""
                title_str = ch.title

                line_content = f"{prefix}{num_str}{vol_str}{title_str}"
                # 填充整行宽度
                l_width = str_visual_width(line_content)
                pad_space = " " * max(0, cols - l_width)
                full_line = line_content + pad_space
                full_line = truncate_to_width(full_line, cols)
                full_line = pad_to_width(full_line, cols)

                if is_selected:
                    buffer.append(f"\033[K{BG_BLUE}{FG_WHITE}{BOLD}{full_line}{RESET}\n")
                elif is_current:
                    buffer.append(f"\033[K{FG_GREEN}{BOLD}{full_line}{RESET}\n")
                else:
                    buffer.append(f"\033[K{full_line}\n")
            else:
                buffer.append("\033[K\n")

        # 4. 底部操作指引
        b_left = " [↑/↓]选择  [Enter]跳转阅读  [输入文字/数字]快速过滤"
        b_right = " [Esc]清空/返回 "
        b_gap = max(1, cols - str_visual_width(b_left) - str_visual_width(b_right))
        footer = b_left + (" " * b_gap) + b_right
        if str_visual_width(footer) > cols:
            footer = footer[:cols]
        buffer.append(f"{INVERSE}{footer}{RESET}")

        self.term.write("".join(buffer))
        self.term.flush()

    def run(self) -> Optional[int]:
        """运行目录选择循环，返回目标章节索引或 None"""
        self._update_filter()

        while True:
            self.render()
            key = self.term.read_key(0.5, text_input=self.filter_mode)
            if not key:
                continue

            _, rows = self.term.get_size()
            list_height = max(1, rows - 4)

            # 退出
            if key == KEY_ESC:
                if self.filter_mode:
                    self.filter_text = ""
                    self.filter_mode = False
                    self._update_filter()
                else:
                    return None

            # 确认选择
            elif key == KEY_ENTER:
                if self.filtered_indices:
                    return self.filtered_indices[self.cursor_pos]
                return None

            # 光标上下移动
            elif key == KEY_UP or (key == 'k' and not self.filter_mode):
                if self.cursor_pos > 0:
                    self.cursor_pos -= 1
                    self._adjust_scroll()

            elif key == KEY_DOWN or (key == 'j' and not self.filter_mode):
                if self.cursor_pos < len(self.filtered_indices) - 1:
                    self.cursor_pos += 1
                    self._adjust_scroll()

            # 翻页
            elif key == KEY_PGUP:
                self.cursor_pos = max(0, self.cursor_pos - list_height)
                self._adjust_scroll()

            elif key == KEY_PGDN:
                self.cursor_pos = min(max(0, len(self.filtered_indices) - 1), self.cursor_pos + list_height)
                self._adjust_scroll()

            elif key == KEY_HOME:
                self.cursor_pos = 0
                self._adjust_scroll()

            elif key == KEY_END:
                self.cursor_pos = max(0, len(self.filtered_indices) - 1)
                self._adjust_scroll()

            elif key == '/':
                self.filter_mode = True
                self.filter_text = ""
                self._update_filter()

            # 删除字符
            elif key == KEY_BACKSPACE:
                if self.filter_text:
                    self.filter_text = self.filter_text[:-1]
                    self._update_filter()
                else:
                    self.filter_mode = False

            # 输入普通可打印字符过滤（过滤掉特殊控制字符）
            elif key and not key.startswith("KEY_") and all(ord(char) >= 32 for char in key):
                self.filter_mode = True
                self.filter_text += key
                self._update_filter()
