from __future__ import annotations
import json
import os
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

        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.chapters_dir.mkdir(parents=True, exist_ok=True)

    # ------------------ 书架与阅读进度 ------------------

    def load_shelf(self) -> List[ShelfItem]:
        """加载书架，按最新活跃时间倒序排列（新的排在最前面）"""
        if not self.shelf_file.exists():
            return []
        
        try:
            with open(self.shelf_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                items = [ShelfItem.from_dict(item) for item in data]
                # Preserve the upstream shelf ordering and keep locally added books recent.
                items.sort(key=lambda x: (x.added_at or x.book.updated_at), reverse=True)
                return items
        except Exception:
            return []

    def save_shelf(self, items: List[ShelfItem]) -> None:
        """保存书架"""
        temp_file = self.shelf_file.with_suffix(".tmp")
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump([item.to_dict() for item in items], f, ensure_ascii=False, indent=2)
            temp_file.replace(self.shelf_file)
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
        return self.get_shelf_item(book_id) is not None

    def add_to_shelf(self, book: Book, added_at: Optional[float] = None) -> ShelfItem:
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
                found = it
                break
        
        if not found:
            found = ShelfItem(book=book, last_read_time=0.0, added_at=added_at or book.updated_at)
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
            if item.book.book_id in cloud_times:
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
        file_path = self.chapters_dir / f"{book_id}.json"
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump([ch.to_dict() for ch in chapters], f, ensure_ascii=False)
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

    # ------------------ 章节正文离线缓存 ------------------

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
