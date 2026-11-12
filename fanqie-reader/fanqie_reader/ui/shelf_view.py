from __future__ import annotations
import time
from datetime import datetime
from typing import List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..models import ShelfItem, Book, Chapter
from ..storage import StorageManager
from ..api import FanqieAPI
from ..auth import AuthManager
from ..text_engine import str_visual_width, truncate_to_width, pad_to_width
from .terminal import (
    TerminalApp,
    RESET, BOLD, DIM, INVERSE,
    FG_GREEN, FG_CYAN, FG_YELLOW, FG_WHITE, FG_GRAY, FG_RED, FG_MAGENTA,
    BG_BLUE, BG_DARK_GRAY,
    KEY_UP, KEY_DOWN, KEY_PGUP, KEY_PGDN, KEY_HOME, KEY_END,
    KEY_ENTER, KEY_ESC, KEY_BACKSPACE, KEY_TAB
)
from .reader_view import ReaderView
from .search_view import SearchView
from .toc_view import TOCView
from .login_view import LoginView

# This shelf entry is the audiobook feed for the text edition already in the cloud shelf.
TEXT_EDITION_OVERRIDES = {
    "7237435769856494652": "7005106440989838336",
}

def format_relative_time(timestamp: float) -> str:
    """人性化相对时间展示"""
    now = time.time()
    diff = now - timestamp
    if diff < 60:
        return "刚刚"
    elif diff < 3600:
        return f"{int(diff // 60)}分钟前"
    elif diff < 86400:
        return f"{int(diff // 3600)}小时前"
    elif diff < 86400 * 3:
        return f"{int(diff // 86400)}天前"
    else:
        dt = datetime.fromtimestamp(timestamp)
        return dt.strftime("%m-%d %H:%M")

