from __future__ import annotations
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from bs4 import BeautifulSoup, Tag

from .models import Book, Chapter, SourceBook
from .storage import StorageManager

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

_DATA_DIR = Path(__file__).resolve().parent / "data"
BUILTIN_SOURCES_FILE = _DATA_DIR / "book_sources.json"


def _decode_html(raw: bytes, content_type: str = "") -> str:
    """Decode HTML bytes using HTTP header, meta charset, or UTF-8/GB18030 fallback."""
    match = re.search(r"charset=([a-zA-Z0-9_-]+)", content_type, re.IGNORECASE)
    if match:
        enc = match.group(1).strip().strip("\"'")
        try:
            return raw.decode(enc, errors="replace")
        except LookupError:
            pass

    head = raw[:4096].decode("ascii", errors="ignore")
    meta_match = re.search(r'charset=["\']?([a-zA-Z0-9_-]+)', head, re.IGNORECASE)
    if meta_match:
        enc = meta_match.group(1).strip()
        try:
            return raw.decode(enc, errors="replace")
        except LookupError:
            pass

    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _split_selector_and_js(expr: str) -> Tuple[str, str, str]:
    """Split 'css@attr@js:...' into (css_selector, attr_name, js_expr)."""
    if not expr:
        return "", "", ""
    js_part = ""
    if "@js:" in expr:
        expr, js_part = expr.split("@js:", 1)
    attr_part = ""
    if "@" in expr:
        expr, attr_part = expr.rsplit("@", 1)
    return expr.strip(), attr_part.strip(), js_part.strip()


def _apply_simple_js(value: str, js_expr: str) -> str:
    """Apply common so-novel @js transforms without a JS engine."""
    if not js_expr or not value:
        return value
    # e.g. r=r.replace(/^\[[^\]]*\]/,'') or r.replace(/[^：]*：/,'')
    for m in re.finditer(r"r\.replace\(/(.+?)/([gimsuy]*),\s*['\"](.*?)['\"]\)", js_expr):
        pattern, flags_str, repl = m.group(1), m.group(2), m.group(3)
        flags = re.IGNORECASE if "i" in flags_str else 0
        try:
            value = re.sub(pattern, repl, value, count=0 if "g" in flags_str else 1, flags=flags)
        except re.error:
            pass
    # e.g. r='http://www.mcxs.la'+r
    prefix_m = re.search(r"r\s*=\s*['\"]([^'\"]+)['\"]\s*\+\s*r", js_expr)
    if prefix_m and not value.startswith("http"):
        value = prefix_m.group(1) + value
    return value.strip()


def _extract_text(root: Tag, expr: str) -> str:
    """Extract text or attribute from a BeautifulSoup Tag using a so-novel rule expression."""
    selector, attr, js_expr = _split_selector_and_js(expr)
    if not selector:
        return ""
    try:
        el = root.select_one(selector)
    except Exception:
        return ""
    if el is None:
        return ""
    if attr:
        val = str(el.get(attr, "") or "")
    else:
        val = el.get_text(" ", strip=True)
    return _apply_simple_js(val, js_expr).strip()


def _extract_href(root: Tag, expr: str, base_url: str) -> str:
    """Extract an absolute URL from a BeautifulSoup Tag."""
    selector, attr, _ = _split_selector_and_js(expr)
    if not selector:
        return ""
    try:
        el = root.select_one(selector)
    except Exception:
        return ""
    if el is None:
        return ""
    href = str(el.get(attr or "href", "") or "").strip()
    if not href or href.startswith("javascript:"):
        return ""
    return urllib.parse.urljoin(base_url, href)


def _parse_post_data(template: str, keyword: str) -> Dict[str, str]:
    """Parse so-novel POST data template like '{searchkey: %s, searchtype: all}'."""
    body = template.strip()
    if body.startswith("{") and body.endswith("}"):
        body = body[1:-1]
    result: Dict[str, str] = {}
    for pair in body.split(","):
        if ":" not in pair:
            continue
        k, v = pair.split(":", 1)
        key = k.strip().strip("\"'")
        val = v.strip().strip("\"'")
        if "%s" in val:
            val = val.replace("%s", keyword)
        result[key] = val
    return result


