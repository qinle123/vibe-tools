from __future__ import annotations
import hashlib
import time
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any


def make_local_book_id(title: str, author: str = "") -> str:
    """Generate a stable book_id for books searched/downloaded from external sources."""
    key = f"{title.strip()}|{author.strip()}".encode("utf-8")
    return "local_" + hashlib.md5(key).hexdigest()[:12]


@dataclass
class Chapter:
    item_id: str
    title: str
    volume_name: str = ""
    index: int = 0
    source_url: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Chapter:
        return cls(
            item_id=str(data.get("item_id", "")),
            title=str(data.get("title", "")),
            volume_name=str(data.get("volume_name", "")),
            index=int(data.get("index", 0)),
            source_url=str(data.get("source_url", "")),
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
    source_name: str = ""
    source_url: str = ""

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
            updated_at=float(data.get("updated_at", time.time())),
            source_name=str(data.get("source_name", "")),
            source_url=str(data.get("source_url", "")),
        )


@dataclass
class SourceBook:
    """A book search hit from an external download source (so-novel rule)."""
    source_name: str
    source_base_url: str
    book_url: str
    title: str
    author: str = ""
    category: str = ""
    latest_chapter: str = ""
    last_update_time: str = ""
    intro: str = ""
    match_score: int = 0


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