class ShelfView:
    """本地个人书架控制台视图"""

    def __init__(self, term: TerminalApp, api: FanqieAPI, storage: StorageManager, auth: Optional[AuthManager] = None):
        self.term = term
        self.api = api
        self.storage = storage
        self.auth = auth or AuthManager()

        self.shelf_items: List[ShelfItem] = []
        self.cursor_pos: int = 0
        self.top_offset: int = 0

        self.filter_mode: bool = False
        self.filter_query: str = ""

        self.toast_msg: str = ""
        self.toast_time: float = 0.0
        self.confirm_delete_id: Optional[str] = None

        self.reload_shelf()

    def reload_shelf(self) -> None:
        self.shelf_items = self.storage.load_shelf()
        display_items = self._get_display_items()
        self.cursor_pos = min(self.cursor_pos, max(0, len(display_items) - 1))

    def _get_display_items(self) -> List[ShelfItem]:
        visible_items = [
            item for item in self.shelf_items
            if item.book.media_genre != 4 and item.book.book_id not in TEXT_EDITION_OVERRIDES
        ]
        if self.filter_mode and self.filter_query.strip():
            q = self.filter_query.strip().lower()
            return [it for it in visible_items if q in it.book.title.lower() or q in (it.book.author or "").lower()]
        return visible_items

    def show_toast(self, msg: str, duration: float = 2.5) -> None:
        self.toast_msg = msg
        self.toast_time = time.time() + duration

    def _adjust_scroll(self, list_height: int) -> None:
        display_items = self._get_display_items()
        if not display_items:
            self.cursor_pos = 0
            self.top_offset = 0
            return
        self.cursor_pos = max(0, min(self.cursor_pos, len(display_items) - 1))
        if self.cursor_pos < self.top_offset:
            self.top_offset = self.cursor_pos
        elif self.cursor_pos >= self.top_offset + list_height:
            self.top_offset = self.cursor_pos - list_height + 1

    def render(self) -> None:
        cols, rows = self.term.get_size()
        display_items = self._get_display_items()

        # 计算可用高度
        header_lines = 3 if self.filter_mode else 1
        list_height = max(1, rows - 2 - header_lines)

        buffer = []
        buffer.append("\033[H")

        # 1. 顶部标题栏
        auth_status = f"● {self.auth.get_display_name()}" if self.auth.is_logged_in() else "○ 未登录"
        top_title = f" 📚 番茄小说 · 书架 [{auth_status}]"
        top_meta = f"已藏 {len(self.shelf_items)} 本 "
        gap = max(1, cols - str_visual_width(top_title) - str_visual_width(top_meta))
        header = top_title + (" " * gap) + top_meta
        buffer.append(f"{INVERSE}{BOLD}{truncate_to_width(header, cols)}{RESET}\n")

        # 2. 如果处于过滤模式，显示过滤条
        if self.filter_mode:
            f_prefix = " 🔍 过滤书架: "
            f_p_w = str_visual_width(f_prefix)
            f_hint = f"匹配 {len(display_items)} 本 [回车阅读 | ↑/↓挑选 | ESC退出]"
            f_h_w = str_visual_width(f_hint)
            f_gap = max(1, cols - f_p_w - str_visual_width(self.filter_query) - f_h_w)
            f_line = f_prefix + f"{FG_YELLOW}{BOLD}{self.filter_query}{RESET}" + (" " * f_gap) + f"{FG_GRAY}{f_hint}{RESET}"
            buffer.append(f"\033[K{truncate_to_width(f_line, cols)}\n")
            buffer.append(f"\033[K{FG_GRAY}{'─' * cols}{RESET}\n")

        # 3. 书架内容列表
        if not display_items:
            pad_y = max(1, list_height // 2 - 2)
            for _ in range(pad_y):
                buffer.append("\033[K\n")
            
            if self.filter_mode and self.filter_query:
                guide_lines = [
                    f"{FG_YELLOW}未在书架中找到匹配《{self.filter_query}》的书籍{RESET}",
                    "",
                    f"按 {FG_GREEN}[Backspace]{RESET} 修改过滤词，或按 {FG_GRAY}[ESC]{RESET} 退出过滤模式。"
                ]
            else:
                guide_lines = [
                    f"{FG_YELLOW}你的书架还是空的！{RESET}",
                    "",
                    f"按 {FG_GREEN}[s]{RESET} 搜全网，或按 {FG_CYAN}[S]{RESET} 一键同步手机端书架！",
                    f"按 {FG_GRAY}[q]{RESET} 退出程序。"
                ]
            for gline in guide_lines:
                pad_x = max(0, (cols - str_visual_width(gline)) // 2)
                buffer.append(f"\033[K" + " " * pad_x + gline + "\n")
            
            for _ in range(max(0, list_height - pad_y - len(guide_lines))):
                buffer.append("\033[K\n")
        else:
            visible_items = display_items[self.top_offset : self.top_offset + list_height]
            for v_idx in range(list_height):
                if v_idx < len(visible_items):
                    real_idx = self.top_offset + v_idx
                    item = visible_items[v_idx]
                    is_selected = (real_idx == self.cursor_pos)

                    # 格式化各列
                    idx_str = f" {real_idx + 1:2d}. "
                    title_str = f"《{item.book.title}》"
                    author_str = f" {item.book.author}" if item.book.author else ""
                    
                    cur_ch_str = item.last_chapter_title or f"第 {item.last_chapter_index + 1} 章"
                    pct_str = f"{item.progress_percent():.1f}%"
                    total_str = f"共{item.book.chapter_total}章" if item.book.chapter_total else ""
                    
                    progress_info = f"[{cur_ch_str} | {pct_str} {total_str}]"
                    time_info = format_relative_time(item.last_read_time) + " "

                    left_col = idx_str + title_str + author_str
                    right_col = f"{progress_info}  {time_info}"

                    l_w = str_visual_width(left_col)
                    r_w = str_visual_width(right_col)
                    line_gap = max(1, cols - l_w - r_w)
                    full_line = left_col + (" " * line_gap) + right_col
                    full_line = truncate_to_width(full_line, cols)
                    full_line = pad_to_width(full_line, cols)

                    if is_selected:
                        buffer.append(f"\033[K{BG_BLUE}{FG_WHITE}{BOLD}{full_line}{RESET}\n")
                    else:
                        buffer.append(f"\033[K{full_line}\n")
                else:
                    buffer.append("\033[K\n")

        # 4. 底部状态与操作指引
        if self.confirm_delete_id:
            del_item = self.storage.get_shelf_item(self.confirm_delete_id)
            book_name = del_item.book.title if del_item else ""
            warn_text = f" ⚠ 确认将《{book_name}》从书架移除？(按 y 确认，其他键取消)"
            warn_line = f"{BG_DARK_GRAY}{FG_YELLOW}{BOLD}{warn_text}{RESET}"
            buffer.append(warn_line + (" " * max(0, cols - str_visual_width(warn_text))))
        elif self.toast_msg and time.time() < self.toast_time:
            t_line = f" {FG_GREEN}✔ {self.toast_msg}{RESET}"
            t_line += " " * max(0, cols - str_visual_width(f" ✔ {self.toast_msg}"))
            buffer.append(f"{INVERSE}{t_line}{RESET}")
        else:
            if self.filter_mode:
                b_left = " [Enter]阅读选中书籍  [↑/↓]挑选匹配项  [ESC]退出过滤模式"
                b_right = " 模式: 书架快速过滤 "
            else:
                b_left = " [Enter]阅读  [/]过滤书架  [s]搜书  [S]同步手机  [L]登录  [t]目录  [d]移除  [r]刷新"
                b_right = " [q]退出 "
            b_gap = max(1, cols - str_visual_width(b_left) - str_visual_width(b_right))
            footer = b_left + (" " * b_gap) + b_right
            buffer.append(f"{INVERSE}{truncate_to_width(footer, cols)}{RESET}")

        self.term.write("".join(buffer))
        if self.filter_mode:
            # 物理光标定位到过滤输入文字末尾，使输入法候选框准确弹出
            f_p_w = str_visual_width(" 🔍 过滤书架: ")
            cur_col = min(cols, 1 + f_p_w + str_visual_width(self.filter_query))
            self.term.move_cursor(cur_col, 2)
            self.term.show_cursor()
        else:
            self.term.hide_cursor()
        self.term.flush()

    def sync_mobile(self) -> None:
        """从手机端/云端同步官方书架和最新阅读位置（多线程并发极速拉取）"""
        if not self.auth.is_logged_in():
            self.show_toast("未登录账号，请先按 [L] 扫码登录手机账号")
            return
        
        self.show_toast("正在连接番茄官方云端书架...")
        self.render()
        try:
            cookie_header = self.auth.get_cookie_header()
            cloud_books = self.api.get_cloud_bookshelf(cookie_header)
            cloud_progress = self.api.get_cloud_progress(cookie_header)
            self.storage.apply_cloud_shelf_order(cloud_books)

            pos_map = {str(p.get("book_id")): p for p in cloud_progress if p.get("book_id")}

            # 筛选本地尚未收录的书籍 ID
            existing_ids = {it.book.book_id for it in self.shelf_items}
            cloud_ids = list(dict.fromkeys(
                str(r.get("book_id", "")) for r in cloud_books
                if str(r.get("book_id", ""))
            ))
            cloud_times = {}
            for row in cloud_books:
                book_id = str(row.get("book_id", ""))
                if book_id:
                    cloud_times[book_id] = max(cloud_times.get(book_id, 0.0), float(row.get("last_operate_time", 0) or 0))
            to_fetch_ids = [book_id for book_id in cloud_ids if book_id not in existing_ids]

            new_books = 0
            total_to_fetch = len(to_fetch_ids)

            if total_to_fetch > 0:
                completed_count = 0
                with ThreadPoolExecutor(max_workers=8) as executor:
                    future_to_id = {executor.submit(self.api.get_book_info, bid): bid for bid in to_fetch_ids}
                    for future in as_completed(future_to_id):
                        completed_count += 1
                        try:
                            book = future.result()
                            self.storage.add_to_shelf(book, added_at=cloud_times.get(book.book_id))
                            new_books += 1
                        except Exception:
                            pass
                        # 动态实时进度更新
                        if completed_count % 3 == 0 or completed_count == total_to_fetch:
                            self.toast_msg = f"正在同步云端书架 ({completed_count}/{total_to_fetch})..."
                            self.toast_time = time.time() + 5.0
                            self.render()

            # 同步阅读进度
            updated_pos = 0
            for b_id, p_info in pos_map.items():
                shelf_item = self.storage.get_shelf_item(b_id)
                if not shelf_item:
                    continue
                c_item_id = str(p_info.get("item_id", ""))
                c_index = int(p_info.get("index", 0) or 0)
                c_time = float(p_info.get("read_timestamp", 0))

                chapters = self.storage.get_chapters_meta(b_id)
                if chapters and c_item_id:
                    matched_index = next((i for i, chapter in enumerate(chapters) if chapter.item_id == c_item_id), None)
                    if matched_index is not None:
                        c_index = matched_index
                if c_item_id:
                    ch_title = f"第 {c_index + 1} 章"
                    if chapters and 0 <= c_index < len(chapters):
                        ch_title = chapters[c_index].title

                    self.storage.update_cloud_progress(b_id, c_index, c_item_id, ch_title, c_time)
                    updated_pos += 1

            self.reload_shelf()
            self.show_toast(f"同步成功！新增 {new_books} 本书，对齐 {updated_pos} 本手机进度 ★", duration=4.0)
            self.render()
        except Exception as e:
            self.show_toast(f"同步失败: {e}", duration=4.0)
            self.render()

    def _open_book_reader(self, item: ShelfItem) -> None:
        """加载书籍并打开阅读器进行断点续读"""
        text_book_id = TEXT_EDITION_OVERRIDES.get(item.book.book_id)
        if text_book_id:
            text_item = self.storage.get_shelf_item(text_book_id)
            if text_item:
                item = text_item

        self.term.clear()
        cols, rows = self.term.get_size()
        msg = f"正在加载《{item.book.title}》目录及章节数据..."
        pad_x = max(0, (cols - str_visual_width(msg)) // 2)
        pad_y = max(1, rows // 2)
        self.term.move_cursor(pad_x + 1, pad_y + 1)
        self.term.write(f"{FG_YELLOW}{BOLD}{msg}{RESET}")
        self.term.flush()

        # 优先读取缓存的目录元数据
        chapters = self.storage.get_chapters_meta(item.book.book_id)
        if not chapters:
            try:
                book, chapters = self.api.get_book_detail(item.book.book_id)
                item.book = book
                self.storage.save_chapters_meta(book.book_id, chapters)
            except Exception as e:
                self.show_toast(f"获取书籍信息失败: {e}")
                return

        if self.auth.is_logged_in():
            try:
                cloud_progress = self.api.get_cloud_progress(self.auth.get_cookie_header())
                progress = next((
                    row for row in cloud_progress
                    if str(row.get("book_id", "")) == item.book.book_id and row.get("item_id")
                ), None)
                if progress:
                    chapter_id = str(progress["item_id"])
                    chapter_index = next((
                        idx for idx, chapter in enumerate(chapters)
                        if chapter.item_id == chapter_id
                    ), int(progress.get("index", 0) or 0))
                    chapter_title = chapters[chapter_index].title if 0 <= chapter_index < len(chapters) else ""
                    self.storage.update_cloud_progress(
                        item.book.book_id,
                        chapter_index,
                        chapter_id,
                        chapter_title,
                        float(progress.get("read_timestamp", 0) or 0),
                    )
                    item = self.storage.get_shelf_item(item.book.book_id) or item
            except Exception:
                pass

        reader = ReaderView(
            term=self.term,
            api=self.api,
            storage=self.storage,
            book=item.book,
            chapters=chapters,
            initial_chapter_index=item.last_chapter_index,
            initial_line_offset=item.line_offset
        )
        reader.run()
        self.reload_shelf()

    def run(self) -> None:
        """书架主循环"""
        try:
            while True:
                self.render()
                key = self.term.read_key(0.5, text_input=self.filter_mode)
                if not key:
                    continue

                cols, rows = self.term.get_size()
                header_lines = 3 if self.filter_mode else 1
                list_height = max(1, rows - 2 - header_lines)
                display_items = self._get_display_items()

                # 正在处于删除确认态
                if self.confirm_delete_id:
                    if key in ('y', 'Y'):
                        self.storage.remove_from_shelf(self.confirm_delete_id)
                        self.show_toast("已移出书架")
                        self.reload_shelf()
                    self.confirm_delete_id = None
                    continue

                # ── 无论哪种模式，物理上下键 100% 可用 ──
                if key == KEY_UP:
                    if self.cursor_pos > 0:
                        self.cursor_pos -= 1
                        self._adjust_scroll(list_height)
                    continue

                elif key == KEY_DOWN:
                    if display_items and self.cursor_pos < len(display_items) - 1:
                        self.cursor_pos += 1
                        self._adjust_scroll(list_height)
                    continue

                elif key == KEY_PGUP:
                    self.cursor_pos = max(0, self.cursor_pos - list_height)
                    self._adjust_scroll(list_height)
                    continue

                elif key == KEY_PGDN:
                    if display_items:
                        self.cursor_pos = min(len(display_items) - 1, self.cursor_pos + list_height)
                        self._adjust_scroll(list_height)
                    continue

                elif key == KEY_HOME:
                    self.cursor_pos = 0
                    self._adjust_scroll(list_height)
                    continue

                elif key == KEY_END:
                    if display_items:
                        self.cursor_pos = max(0, len(display_items) - 1)
                        self._adjust_scroll(list_height)
                    continue

                # ── 处于书架快速过滤模式 ──
                if self.filter_mode:
                    if key == KEY_ESC:
                        # ESC 退出过滤模式
                        self.filter_mode = False
                        self.filter_query = ""
                        self.cursor_pos = 0
                        self.top_offset = 0

                    elif key == KEY_ENTER:
                        # 选定当前过滤命中的书籍开始阅读
                        if display_items and 0 <= self.cursor_pos < len(display_items):
                            chosen = display_items[self.cursor_pos]
                            self._open_book_reader(chosen)

                    elif key == KEY_BACKSPACE:
                        if self.filter_query:
                            self.filter_query = self.filter_query[:-1]
                            self.cursor_pos = 0
                            self.top_offset = 0
                        else:
                            # 已经删空，再按退格退出过滤模式
                            self.filter_mode = False

                    elif key == '\x15':  # Ctrl+U 清空过滤词
                        self.filter_query = ""
                        self.cursor_pos = 0
                        self.top_offset = 0

                    elif not key.startswith("KEY_") and (ord(key[0]) >= 32 or ord(key[0]) > 127):
                        # 输入过滤文字（包括拼音和中文字符串），排除控制键
                        self.filter_query += key
                        self.cursor_pos = 0
                        self.top_offset = 0

                # ── 普通主书架模式 ──
                else:
                    # 只有在非过滤状态下按 'q' 才是退出程序，ESC 绝对不退出，绝不闪退！
                    if key == 'q':
                        break

                    elif key == KEY_ESC:
                        # 忽略未绑定操作的 ESC，防止误触闪退
                        pass

                    # Vim 键位上下选择
                    elif key == 'k':
                        if self.cursor_pos > 0:
                            self.cursor_pos -= 1
                            self._adjust_scroll(list_height)

                    elif key == 'j':
                        if self.cursor_pos < len(display_items) - 1:
                            self.cursor_pos += 1
                            self._adjust_scroll(list_height)

                    # 按 / 键：进入书架快速过滤模式
                    elif key == '/':
                        self.filter_mode = True
                        self.filter_query = ""
                        self.cursor_pos = 0
                        self.top_offset = 0

                    # 回车：进入断点续读
                    elif key == KEY_ENTER:
                        if display_items and 0 <= self.cursor_pos < len(display_items):
                            chosen = display_items[self.cursor_pos]
                            self._open_book_reader(chosen)

                    # 按 s：在线搜索
                    elif key == 's':
                        search = SearchView(self.term, self.api, self.storage)
                        new_book = search.run()
                        self.reload_shelf()
                        if new_book:
                            shelf_item = self.storage.get_shelf_item(new_book.book_id)
                            if shelf_item:
                                self._open_book_reader(shelf_item)

                    # 按 L：官方账号扫码/Cookie登录
                    elif key in ('l', 'L'):
                        login_v = LoginView(self.term, self.auth)
                        changed = login_v.run()
                        if changed and self.auth.is_logged_in():
                            self.show_toast(f"登录成功: {self.auth.get_display_name()}，正在同步手机...")
                            self.sync_mobile()

                    # 按 S：一键同步手机端书架与进度
                    elif key == 'S':
                        self.sync_mobile()

                    # 按 d：移出书架
                    elif key == 'd':
                        if display_items and 0 <= self.cursor_pos < len(display_items):
                            self.confirm_delete_id = display_items[self.cursor_pos].book.book_id

                    # 按 t：查看选中书籍目录并跳转
                    elif key == 't':
                        if display_items and 0 <= self.cursor_pos < len(display_items):
                            item = display_items[self.cursor_pos]
                            chapters = self.storage.get_chapters_meta(item.book.book_id)
                            if not chapters:
                                try:
                                    book, chapters = self.api.get_book_detail(item.book.book_id)
                                    item.book = book
                                    self.storage.save_chapters_meta(book.book_id, chapters)
                                except Exception as e:
                                    self.show_toast(f"获取目录失败: {e}")
                                    continue
                            
                            toc = TOCView(self.term, chapters, item.last_chapter_index)
                            chosen_idx = toc.run()
                            if chosen_idx is not None:
                                item.last_chapter_index = chosen_idx
                                item.line_offset = 0
                                self._open_book_reader(item)

                    # 按 r：联网刷新选中书籍信息
                    elif key == 'r':
                        if display_items and 0 <= self.cursor_pos < len(display_items):
                            item = display_items[self.cursor_pos]
                            self.show_toast(f"正在刷新《{item.book.title}》最新章节...")
                            self.render()
                            try:
                                book, chapters = self.api.get_book_detail(item.book.book_id)
                                item.book = book
                                self.storage.save_chapters_meta(book.book_id, chapters)
                                self.storage.add_to_shelf(book)
                                self.show_toast(f"刷新成功，当前全书共 {len(chapters)} 章")
                            except Exception as e:
                                self.show_toast(f"刷新失败: {e}")
                            self.reload_shelf()
        finally:
            self.term.hide_cursor()