def _normalize_text(s: str) -> str:
    return re.sub(r"[\s·•:：\-_《》()（）\[\]【】]", "", s or "").lower()


def score_match(item: SourceBook, target_title: str, target_author: str = "") -> int:
    """Rank how well a SourceBook matches target title and author (higher is better)."""
    n_title = _normalize_text(item.title)
    n_target = _normalize_text(target_title)
    n_author = _normalize_text(item.author)
    n_target_author = _normalize_text(target_author)

    score = 0
    if n_target:
        if n_title == n_target:
            score += 120
        elif n_target in n_title or n_title in n_target:
            score += 30
    if n_target_author and n_author:
        if n_author == n_target_author:
            score += 80
        elif n_target_author in n_author or n_author in n_target_author:
            score += 25
    return score


class SourceManager:
    """so-novel 书源规则引擎与多线程下载器"""

    def __init__(
        self,
        rules_path: Optional[Path] = None,
        user_rules_path: Optional[Path] = None,
        timeout: int = 12,
        retries: int = 2,
    ):
        self.timeout = timeout
        self.retries = retries
        self.rules: List[Dict[str, Any]] = self._load_rules(rules_path, user_rules_path)

    @staticmethod
    def _load_rules(
        rules_path: Optional[Path],
        user_rules_path: Optional[Path],
    ) -> List[Dict[str, Any]]:
        path = rules_path or BUILTIN_SOURCES_FILE
        rules: List[Dict[str, Any]] = []
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        rules.extend(r for r in data if not r.get("disabled"))
            except Exception:
                pass
        extra = user_rules_path or (Path.home() / ".fanqie_reader" / "sources.json")
        if extra.exists():
            try:
                with open(extra, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        by_name = {r.get("name"): r for r in rules if r.get("name")}
                        for r in data:
                            if r.get("disabled"):
                                by_name.pop(r.get("name"), None)
                            elif r.get("name"):
                                by_name[r["name"]] = r
                        rules = list(by_name.values())
            except Exception:
                pass
        return rules

    def get_rule_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        for r in self.rules:
            if r.get("name") == name:
                return r
        return None

    def _http_get(
        self,
        url: str,
        referer: str = "",
        cookies: str = "",
        timeout: Optional[int] = None,
    ) -> Tuple[str, str]:
        """Perform HTTP GET and return (decoded_html, final_url)."""
        headers = dict(DEFAULT_HEADERS)
        if referer:
            headers["Referer"] = referer
        if cookies:
            headers["Cookie"] = cookies

        req_timeout = timeout or self.timeout
        last_err: Optional[Exception] = None
        for attempt in range(self.retries):
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=req_timeout) as resp:
                    raw = resp.read()
                    ct = resp.headers.get("Content-Type", "")
                    return _decode_html(raw, ct), resp.geturl()
            except Exception as e:
                last_err = e
                time.sleep(0.3 * (attempt + 1))
        raise RuntimeError(f"请求失败 ({url}): {last_err}")

    def _http_post(
        self,
        url: str,
        form_data: Dict[str, str],
        referer: str = "",
        cookies: str = "",
        timeout: Optional[int] = None,
    ) -> Tuple[str, str]:
        """Perform HTTP POST and return (decoded_html, final_url)."""
        headers = dict(DEFAULT_HEADERS)
        if referer:
            headers["Referer"] = referer
        if cookies:
            headers["Cookie"] = cookies
        headers["Content-Type"] = "application/x-www-form-urlencoded"

        encoded = urllib.parse.urlencode(form_data).encode("utf-8")
        req_timeout = timeout or self.timeout
        last_err: Optional[Exception] = None
        for attempt in range(self.retries):
            try:
                req = urllib.request.Request(url, data=encoded, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=req_timeout) as resp:
                    raw = resp.read()
                    ct = resp.headers.get("Content-Type", "")
                    return _decode_html(raw, ct), resp.geturl()
            except Exception as e:
                last_err = e
                time.sleep(0.3 * (attempt + 1))
        raise RuntimeError(f"POST请求失败 ({url}): {last_err}")

    # ------------------ 搜索 ------------------

    def search_source(self, rule: Dict[str, Any], keyword: str) -> List[SourceBook]:
        """Search a single so-novel source rule."""
        search_cfg = rule.get("search")
        if not search_cfg or not keyword.strip():
            return []

        base_url = rule.get("url", "")
        method = str(search_cfg.get("method", "get")).lower()
        search_url = str(search_cfg.get("url", ""))
        cookies = str(search_cfg.get("cookies", "") or "")
        timeout = int(search_cfg.get("timeout", self.timeout) or self.timeout)
        timeout = min(timeout, 15)

        if method == "post":
            data_tpl = str(search_cfg.get("data", "{searchkey: %s}"))
            form = _parse_post_data(data_tpl, keyword.strip())
            html, final_url = self._http_post(
                search_url, form, referer=base_url, cookies=cookies, timeout=timeout
            )
        else:
            q_enc = urllib.parse.quote(keyword.strip())
            target_url = search_url.replace("%s", q_enc)
            html, final_url = self._http_get(
                target_url, referer=base_url, cookies=cookies, timeout=timeout
            )

        soup = BeautifulSoup(html, "html.parser")
        result_sel = str(search_cfg.get("result", ""))
        if not result_sel:
            return []
        try:
            rows = soup.select(result_sel)
        except Exception:
            return []

        results: List[SourceBook] = []
        for row in rows:
            title = _extract_text(row, str(search_cfg.get("bookName", "")))
            book_url = _extract_href(row, str(search_cfg.get("bookName", "")), final_url or base_url)
            if not title or not book_url:
                continue
            author = _extract_text(row, str(search_cfg.get("author", "")))
            # Strip common "作者：" prefixes
            author = re.sub(r"^(?:作者|作\s*者)[：:\s]*", "", author).strip()
            latest = _extract_text(row, str(search_cfg.get("latestChapter", "")))
            updated = _extract_text(row, str(search_cfg.get("lastUpdateTime", "")))
            category = _extract_text(row, str(search_cfg.get("category", "")))
            intro = _extract_text(row, str(search_cfg.get("intro", "")))

            results.append(SourceBook(
                source_name=str(rule.get("name", "")),
                source_base_url=base_url,
                book_url=book_url,
                title=title,
                author=author,
                category=category,
                latest_chapter=latest,
                last_update_time=updated,
                intro=intro,
            ))
        return results

    def search_all(
        self,
        keyword: str,
        target_title: str = "",
        target_author: str = "",
        max_workers: int = 8,
        on_progress: Optional[Callable[[int, int, str], None]] = None,
    ) -> List[SourceBook]:
        """Search all enabled sources concurrently and rank results."""
        searchable = [r for r in self.rules if r.get("search")]
        if not searchable or not keyword.strip():
            return []

        all_hits: List[SourceBook] = []
        total = len(searchable)
        done = 0
        with ThreadPoolExecutor(max_workers=min(max_workers, total)) as pool:
            futures = {pool.submit(self.search_source, r, keyword): r for r in searchable}
            for fut in as_completed(futures):
                rule = futures[fut]
                done += 1
                try:
                    hits = fut.result()
                    all_hits.extend(hits)
                except Exception:
                    pass
                if on_progress:
                    on_progress(done, total, str(rule.get("name", "")))

        rank_title = target_title or keyword.strip()
        for item in all_hits:
            item.match_score = score_match(item, rank_title, target_author)

        all_hits.sort(key=lambda x: x.match_score, reverse=True)
        return all_hits

    # ------------------ 目录解析 ------------------

    def _resolve_toc_entry(self, rule: Dict[str, Any], book_url: str) -> Tuple[str, str]:
        """Resolve (toc_url, base_uri) following so-novel book.url / toc.url / toc.baseUri."""
        book_cfg = rule.get("book", {})
        toc_cfg = rule.get("toc", {})
        base_uri = str(toc_cfg.get("baseUri", "") or "")
        toc_url_tpl = str(toc_cfg.get("url", "") or "")
        book_url_re = str(book_cfg.get("url", "") or "").split("@js:")[0].strip()

        book_id = None
        if book_url_re:
            m = re.search(book_url_re, book_url)
            if m and m.groups():
                book_id = m.group(1)

        if book_id and base_uri and "%s" in base_uri:
            base_uri = base_uri.replace("%s", book_id)
        if book_id and toc_url_tpl and "%s" in toc_url_tpl:
            toc_url = toc_url_tpl.replace("%s", book_id)
        else:
            toc_url = book_url

        return toc_url, base_uri or toc_url

    def _parse_52bqg_like_toc(self, html: str, base_url: str) -> List[Tuple[str, str]]:
        """Handle 52bqg/snxsw style hidden-li & read_tz(id) JS TOC without a JS engine."""
        pre = max([int(m) for m in re.findall(r"li:nth-child\((\d+)\)\s*\{\s*display\s*:\s*none", html)] or [0])
        post = max([int(m) for m in re.findall(r"li:nth-last-child\((\d+)\)\s*\{\s*display\s*:\s*none", html)] or [0])
        bid_counts: Dict[str, int] = {}
        for bid in re.findall(r"/book_(\d+)/", html):
            bid_counts[bid] = bid_counts.get(bid, 0) + 1
        best_bid = max(bid_counts, key=lambda k: bid_counts[k]) if bid_counts else ""

        soup = BeautifulSoup(html, "html.parser")
        uls = soup.select("ul.section-list")
        if not uls:
            return []
        best_ul = max(uls, key=lambda u: len(u.find_all("li")))
        lis = best_ul.find_all("li")
        if pre or post:
            lis = lis[pre : max(pre, len(lis) - post)]

        entries: List[Tuple[str, str]] = []
        for li in lis:
            a = li.find("a")
            if not a:
                continue
            title = a.get_text(strip=True)
            href = str(a.get("href", "") or "").strip()
            onclick = str(a.get("onclick", "") or "")
            if not href and onclick:
                m = re.search(r"read_tz\((\d+)\)", onclick)
                if m and best_bid:
                    parsed = urllib.parse.urlparse(base_url)
                    origin = f"{parsed.scheme}://{parsed.netloc}"
                    href = f"{origin}/book_{best_bid}/{m.group(1)}.html"
            if href and title:
                entries.append((title, urllib.parse.urljoin(base_url, href)))
        return entries

    def fetch_toc(self, rule: Dict[str, Any], book_url: str) -> List[Chapter]:
        """Fetch full table of contents for a book from a source rule."""
        toc_cfg = rule.get("toc", {})
        item_sel = str(toc_cfg.get("item", "") or "")
        next_sel = str(toc_cfg.get("nextPage", "") or "")
        cookies = str(rule.get("search", {}).get("cookies", "") or "")
        base_referer = str(rule.get("url", "") or book_url)

        toc_url, base_uri = self._resolve_toc_entry(rule, book_url)
        html, final_url = self._http_get(toc_url, referer=base_referer, cookies=cookies)
        effective_base = base_uri if base_uri != toc_url else (final_url or toc_url)

        page_urls: List[str] = [toc_url]
        first_soup = BeautifulSoup(html, "html.parser")

        # Check pagination
        if next_sel:
            try:
                opts = first_soup.select(next_sel)
                if opts and opts[0].name == "option":
                    for opt in opts:
                        val = str(opt.get("value", "") or "").strip()
                        if val:
                            u = urllib.parse.urljoin(effective_base, val)
                            if u not in page_urls:
                                page_urls.append(u)
            except Exception:
                pass

        raw_entries: List[Tuple[str, str]] = []
        visited = set()

        def _extract_page(page_html: str, page_url: str) -> Optional[str]:
            if "read_tz(" in page_html and "section-list" in page_html:
                raw_entries.extend(self._parse_52bqg_like_toc(page_html, effective_base))
            else:
                soup = BeautifulSoup(page_html, "html.parser")
                if item_sel:
                    try:
                        for a in soup.select(item_sel):
                            title = a.get_text(" ", strip=True)
                            href = str(a.get("href", "") or "").strip()
                            if title and href and not href.startswith("javascript:"):
                                raw_entries.append((title, urllib.parse.urljoin(effective_base, href)))
                    except Exception:
                        pass
                if next_sel:
                    try:
                        nxt = soup.select_one(next_sel)
                        if nxt and nxt.name != "option":
                            href = str(nxt.get("href", "") or "").strip()
                            if href and not href.startswith("javascript:"):
                                return urllib.parse.urljoin(effective_base, href)
                    except Exception:
                        pass
            return None

        if len(page_urls) > 1:
            # All pagination URLs extracted upfront (e.g. select > option)
            for idx_p, purl in enumerate(page_urls[:100]):
                if purl in visited:
                    continue
                visited.add(purl)
                phtml = html if idx_p == 0 else self._http_get(purl, referer=toc_url, cookies=cookies)[0]
                _extract_page(phtml, purl)
        else:
            cur_url: Optional[str] = toc_url
            cur_html = html
            for _ in range(100):
                if not cur_url or cur_url in visited:
                    break
                visited.add(cur_url)
                nxt_url = _extract_page(cur_html, cur_url)
                if not nxt_url or nxt_url in visited:
                    break
                cur_url = nxt_url
                cur_html, _ = self._http_get(cur_url, referer=toc_url, cookies=cookies)

        if toc_cfg.get("isDesc"):
            raw_entries.reverse()

        # Deduplicate while preserving order
        seen_urls = set()
        chapters: List[Chapter] = []
        for title, ch_url in raw_entries:
            if ch_url in seen_urls:
                continue
            seen_urls.add(ch_url)
            idx = len(chapters)
            chapters.append(Chapter(
                item_id=f"ch_{idx:05d}",
                title=title,
                index=idx,
                source_url=ch_url,
            ))
        return chapters

    # ------------------ 章节正文抓取 ------------------

    def _clean_chapter_html(self, content_el: Tag, ch_cfg: Dict[str, Any]) -> str:
        """Clean chapter HTML element into newline-separated paragraphs."""
        filter_tag = str(ch_cfg.get("filterTag", "") or "")
        if filter_tag:
            for sel in filter_tag.split(","):
                sel = sel.strip()
                if not sel:
                    continue
                try:
                    for bad in content_el.select(sel):
                        bad.decompose()
                except Exception:
                    pass

        for br in content_el.find_all("br"):
            br.replace_with("\n")

        if ch_cfg.get("paragraphTagClosed"):
            p_tags = content_el.find_all("p")
            if p_tags:
                raw_text = "\n".join(p.get_text(" ", strip=True) for p in p_tags)
            else:
                raw_text = content_el.get_text("\n")
        else:
            raw_text = content_el.get_text("\n")

        raw_text = raw_text.replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")

        filter_txt = str(ch_cfg.get("filterTxt", "") or "")
        if filter_txt:
            try:
                raw_text = re.sub(filter_txt, "", raw_text, flags=re.MULTILINE)
            except re.error:
                pass

        paragraphs = [line.strip() for line in raw_text.split("\n") if line.strip()]
        return "\n".join(paragraphs)

    def fetch_chapter_content(self, rule: Dict[str, Any], chapter_url: str) -> Tuple[str, str]:
        """Fetch and clean a single chapter (handling multi-page chapters)."""
        ch_cfg = rule.get("chapter", {})
        title_sel = str(ch_cfg.get("title", "") or "")
        content_sel = str(ch_cfg.get("content", "") or "")
        next_sel = str(ch_cfg.get("nextPage", "") or "")
        cookies = str(rule.get("search", {}).get("cookies", "") or "")
        referer = str(rule.get("url", "") or chapter_url)
        timeout = int(ch_cfg.get("timeout", self.timeout) or self.timeout)
        timeout = min(timeout, 15)

        visited = set()
        cur_url: Optional[str] = chapter_url
        chapter_title = ""
        parts: List[str] = []

        for _ in range(12):
            if not cur_url or cur_url in visited:
                break
            visited.add(cur_url)
            html, final_url = self._http_get(cur_url, referer=referer, cookies=cookies, timeout=timeout)
            soup = BeautifulSoup(html, "html.parser")

            if not chapter_title and title_sel:
                chapter_title = _extract_text(soup, title_sel)

            if content_sel:
                try:
                    c_el = soup.select_one(content_sel)
                except Exception:
                    c_el = None
                if c_el is not None:
                    cleaned = self._clean_chapter_html(c_el, ch_cfg)
                    if cleaned:
                        parts.append(cleaned)

            if not next_sel:
                break
            nxt_href = _extract_href(soup, next_sel, final_url or cur_url)
            if not nxt_href or nxt_href in visited:
                break
            # Some sites point nextPage to the next chapter instead of sub-page (e.g. _2.html vs next id)
            cur_base = cur_url.rsplit("/", 1)[-1].split(".")[0].split("_")[0]
            nxt_base = nxt_href.rsplit("/", 1)[-1].split(".")[0].split("_")[0]
            if cur_base != nxt_base and "_" not in nxt_href.rsplit("/", 1)[-1]:
                break
            cur_url = nxt_href

        return chapter_title, "\n".join(parts)

    # ------------------ 全书下载与分章落盘 ------------------

    def download_book(
        self,
        source_book: SourceBook,
        storage: StorageManager,
        book: Book,
        progress_cb: Optional[Callable[[int, int, str, int], None]] = None,
        max_workers: int = 6,
    ) -> List[Chapter]:
        """Download full book from a source, split by chapters, and persist locally."""
        rule = self.get_rule_by_name(source_book.source_name)
        if not rule:
            raise RuntimeError(f"未找到书源规则: {source_book.source_name}")

        chapters = self.fetch_toc(rule, source_book.book_url)
        if not chapters:
            raise RuntimeError(f"书源 [{source_book.source_name}] 未解析到章节目录")

        # 换源或重新下载时清空旧章节缓存，避免残留混杂
        storage.clear_book_cache(book.book_id)

        book.chapter_total = len(chapters)
        book.source_name = source_book.source_name
        book.source_url = source_book.book_url
        if not book.author and source_book.author:
            book.author = source_book.author
        if not book.abstract and source_book.intro:
            book.abstract = source_book.intro

        storage.save_chapters_meta(book.book_id, chapters)
        storage.add_to_shelf(book)

        total = len(chapters)
        done = 0
        failed = 0

        def _download_one(ch: Chapter) -> Tuple[Chapter, str, str]:
            title, content = self.fetch_chapter_content(rule, ch.source_url)
            return ch, (title or ch.title), content

        with ThreadPoolExecutor(max_workers=min(max_workers, max(1, total))) as pool:
            futures = {pool.submit(_download_one, ch): ch for ch in chapters}
            for fut in as_completed(futures):
                ch = futures[fut]
                done += 1
                try:
                    _, ch_title, content = fut.result()
                    if content.strip():
                        storage.save_chapter_cache(book.book_id, ch.item_id, ch_title, content)
                    else:
                        failed += 1
                except Exception:
                    failed += 1
                if progress_cb and (done % 5 == 0 or done == total):
                    progress_cb(done, total, ch.title, failed)

        return chapters
