from __future__ import annotations
import json
import shutil
import time
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any

from .models import Book, Chapter, ShelfItem


class StorageManager:
    """本地存储管理器：书架、阅读进度、章节离线缓存"""

    def __init__(self, base_dir: Optional[str] = None):
        if base_dir:
            self.base_dir = Path(base_dir)
        else:
            self.base_dir = Path.home() / ".fanqie_reader"

        self.shelf_file = self.base_dir / "bookshelf.json"
        self.cache_dir = self.base_dir / "cache"
        self.chapters_dir = self.base_dir / "chapters"

        self._shelf_ids_cache: Optional[Tuple[Tuple[int, int], frozenset[str]]] = None
        self._chapters_nonempty_cache: Dict[str, Tuple[Tuple[int, int], bool]] = {}

        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.chapters_dir.mkdir(parents=True, exist_ok=True)

    # ------------------ 书架与阅读进度 ------------------

    def load_shelf(self) -> List[ShelfItem]:
        """加载书架，按最近打开时间优先倒序排列（最近阅读的排在最前面）"""
        if not self.shelf_file.exists():
            return []

        try:
            with open(self.shelf_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                items = [ShelfItem.from_dict(item) for item in data]
                items.sort(
                    key=lambda x: (x.last_read_time or 0.0, x.added_at or x.book.updated_at),
                    reverse=True,
                )
                return items
        except Exception:
            return []

    def save_shelf(self, items: List[ShelfItem]) -> None:
        """保存书架"""
        self._shelf_ids_cache = None
        temp_file = self.shelf_file.with_suffix(".tmp")
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump([item.to_dict() for item in items], f, ensure_ascii=False, indent=2)
            temp_file.replace(self.shelf_file)
            try:
                st = self.shelf_file.stat()
                self._shelf_ids_cache = (
                    (st.st_mtime_ns, st.st_size),
                    frozenset(it.book.book_id for it in items),
                )
            except OSError:
                pass
        except Exception:
            if temp_file.exists():
                temp_file.unlink(missing_ok=True)

    def get_shelf_item(self, book_id: str) -> Optional[ShelfItem]:
        items = self.load_shelf()
        for it in items:
            if it.book.book_id == book_id:
                return it
        return None

    def is_in_shelf(self, book_id: str) -> bool:
        try:
            st = self.shelf_file.stat()
        except OSError:
            self._shelf_ids_cache = None
            return False

        sig = (st.st_mtime_ns, st.st_size)
        if self._shelf_ids_cache is not None and self._shelf_ids_cache[0] == sig:
            return book_id in self._shelf_ids_cache[1]

        ids = frozenset(it.book.book_id for it in self.load_shelf())
        self._shelf_ids_cache = (sig, ids)
        return book_id in ids

    def add_to_shelf(
        self,
        book: Book,
        added_at: Optional[float] = None,
        in_cloud_shelf: Optional[bool] = None,
    ) -> ShelfItem:
        """添加书籍到书架，已存在则更新书籍元数据"""
        items = self.load_shelf()
        found: Optional[ShelfItem] = None
        for it in items:
            if it.book.book_id == book.book_id:
                it.book = book
                if added_at is not None:
                    it.added_at = added_at
                elif not it.added_at:
                    it.added_at = book.updated_at
                if in_cloud_shelf is not None:
                    it.in_cloud_shelf = in_cloud_shelf
                found = it
                break

        if not found:
            found = ShelfItem(
                book=book,
                last_read_time=0.0,
                added_at=added_at or book.updated_at,
                in_cloud_shelf=in_cloud_shelf,
            )
            items.insert(0, found)

        self.save_shelf(items)
        return found

    def update_cloud_progress(
        self,
        book_id: str,
        chapter_index: int,
        chapter_id: str,
        chapter_title: str,
        read_time: float,
    ) -> bool:
        """Apply cloud progress without replacing its timestamp with local time."""
        items = self.load_shelf()
        for item in items:
            if item.book.book_id == book_id:
                item.last_chapter_index = chapter_index
                item.last_chapter_id = chapter_id
                item.last_chapter_title = chapter_title
                item.line_offset = 0
                item.last_read_time = read_time
                self.save_shelf(items)
                return True
        return False

    def apply_cloud_shelf_order(self, rows: List[Dict[str, Any]]) -> None:
        """Use the phone shelf's latest operation time for synced book ordering."""
        cloud_times: Dict[str, float] = {}
        for row in rows:
            book_id = str(row.get("book_id", ""))
            if not book_id:
                continue
            timestamp = float(row.get("last_operate_time", 0) or 0)
            cloud_times[book_id] = max(timestamp, cloud_times.get(book_id, 0.0))

        items = self.load_shelf()
        changed = False
        for item in items:
            in_cloud = item.book.book_id in cloud_times
            if item.in_cloud_shelf is not in_cloud:
                item.in_cloud_shelf = in_cloud
                changed = True
            if in_cloud and item.added_at != cloud_times[item.book.book_id]:
                item.added_at = cloud_times[item.book.book_id]
                changed = True
        if changed:
            self.save_shelf(items)

    def remove_from_shelf(self, book_id: str) -> bool:
        """从书架移除"""
        items = self.load_shelf()
        new_items = [it for it in items if it.book.book_id != book_id]
        if len(new_items) != len(items):
            self.save_shelf(new_items)
            return True
        return False

    def update_progress(
        self,
        book_id: str,
        chapter_index: int,
        chapter_id: str,
        chapter_title: str,
        line_offset: int,
        book: Optional[Book] = None
    ) -> None:
        """保存阅读进度（断点续读）"""
        items = self.load_shelf()
        found = False
        for it in items:
            if it.book.book_id == book_id:
                it.last_chapter_index = chapter_index
                it.last_chapter_id = chapter_id
                it.last_chapter_title = chapter_title
                it.line_offset = max(0, line_offset)
                it.last_read_time = time.time()
                if book:
                    it.book = book
                found = True
                break

        if not found and book:
            new_item = ShelfItem(
                book=book,
                last_chapter_index=chapter_index,
                last_chapter_id=chapter_id,
                last_chapter_title=chapter_title,
                line_offset=max(0, line_offset),
                last_read_time=time.time()
            )
            items.insert(0, new_item)

        self.save_shelf(items)

    # ------------------ 目录元数据缓存 ------------------

    def save_chapters_meta(self, book_id: str, chapters: List[Chapter]) -> None:
        """缓存整本书的章节目录"""
        self._chapters_nonempty_cache.pop(book_id, None)
        file_path = self.chapters_dir / f"{book_id}.json"
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump([ch.to_dict() for ch in chapters], f, ensure_ascii=False)
            try:
                st = file_path.stat()
                self._chapters_nonempty_cache[book_id] = ((st.st_mtime_ns, st.st_size), bool(chapters))
            except OSError:
                pass
        except Exception:
            pass

    def get_chapters_meta(self, book_id: str) -> Optional[List[Chapter]]:
        """获取缓存的章节目录"""
        file_path = self.chapters_dir / f"{book_id}.json"
        if not file_path.exists():
            return None
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return [Chapter.from_dict(ch) for ch in data]
        except Exception:
            return None

    # ------------------ 章节正文离线缓存 & 下载状态 ------------------

    def get_downloaded_chapter_count(self, book_id: str) -> int:
        """返回本地已下载的章节数量"""
        book_cache = self.cache_dir / book_id
        if not book_cache.exists():
            return 0
        try:
            return sum(1 for p in book_cache.iterdir() if p.suffix == ".txt")
        except Exception:
            return 0

    def _has_chapters_meta(self, book_id: str) -> bool:
        """检查书籍是否有非空目录缓存，结果按文件 stat 缓存在内存中"""
        file_path = self.chapters_dir / f"{book_id}.json"
        try:
            st = file_path.stat()
        except OSError:
            self._chapters_nonempty_cache.pop(book_id, None)
            return False

        sig = (st.st_mtime_ns, st.st_size)
        cached = self._chapters_nonempty_cache.get(book_id)
        if cached is not None and cached[0] == sig:
            return cached[1]

        chapters = self.get_chapters_meta(book_id)
        has_chapters = bool(chapters)
        self._chapters_nonempty_cache[book_id] = (sig, has_chapters)
        return has_chapters

    def is_book_downloaded(self, book_id: str) -> bool:
        """判断书籍是否已在本地完成下载并分章"""
        book_cache = self.cache_dir / book_id
        if not book_cache.exists():
            return False
        try:
            has_txt = any(p.suffix == ".txt" for p in book_cache.iterdir())
        except Exception:
            return False
        if not has_txt:
            return False
        return self._has_chapters_meta(book_id)

    def clear_book_cache(self, book_id: str) -> None:
        """清空指定书籍的本地章节正文与目录缓存（换源重下时使用）"""
        self._chapters_nonempty_cache.pop(book_id, None)
        book_cache = self.cache_dir / book_id
        if book_cache.exists():
            shutil.rmtree(book_cache, ignore_errors=True)
        meta_file = self.chapters_dir / f"{book_id}.json"
        if meta_file.exists():
            meta_file.unlink(missing_ok=True)

    def get_chapter_cache(self, book_id: str, item_id: str) -> Optional[Tuple[str, str]]:
        """读取已缓存的章节正文"""
        book_cache = self.cache_dir / book_id
        file_path = book_cache / f"{item_id}.txt"
        if not file_path.exists():
            return None
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                if not lines:
                    return None
                title = lines[0].strip()
                content = "".join(lines[1:])
                return title, content
        except Exception:
            return None

    def save_chapter_cache(self, book_id: str, item_id: str, title: str, content: str) -> None:
        """保存章节正文到本地缓存"""
        book_cache = self.cache_dir / book_id
        book_cache.mkdir(parents=True, exist_ok=True)
        file_path = book_cache / f"{item_id}.txt"
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(f"{title}\n")
                f.write(content)
        except Exception:
            pass
