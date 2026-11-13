from __future__ import annotations
import time
import threading
import webbrowser
from typing import List, Optional, Tuple

from ..models import Book, Chapter
from ..storage import StorageManager
from ..api import FanqieAPI
from ..auth import AuthManager
from ..text_engine import (
    TextLayoutEngine, str_visual_width, truncate_to_width, sanitize_terminal_text,
)
from .terminal import (
    TerminalApp,
    RESET, BOLD, DIM, INVERSE,
    FG_GREEN, FG_CYAN, FG_YELLOW, FG_WHITE, FG_GRAY, FG_MAGENTA, FG_RED,
    BG_BLACK, BG_DARK_GRAY, BG_BLUE, BG_CYAN, BG_YELLOW,
    KEY_UP, KEY_DOWN, KEY_PGUP, KEY_PGDN, KEY_HOME, KEY_END,
    KEY_ENTER, KEY_ESC, KEY_BACKSPACE, FG_BLACK
)
from .toc_view import TOCView

class ReaderView:
    """沉浸式终端小说阅读器核心引擎"""

    WIDTH_PRESETS = [65, 80, 100]

    def __init__(
        self,
        term: TerminalApp,
        api: FanqieAPI,
        storage: StorageManager,
        book: Book,
        chapters: List[Chapter],
        initial_chapter_index: int = 0,
        initial_line_offset: int = 0
    ):
        self.term = term
        self.api = api
        self.storage = storage
        self.auth = AuthManager(storage.base_dir)
        self._cloud_sync_timer: Optional[threading.Timer] = None
        self._cloud_sync_payload = None
        self._cloud_sync_lock = threading.Lock()
        self._cloud_sync_error: Optional[str] = None
        self.book = book
        self.chapters = chapters
        progress_item = storage.get_shelf_item(book.book_id)
        chapter_id_index = next((i for i, chapter in enumerate(chapters) if progress_item and chapter.item_id == progress_item.last_chapter_id), None)
        if chapter_id_index is not None:
            initial_chapter_index = chapter_id_index
        self.chapter_index = max(0, min(initial_chapter_index, len(chapters) - 1)) if chapters else 0
        self.line_offset = max(0, initial_line_offset)

        self.width_idx = 1  # 默认 80 宽
        self.layout_engine = TextLayoutEngine(self.WIDTH_PRESETS[self.width_idx])

        # 当前章节正文排版行
        self.current_title: str = ""
        self.formatted_lines: List[str] = []
        self._layout_source: Optional[Tuple[str, str]] = None
        self._layout_is_error = False
        self._last_frame = None
        self._last_frame_size = None
        self.loading: bool = False
        self.toast_message: str = ""
        self.toast_time: float = 0.0
        self.highlight_line: Optional[int] = None
        self.highlight_until: float = 0.0

        # 后台预加载线程
        self.prefetch_thread: Optional[threading.Thread] = None

    def show_toast(self, msg: str, duration: float = 2.0) -> None:
        self.toast_message = msg
        self.toast_time = time.time() + duration

    def _update_layout(self, cols: int, *, force: bool = False, preserve_position: bool = True) -> None:
        """窗口/列宽改变时重排一次，以正文字符位置保留阅读锚点。"""
        width = min(self.WIDTH_PRESETS[self.width_idx], max(2, cols - 2))
        if not force and width == self.layout_engine.content_width:
            return
        anchor = sum(len(line.strip()) for line in self.formatted_lines[:self.line_offset])
        self.layout_engine.set_content_width(width)
        if self._layout_source is None:
            return
        title, content = self._layout_source
        if self._layout_is_error:
            self.formatted_lines = [
                line for paragraph in content.splitlines()
                for line in self.layout_engine.wrap_paragraph(paragraph)
            ]
        else:
            self.formatted_lines = self.layout_engine.layout_chapter(title, content)
        if preserve_position:
            consumed = 0
            for index, line in enumerate(self.formatted_lines):
                length = len(line.strip())
                if consumed + length > anchor:
                    self.line_offset = index
                    break
                consumed += length
            else:
                self.line_offset = max(0, len(self.formatted_lines) - 1)
        self.highlight_line = None

    def _fetch_chapter_content(self, ch_idx: int) -> Tuple[str, str]:
        """获取章节内容（优先从本地离线缓存读，没有则联网获取并缓存）"""
        if not (0 <= ch_idx < len(self.chapters)):
            return "", ""
        
        target_ch = self.chapters[ch_idx]
        cached = self.storage.get_chapter_cache(self.book.book_id, target_ch.item_id)
        # Older versions cached preview-only responses as if they were complete.
        if cached and len(cached[1]) >= 250:
            return cached

        # 联网请求
        cookie_header = self.auth.get_cookie_header() if self.auth.is_logged_in() else None
        title, content = self.api.get_chapter_content(target_ch.item_id, cookie_header=cookie_header)
        if not title:
            title = target_ch.title
        self.storage.save_chapter_cache(self.book.book_id, target_ch.item_id, title, content)
        return title, content

    def _prefetch_next_chapter(self) -> None:
        """后台异步预加载下一章"""
        next_idx = self.chapter_index + 1
        if 0 <= next_idx < len(self.chapters):
            def _worker():
                try:
                    self._fetch_chapter_content(next_idx)
                except Exception:
                    pass
            self.prefetch_thread = threading.Thread(target=_worker, daemon=True)
            self.prefetch_thread.start()

    def load_current_chapter(self, reset_offset: bool = False, to_end: bool = False) -> None:
        """载入当前章节并进行中文智能折行排版"""
        if not self.chapters:
            self._layout_source = None
            self.formatted_lines = ["当前书籍无可用章节。"]
            return

        self.loading = True
        self.render()
        loaded = False

        try:
            title, content = self._fetch_chapter_content(self.chapter_index)
            self.current_title = title or self.chapters[self.chapter_index].title
            self._layout_source = (self.current_title, content)
            self._layout_is_error = False
            loaded = True
        except Exception as e:
            self.current_title = self.chapters[self.chapter_index].title
            error_lines = [
                "",
                "章节正文未完整加载",
                str(e),
                "按 'o' 在番茄官方网页打开本章，或按 'r' 重试。",
                "也可按 '[' / ']' 切换章节，按 'q' 返回书架。",
                ""
            ]
            self._layout_source = (self.current_title, "\n".join(error_lines))
            self._layout_is_error = True

        cols, term_rows = self.term.get_size()
        self._update_layout(cols, force=True, preserve_position=False)

        self.loading = False

        if reset_offset:
            self.line_offset = 0
        elif to_end:
            content_rows = max(1, term_rows - 2)
            self.line_offset = max(0, len(self.formatted_lines) - content_rows)
        self.line_offset = min(self.line_offset, max(0, len(self.formatted_lines) - max(1, term_rows - 2)))

        if loaded:
            self._prefetch_next_chapter()
            self.save_current_progress()

    def save_current_progress(self) -> None:
        """保存断点续读记录"""
        if not self.chapters or not (0 <= self.chapter_index < len(self.chapters)):
            return
        
        cur_ch = self.chapters[self.chapter_index]
        self.storage.update_progress(
            book_id=self.book.book_id,
            chapter_index=self.chapter_index,
            chapter_id=cur_ch.item_id,
            chapter_title=self.current_title or cur_ch.title,
            line_offset=self.line_offset,
            book=self.book
        )
        if self.auth.is_logged_in():
            total_lines = max(1, len(self.formatted_lines))
            chapter_fraction = min(1.0, max(0.0, self.line_offset / total_lines))
            book_fraction = (
                self.chapter_index + chapter_fraction
            ) / max(1, len(self.chapters))
            self._cloud_sync_payload = {
                "book_id": self.book.book_id,
                "item_id": cur_ch.item_id,
                "read_progress": round(book_fraction * 10000),
                "index": self.chapter_index,
                "read_timestamp": str(int(time.time())),
                "genre_type": 0,
            }
            # 服务端的 read_progress 是整本书的万分比；index 才是章节序号。
            self._cloud_sync_error = None
            if self._cloud_sync_timer:
                self._cloud_sync_timer.cancel()
            self._cloud_sync_timer = threading.Timer(0.35, self._sync_cloud_progress)
            self._cloud_sync_timer.daemon = True
            self._cloud_sync_timer.start()

    def _sync_cloud_progress(self) -> None:
        with self._cloud_sync_lock:
            payload = self._cloud_sync_payload
            if not payload or not self.auth.is_logged_in():
                return
            try:
                self.api.update_cloud_progress(payload, self.auth.get_cookie_header())
                self._cloud_sync_payload = None
                self._cloud_sync_error = None
            except Exception as exc:
                # 保留 payload，退出时的 flush 可以再次尝试；不要让失败静默消失。
                self._cloud_sync_error = str(exc)

    def flush_cloud_progress(self) -> None:
        if self._cloud_sync_timer:
            self._cloud_sync_timer.cancel()
            self._cloud_sync_timer = None
        self._sync_cloud_progress()

    def scroll_half_page(self, direction: int) -> None:
        _, rows = self.term.get_size()
        content_rows = max(1, rows - 2)
        max_offset = max(0, len(self.formatted_lines) - content_rows)
        previous_offset = self.line_offset
        step = max(1, content_rows // 2)
        if direction > 0:
            self.line_offset = min(max_offset, previous_offset + step)
            target_line = min(len(self.formatted_lines) - 1, previous_offset + content_rows)
        else:
            self.line_offset = max(0, previous_offset - step)
            target_line = previous_offset
        if self.line_offset != previous_offset:
            self.highlight_line = target_line
            self.highlight_until = time.monotonic() + 1.2
            self.save_current_progress()

    @staticmethod
    def _compose_bar(left: str, right: str, width: int) -> str:
        left = sanitize_terminal_text(left)
        right = truncate_to_width(sanitize_terminal_text(right), width)
        budget = max(0, width - str_visual_width(right) - 1)
        left = truncate_to_width(left, budget, ellipsis="…")
        return left + " " * max(0, width - str_visual_width(left + right)) + right

    def render(self) -> None:
        """按固定屏幕行绘制，只更新变化的行；不触发终端换行/滚屏。"""
        cols, rows = self.term.get_size()
        cols, rows = max(1, cols), max(1, rows)
        # 留出右边界，避免终端最后一列的自动换行状态。
        safe_width = cols - 1
        content_rows = max(0, rows - 2)
        if not self.loading:
            self._update_layout(cols)
            self.line_offset = min(self.line_offset, max(0, len(self.formatted_lines) - max(1, content_rows)))
        cur_title = self.current_title or (self.chapters[self.chapter_index].title if self.chapters else "")
        vol_info = f"[{self.chapters[self.chapter_index].volume_name}] " if self.chapters and self.chapters[self.chapter_index].volume_name else ""
        top_bar = self._compose_bar(
            f" {self.book.title} ❯ {vol_info}{cur_title}",
            f"宽:{self.layout_engine.content_width}列 ", safe_width,
        )
        frame = [(top_bar, INVERSE + BOLD)]
        if self.highlight_line is not None and time.monotonic() >= self.highlight_until:
            self.highlight_line = None
        for index in range(content_rows):
            line_index = self.line_offset + index
            text, style = "", ""
            if self.loading:
                if index == content_rows // 2:
                    text = truncate_to_width("正在获取正文并解密排版中...", safe_width)
                    text = " " * max(0, (safe_width - str_visual_width(text)) // 2) + text
                    style = FG_YELLOW
            elif line_index < len(self.formatted_lines):
                text = self.layout_engine.pad_line_to_center(self.formatted_lines[line_index], cols)
                if line_index == self.highlight_line:
                    style = BG_YELLOW + FG_BLACK
            frame.append((truncate_to_width(sanitize_terminal_text(text), safe_width), style))

        if rows > 1:
            if self.toast_message and time.time() < self.toast_time:
                bottom_bar = truncate_to_width(sanitize_terminal_text(f" ✔ {self.toast_message}"), safe_width)
                bottom_style = INVERSE + FG_GREEN
            else:
                total_lines = len(self.formatted_lines)
                end = min(total_lines, self.line_offset + content_rows)
                percent = int(end / max(1, total_lines) * 100)
                chapter = f"{self.chapter_index + 1}/{len(self.chapters)}"
                shelf = "★已在书架" if self.storage.is_in_shelf(self.book.book_id) else "☆未加书架"
                left = f" 章节:{chapter} 行:{end}/{total_lines} {percent}% | {shelf}"
                right = f"[t]目录 [w]排版 [a]书架 [?]帮助 [Esc]返回 {time.strftime('%H:%M')} "
                if str_visual_width(left + right) + 1 > safe_width:
                    right = "[?]帮助 [Esc]返回 "
                if safe_width < 48:
                    left, right = f" {chapter} {percent}%", "[?]帮助 "
                bottom_bar = self._compose_bar(left, right, safe_width)
                bottom_style = INVERSE
            frame.append((bottom_bar, bottom_style))

        previous = self._last_frame if self._last_frame_size == (cols, rows) else None
        buffer = []
        for index, (text, style) in enumerate(frame):
            if previous is None or previous[index] != (text, style):
                # 先写内容再清理行尾，避免整行先擦除产生空白闪烁。
                buffer.append(f"\033[{index + 1};1H{RESET}{style}{text}\033[K{RESET}")
        if buffer:
            self.term.write("".join(buffer))
            self.term.flush()
        self._last_frame = frame
        self._last_frame_size = (cols, rows)

    def show_help_modal(self) -> None:
        """显示按键帮助浮层"""
        help_lines = [
            "↓ / ↑ 或 j / k：向下 / 向上滚动 1 行",
            "Space / PgDown：向下翻页",
            "b / PgUp：向上翻页",
            "d / u：向下 / 向上翻半屏",
            "g / Home：本章开头；G / End：本章末尾",
            "h / l：上一章 / 下一章",
            "t：查看并搜索目录",
            "w：切换列宽 (65/80/100)，按窗口自动适配",
            "a：加入 / 移出本地书架",
            "r：重新加载本章；o：官方网页打开本章",
            "q / Esc：退出阅读并保存断点",
        ]
        offset = 0
        previous = None
        while True:
            cols, rows = self.term.get_size()
            cols, rows = max(1, cols), max(1, rows)
            width, height = cols - 1, max(1, rows - 2)
            engine = TextLayoutEngine(max(2, width))
            lines = [line for entry in help_lines for line in engine.wrap_paragraph(entry)]
            offset = min(offset, max(0, len(lines) - height))
            state = (cols, rows, offset)
            if state != previous:
                visible = [" 快捷键帮助"] + lines[offset:offset + max(0, rows - 2)]
                visible += [""] * (max(1, rows - 1) - len(visible))
                if rows > 1:
                    visible.append(" ↑/↓ 翻阅帮助；其他键关闭")
                self.term.write("".join(
                    f"\033[{index + 1};1H{RESET}{BG_BLUE}{FG_WHITE}{truncate_to_width(text, width)}\033[K{RESET}"
                    for index, text in enumerate(visible)
                ))
                self.term.flush()
                previous = state
            key = self.term.read_key(0.1)
            if key in (KEY_DOWN, 'j', KEY_PGDN):
                offset = min(max(0, len(lines) - height), offset + (height if key == KEY_PGDN else 1))
            elif key in (KEY_UP, 'k', KEY_PGUP):
                offset = max(0, offset - (height if key == KEY_PGUP else 1))
            elif key:
                break
        self._last_frame = None
        self.render()

    def run(self) -> None:
        """主阅读事件循环"""
        try:
            self.load_current_chapter(reset_offset=(self.line_offset == 0))

            while True:
                self.render()
                key = self.term.read_key(0.5)
                if not key:
                    continue

                cols, rows = self.term.get_size()
                content_rows = max(1, rows - 2)
                max_offset = max(0, len(self.formatted_lines) - content_rows)

                # 退出阅读
                if key in ('q', KEY_ESC):
                    break

                # 方向键只滚动正文，到边界后保持当前章节。
                elif key in ('j', KEY_DOWN):
                    if self.line_offset < max_offset:
                        self.line_offset += 1
                        self.save_current_progress()

                # 上滚单行
                elif key in ('k', KEY_UP):
                    if self.line_offset > 0:
                        self.line_offset -= 1
                        self.save_current_progress()

                # 向下翻页 (Space / PageDown)
                elif key == 'd':
                    self.scroll_half_page(1)

                # 向上半屏
                elif key == 'u':
                    self.scroll_half_page(-1)

                # 向下翻页 (Space / PageDown)
                elif key in (' ', KEY_PGDN):
                    if self.line_offset < max_offset:
                        # 保留 2 行上下文
                        step = max(1, content_rows - 2)
                        self.line_offset = min(max_offset, self.line_offset + step)
                        self.save_current_progress()

                # 向上翻页 (b / PageUp)
                elif key in ('b', KEY_PGUP):
                    if self.line_offset > 0:
                        step = max(1, content_rows - 2)
                        self.line_offset = max(0, self.line_offset - step)
                        self.save_current_progress()

                # 跳到本章开头
                elif key in ('g', KEY_HOME):
                    self.line_offset = 0
                    self.save_current_progress()

                # 跳到本章结尾
                elif key in ('G', KEY_END):
                    self.line_offset = max_offset
                    self.save_current_progress()

                # h / l 在章节间前后移动，方向键始终只控制正文滚动。
                elif key in ('h', '['):
                    if self.chapter_index > 0:
                        self.chapter_index -= 1
                        self.show_toast(f"切换至: 第 {self.chapter_index + 1} 章")
                        self.load_current_chapter(reset_offset=True)
                    else:
                        self.show_toast("已经是第一章了")

                # 切下一章
                elif key in ('l', ']'):
                    if self.chapter_index < len(self.chapters) - 1:
                        self.chapter_index += 1
                        self.show_toast(f"切换至: 第 {self.chapter_index + 1} 章")
                        self.load_current_chapter(reset_offset=True)
                    else:
                        self.show_toast("已经是最新章节了")

                # 切换宽度
                elif key == 'w':
                    self.width_idx = (self.width_idx + 1) % len(self.WIDTH_PRESETS)
                    self._update_layout(cols)
                    self.show_toast(f"排版列宽: {self.WIDTH_PRESETS[self.width_idx]}，当前窗口使用 {self.layout_engine.content_width} 列")
                    self.line_offset = min(self.line_offset, max(0, len(self.formatted_lines) - content_rows))
                    self.save_current_progress()

                # 加入/移出书架
                elif key == 'a':
                    if self.storage.is_in_shelf(self.book.book_id):
                        self.storage.remove_from_shelf(self.book.book_id)
                        self.show_toast("已从书架移除")
                    else:
                        self.storage.add_to_shelf(self.book)
                        self.save_current_progress()
                        self.show_toast("已成功加入书架 ★")

                # 重新加载
                elif key == 'r':
                    self.show_toast("重新加载当前章...")
                    cur_ch = self.chapters[self.chapter_index]
                    cache_file = self.storage.cache_dir / self.book.book_id / f"{cur_ch.item_id}.txt"
                    if cache_file.exists():
                        cache_file.unlink(missing_ok=True)
                    self.load_current_chapter(reset_offset=False)

                # 在官方网页阅读当前章节
                elif key == 'o':
                    if 0 <= self.chapter_index < len(self.chapters):
                        item_id = self.chapters[self.chapter_index].item_id
                        try:
                            opened = webbrowser.open(f"https://fanqienovel.com/reader/{item_id}")
                            self.show_toast("已在浏览器打开番茄官方章节页" if opened else "无法启动浏览器，请手动打开番茄章节页")
                        except Exception as exc:
                            self.show_toast(f"打开官方网页失败: {exc}")

                # 打开目录
                elif key == 't':
                    toc = TOCView(self.term, self.chapters, self.chapter_index)
                    chosen_idx = toc.run()
                    self._last_frame = None
                    if chosen_idx is not None and chosen_idx != self.chapter_index:
                        self.chapter_index = chosen_idx
                        self.show_toast(f"跳转至: 第 {self.chapter_index + 1} 章")
                        self.load_current_chapter(reset_offset=True)

                # 帮助
                elif key in ('?', '/'):
                    self.show_help_modal()
        finally:
            # q/Esc、Ctrl-C、异常退出都先落本地并同步最后一次云端进度。
            self.save_current_progress()
            self.flush_cloud_progress()
