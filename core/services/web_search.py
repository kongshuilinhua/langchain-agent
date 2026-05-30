from __future__ import annotations

from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from core.config import get_settings


DUCKDUCKGO_HTML_URL = "https://html.duckduckgo.com/html/"
MAX_QUERY_CHARS = 300
MAX_TOP_K = 10


class WebSearchError(ValueError):
    pass


@dataclass
class SearchItem:
    title: str
    url: str
    snippet: str = ""


def search_web(query: str, *, top_k: int | None = None, timeout_seconds: int | None = None) -> dict:
    settings = get_settings()
    if not settings.web_search_enabled:
        raise WebSearchError("web_search_disabled")
    provider = (settings.web_search_provider or "duckduckgo_html").strip()
    if provider != "duckduckgo_html":
        raise WebSearchError("unsupported_web_search_provider")

    normalized_query = _normalize_query(query)
    limit = _top_k(top_k or settings.web_search_top_k)
    timeout = _timeout(timeout_seconds or settings.web_search_timeout_seconds)
    started = time.monotonic()
    html = _fetch_duckduckgo_html(normalized_query, timeout_seconds=timeout)
    items = _parse_duckduckgo_html(html, limit=limit)
    latency_ms = int((time.monotonic() - started) * 1000)
    return {
        "query": normalized_query,
        "provider": provider,
        "items": [item.__dict__ for item in items],
        "latency_ms": latency_ms,
    }


def search_items_as_sources(items: list[dict]) -> list[dict]:
    sources = []
    for index, item in enumerate(items, start=1):
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        snippet = str(item.get("snippet") or "").strip()
        if not title and not snippet:
            continue
        sources.append(
            {
                "source_type": "web_search",
                "source_id": f"web-{index}",
                "chunk_id": f"web-search-{index}",
                "title": title or url or f"Web result {index}",
                "url": url,
                "snippet": snippet,
                "retrieval_channel": "web_search",
                "score": None,
            }
        )
    return sources


def _fetch_duckduckgo_html(query: str, *, timeout_seconds: int) -> str:
    settings = get_settings()
    url = f"{DUCKDUCKGO_HTML_URL}?{urllib.parse.urlencode({'q': query})}"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": settings.web_search_user_agent,
            "Accept": "text/html,application/xhtml+xml",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read(int(settings.web_search_max_response_bytes) + 1)
            if len(raw) > int(settings.web_search_max_response_bytes):
                raise WebSearchError("web_search_response_too_large")
            content_type = response.headers.get("Content-Type", "")
            charset = "utf-8"
            match = re.search(r"charset=([A-Za-z0-9._-]+)", content_type)
            if match:
                charset = match.group(1)
            return raw.decode(charset, errors="replace")
    except WebSearchError:
        raise
    except urllib.error.HTTPError as exc:
        raise WebSearchError(f"web_search_http_{exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise WebSearchError("web_search_unavailable") from exc


def _parse_duckduckgo_html(html: str, *, limit: int) -> list[SearchItem]:
    parser = _DuckDuckGoHTMLParser()
    parser.feed(html)
    parser.close()
    items = []
    seen_urls: set[str] = set()
    for item in parser.items:
        title = _clean_text(item.title)
        url = _clean_url(item.url)
        snippet = _clean_text(item.snippet)
        if not title or not url or url in seen_urls:
            continue
        seen_urls.add(url)
        items.append(SearchItem(title=title, url=url, snippet=snippet))
        if len(items) >= limit:
            break
    return items


class _DuckDuckGoHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[SearchItem] = []
        self._current: SearchItem | None = None
        self._last_item: SearchItem | None = None
        self._capture: str | None = None
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key: value or "" for key, value in attrs}
        class_name = attrs_dict.get("class", "")
        if tag == "a" and "result__a" in class_name:
            self._current = SearchItem(title="", url=attrs_dict.get("href", ""), snippet="")
            self._capture = "title"
            self._buffer = []
        elif "result__snippet" in class_name and self._last_item:
            self._capture = "snippet"
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._capture == "title" and tag == "a" and self._current:
            self._current.title = "".join(self._buffer)
            self.items.append(self._current)
            self._last_item = self._current
            self._current = None
            self._capture = None
            self._buffer = []
        elif self._capture == "snippet" and tag in {"a", "div"} and self._last_item:
            self._last_item.snippet = "".join(self._buffer)
            self._capture = None
            self._buffer = []


def _normalize_query(query: str) -> str:
    normalized = " ".join(str(query or "").split())[:MAX_QUERY_CHARS].strip()
    if not normalized:
        raise WebSearchError("web_search_empty_query")
    return normalized


def _top_k(value: int) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError):
        count = 5
    return max(1, min(count, MAX_TOP_K))


def _timeout(value: int) -> int:
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        seconds = 8
    return max(1, min(seconds, 20))


def _clean_text(value: str) -> str:
    return " ".join(unescape(value or "").split())


def _clean_url(value: str) -> str:
    url = unescape(value or "").strip()
    if url.startswith("//"):
        url = f"https:{url}"
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
        redirected = query.get("uddg")
        if redirected:
            url = urllib.parse.unquote(redirected)
            parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return url
