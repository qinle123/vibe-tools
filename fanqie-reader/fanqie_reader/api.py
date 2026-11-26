from __future__ import annotations
import json
import re
import urllib.request
import urllib.parse
import urllib.error
import time
from typing import List, Tuple, Optional, Dict, Any

from .models import Book, Chapter

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

class FanqieAPI:
    """番茄小说官方数据接口客户端"""

    def __init__(self, timeout: int = 10, retries: int = 3):
        self.timeout = timeout
        self.retries = retries

    def _fetch(self, url: str, headers: Optional[Dict[str, str]] = None) -> str:
        req_headers = dict(DEFAULT_HEADERS)
        if headers:
            req_headers.update(headers)
        
        last_err: Optional[Exception] = None
        for attempt in range(self.retries):
            try:
                req = urllib.request.Request(url, headers=req_headers)
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return resp.read().decode("utf-8", errors="ignore")
            except Exception as e:
                last_err = e
                time.sleep(0.5 * (attempt + 1))
        
        raise RuntimeError(f"请求失败 ({url}): {last_err}")

    def _parse_initial_state(self, html: str) -> Dict[str, Any]:
        """从 SSR HTML 中提取 window.__INITIAL_STATE__ 数据"""
        prefix = "__INITIAL_STATE__="
        start = html.find(prefix)
        if start == -1:
            raise ValueError("页面中未找到 __INITIAL_STATE__ 数据")
        
        start += len(prefix)
        # 去除开头可能的空格或 (function(){ return 
        sub = html[start:].lstrip()
        if sub.startswith("(function(){ return "):
            sub = sub[len("(function(){ return "):]
        
        decoder = json.JSONDecoder()
        data, _ = decoder.raw_decode(sub)
        return data

    def search_books(self, query: str, offset: int = 0, count: int = 15) -> List[Book]:
        """根据关键词搜索小说"""
        if not query.strip():
            return []
        
        encoded_q = urllib.parse.quote(query.strip())
        url = (
            f"https://novel.snssdk.com/api/novel/channel/homepage/search/search/v1/"
            f"?aid=13&q={encoded_q}&offset={offset}&count={count}"
        )
        
        try:
            resp_text = self._fetch(url)
            data = json.loads(resp_text)
            ret_data = data.get("data", {}).get("ret_data", [])
            books: List[Book] = []
            
            for item in ret_data:
                # 兼容不同返回结构
                book_id = str(item.get("book_id", "") or item.get("id", ""))
                if not book_id:
                    continue
                media_genre = int(item.get("genre", 0) or 0)
                if media_genre == 4:
                    continue
                
                title = str(item.get("book_name", "") or item.get("title", ""))
                # 去除 <em> 标签
                title = re.sub(r'</?em>', '', title)
                
                author = str(item.get("author", ""))
                abstract = str(item.get("abstract", "") or item.get("description", ""))
                category = str(item.get("category", "") or item.get("category_v2", ""))
                thumb_url = str(item.get("thumb_url", "") or item.get("thumb_uri", ""))
                
                books.append(Book(
                    book_id=book_id,
                    title=title,
                    author=author,
                    abstract=abstract,
                    category=category,
                    thumb_url=thumb_url,
                    chapter_total=int(item.get("chapter_count", 0)),
                    media_genre=media_genre,
                ))
            return books
        except Exception as e:
            raise RuntimeError(f"搜索失败: {e}")

    def get_book_info(self, book_id: str) -> Book:
        """极速获取书籍基本元信息（不耗时解析完整章节目录）"""
        url = f"https://fanqienovel.com/page/{book_id}"
        try:
            page_html = self._fetch(url)
            state = self._parse_initial_state(page_html)
        except Exception:
            data = json.loads(self._fetch(
                f"https://api.fanqiesdk.com/api/novel/book/page/data/v1/?aid=1967&book_id={book_id}"
            )).get("data", {})
            return Book(
                book_id=book_id,
                title=str(data.get("book_name", f"书籍_{book_id}")),
                author=str(data.get("author", "") if isinstance(data.get("author", ""), str) else data.get("author", {}).get("name", "")),
                abstract=str(data.get("abstract", "")),
                category=str(data.get("category", "")),
                thumb_url=str(data.get("thumb_url", data.get("thumb_uri", ""))),
                chapter_total=int(data.get("serial_num", 0) or 0),
                media_genre=int(data.get("genre", 0) or 0),
            )
        
        page = state.get("page", {})
        book_title = page.get("bookName", "") or page.get("title", f"书籍_{book_id}")
        author_name = page.get("authorName", "") or page.get("author", "")
        abstract = page.get("abstract", "") or page.get("description", "")
        category = page.get("category", "") or page.get("categoryV2", "")
        thumb_url = page.get("thumbUrl", "") or page.get("thumbUri", "")
        chapter_total = int(page.get("chapterTotal", 0))

        return Book(
            book_id=book_id,
            title=book_title,
            author=author_name,
            abstract=abstract,
            category=category,
            thumb_url=thumb_url,
            chapter_total=chapter_total,
            media_genre=int(page.get("genre", 0) or 0),
        )

    def get_book_detail(self, book_id: str) -> Tuple[Book, List[Chapter]]:
        """获取书籍详情与正序目录列表"""
        url = f"https://fanqienovel.com/page/{book_id}"
        try:
            page_html = self._fetch(url)
            state = self._parse_initial_state(page_html)
        except Exception:
            detail_url = (
                "https://api.fanqiesdk.com/api/novel/book/directory/detail/v1/"
                f"?aid=1967&book_id={book_id}"
            )
            payload = json.loads(self._fetch(detail_url)).get("data", {})
            info = json.loads(self._fetch(
                f"https://api.fanqiesdk.com/api/novel/book/page/data/v1/?aid=1967&book_id={book_id}"
            )).get("data", {})
            author = info.get("author", "")
            if isinstance(author, dict):
                author = author.get("name", "")
            book = Book(
                book_id=book_id,
                title=str(info.get("book_name", f"书籍_{book_id}")),
                author=str(author),
                abstract=str(info.get("abstract", "")),
                category=str(info.get("category", "")),
                thumb_url=str(info.get("thumb_url", "")),
                chapter_total=int(info.get("serial_num", 0) or 0),
                media_genre=int(info.get("genre", 0) or 0),
            )
            chapters = []
            idx = 0
            for volume in payload.get("chapterListWithVolume", []):
                for chapter in volume:
                    chapters.append(Chapter(
                        item_id=str(chapter.get("itemId", "")),
                        title=str(chapter.get("title", "")),
                        volume_name=str(chapter.get("volume_name", "")),
                        index=idx,
                    ))
                    idx += 1
            book.chapter_total = book.chapter_total or len(chapters)
            return book, chapters
        
        page = state.get("page", {})
        book_title = page.get("bookName", "") or page.get("title", f"书籍_{book_id}")
        author_name = page.get("authorName", "") or page.get("author", "")
        abstract = page.get("abstract", "") or page.get("description", "")
        category = page.get("category", "") or page.get("categoryV2", "")
        thumb_url = page.get("thumbUrl", "") or page.get("thumbUri", "")
        chapter_total = int(page.get("chapterTotal", 0))

        book = Book(
            book_id=book_id,
            title=book_title,
            author=author_name,
            abstract=abstract,
            category=category,
            thumb_url=thumb_url,
            chapter_total=chapter_total,
            media_genre=int(page.get("genre", 0) or 0),
        )

        chapters: List[Chapter] = []
        vols = page.get("chapterListWithVolume", [])
        vol_names = page.get("volumeNameList", [])
        
        idx = 0
        if vols:
            for v_idx, vol in enumerate(vols):
                v_name = vol_names[v_idx] if v_idx < len(vol_names) else ""
                for ch in vol:
                    item_id = str(ch.get("itemId", ""))
                    title = str(ch.get("title", ""))
                    if item_id:
                        chapters.append(Chapter(
                            item_id=item_id,
                            title=title,
                            volume_name=v_name,
                            index=idx
                        ))
                        idx += 1
        else:
            # 备选：从 itemIds 构造（注意网页中的 itemIds 通常是倒序的，需要翻转）
            item_ids = page.get("itemIds", [])
            for item_id in reversed(item_ids):
                chapters.append(Chapter(
                    item_id=str(item_id),
                    title=f"第 {idx + 1} 章",
                    index=idx
                ))
                idx += 1

        if not book.chapter_total:
            book.chapter_total = len(chapters)

        return book, chapters

    # ------------------ 官方云端书架与阅读进度同步 ------------------

    def get_cloud_bookshelf(self, cookie_header: str) -> List[Dict[str, Any]]:
        """获取手机端/云端官方书架列表"""
        url = "https://fanqienovel.com/reading/bookapi/bookshelf/info/v:version/?aid=1967&iid=0&version_code=57700&update_version_code=57700"
        headers = {"Cookie": cookie_header, "Referer": "https://fanqienovel.com/"}
        try:
            resp_str = self._fetch(url, headers=headers)
            data = json.loads(resp_str)
            d = data.get("data", {})
            rows = d.get("book_shelf_info") or d.get("bookShelfInfo") or []
            return rows
        except Exception as e:
            raise RuntimeError(f"获取云端书架失败: {e}")

    def get_cloud_progress(self, cookie_header: str) -> List[Dict[str, Any]]:
        """获取官方云端小说的阅读进度记录"""
        url = "https://fanqienovel.com/api/reader/book/progress"
        headers = {"Cookie": cookie_header, "Referer": "https://fanqienovel.com/"}
        try:
            resp_str = self._fetch(url, headers=headers)
            data = json.loads(resp_str)
            rows = data.get("data", [])
            if isinstance(rows, list):
                return rows
            return []
        except Exception as e:
            raise RuntimeError(f"获取云端阅读进度失败: {e}")

