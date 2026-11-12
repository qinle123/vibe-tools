from __future__ import annotations
import time
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any

@dataclass
class Chapter:
    item_id: str
    title: str
    volume_name: str = ""
    index: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Chapter:
        return cls(
            item_id=str(data.get("item_id", "")),
            title=str(data.get("title", "")),
            volume_name=str(data.get("volume_name", "")),
            index=int(data.get("index", 0))
        )

@dataclass
class Book:
    book_id: str
    title: str
    author: str = ""
    abstract: str = ""
    category: str = ""
    thumb_url: str = ""
    chapter_total: int = 0
    updated_at: float = field(default_factory=time.time)
    media_genre: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Book:
        return cls(
            book_id=str(data.get("book_id", "")),
            title=str(data.get("title", "")),
            author=str(data.get("author", "")),
            abstract=str(data.get("abstract", "")),
            category=str(data.get("category", "")),
            thumb_url=str(data.get("thumb_url", "")),
            chapter_total=int(data.get("chapter_total", 0)),
            media_genre=int(data.get("media_genre", 0) or 0),
            updated_at=float(data.get("updated_at", time.time()))
        )

@dataclass
class ShelfItem:
    book: Book
    last_chapter_index: int = 0
    last_chapter_id: str = ""
    last_chapter_title: str = ""
    line_offset: int = 0
    last_read_time: float = field(default_factory=time.time)
    added_at: float = 0.0

    def progress_percent(self) -> float:
        if self.book.chapter_total <= 0:
            return 0.0
        return min(100.0, max(0.0, ((self.last_chapter_index + 1) / self.book.chapter_total) * 100))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "book": self.book.to_dict(),
            "last_chapter_index": self.last_chapter_index,
            "last_chapter_id": self.last_chapter_id,
            "last_chapter_title": self.last_chapter_title,
            "line_offset": self.line_offset,
            "last_read_time": self.last_read_time,
            "added_at": self.added_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ShelfItem:
        return cls(
            book=Book.from_dict(data.get("book", {})),
            last_chapter_index=int(data.get("last_chapter_index", 0)),
            last_chapter_id=str(data.get("last_chapter_id", "")),
            last_chapter_title=str(data.get("last_chapter_title", "")),
            line_offset=int(data.get("line_offset", 0)),
            last_read_time=float(data.get("last_read_time", time.time())),
            added_at=float(data.get("added_at", 0.0)),
        )
