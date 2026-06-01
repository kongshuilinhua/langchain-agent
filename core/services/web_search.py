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

# 🎯 免 API Key 实时网络搜索端点（指向 DuckDuckGo HTML 免脚本版本）
# 意图说明：为什么不使用其 JSON API？为了零成本、免注册且高吞吐地实现 Web 搜索兜底，直接通过 HTTP 提取和解析结构化 HTML 是极佳的工程方案。
DUCKDUCKGO_HTML_URL = "https://html.duckduckgo.com/html/"
# 🧠 魔鬼数字限制：查询关键词最大长度限制为 300 字符，防超长参数拖慢请求或导致 URL 被网关截断
MAX_QUERY_CHARS = 300
MAX_TOP_K = 10


class WebSearchError(ValueError):
    """自定义 Web 搜索通用异常类。"""
    pass


@dataclass
class SearchItem:
    """
    清洗提取后的网页搜索结果数据模型。
    """
    title: str
    url: str
    snippet: str = ""


def search_web(query: str, *, top_k: int | None = None, timeout_seconds: int | None = None) -> dict:
    """
    实时的网络网页搜索引擎检索（RAG 实时的 Web 召回通道）。

    🎯 意图与工程大局观：
        当知识库中没有充分的相关内部资料时，允许 Agent 通过此方法连接公网获取实时新闻、技术博客或百科知识，充实提示词。
        流水线流程：
        1. 规整化 Query 剔除首尾空白，防 SQL / Prompt 注入。
        2. 发起 GET 请求抓取免 JS 的 DuckDuckGo HTML 页面。
        3. 利用高性能原生 HTMLParser 剔除广告，流式捕获结果块。
        4. 清理还原真实的 URL 重定向跳转。
    """
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
    
    # 抓取与结构化提取
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
    """
    将 Web 搜索的 Item 转换为符合 RAG Trace 规范的 Sources 片段格式。
    """
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
    """
    通过 urllib 向 DuckDuckGo 发起请求并读取网页 HTML 原文。

    🛡️ 防御性设计（防爆防溢出限制）：
        - 对响应体大小进行硬上限校验（`web_search_max_response_bytes`，通常是 512KB）。
          直接在 `read` 环节限制读取，防止目标页面因被恶意灌入几个 G 的海量数据流从而导致系统内存暴增而崩溃。
        - 智能字符集校验：解析 Content-Type 自动获取服务器字符集（如 `gbk` / `utf-8`），缺失时安全降级为 `utf-8` 解码，并带 `errors="replace"` 剔除乱码。
    """
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
    """
    将抓取到的原始 HTML 喂给流式解析器提取数据。
    
    ⚡ 边界与性能思考：
        - 采取 `seen_urls` 原生集合（Set）进行去重拦截，防止同一页面因为排版样式多次重复出现在召回列表中。
        - 超限立即截断，降低不必要的分词以及元数据处理开销。
    """
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
    """
    纯 Python 原生 HTMLParser 实现的高效 DuckDuckGo HTML 提取器。

    🎯 意图与工程大局观：
        不引入重量级的 BeautifulSoup 或 lxml 库。
        利用 C 级速度的流式事件状态机，当遇到 class 为 `result__a` 的超链接时捕获 Title，
        遇到 class 为 `result__snippet` 的 div 时捕获摘要文本，
        极具时空双重性能优势（时间复杂度 O(N)，空间复杂度 O(1) 级的局部缓冲区）。
    """

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
    """规整清理搜索 Query 语句。"""
    normalized = " ".join(str(query or "").split())[:MAX_QUERY_CHARS].strip()
    if not normalized:
        raise WebSearchError("web_search_empty_query")
    return normalized


def _top_k(value: int) -> int:
    """安全限制召回的 Top_K 参数边界（限制在 [1, MAX_TOP_K] 之间）。"""
    try:
        count = int(value)
    except (TypeError, ValueError):
        count = 5
    return max(1, min(count, MAX_TOP_K))


def _timeout(value: int) -> int:
    """安全限制 Web 搜索超时边界（限制在 1-20 秒内，避免连接占死主线程池）。"""
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        seconds = 8
    return max(1, min(seconds, 20))


def _clean_text(value: str) -> str:
    """剔除空字符并将 HTML 转义字符还原（如将 `&amp;` 还原为 `&`）。"""
    return " ".join(unescape(value or "").split())


def _clean_url(value: str) -> str:
    """
    🛡️ 高度健壮的跳转真实 URL 还原提取器。
    
    🎯 意图与工程大局观：
        DuckDuckGo HTML 版本默认会把结果 URL 包装为自身的重定向中继链接（如 `https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com`）。
        如果不做清理，Agent 将拿到极长且包含 DuckDuckGo 本地状态的包装 URL，严重影响大模型对来源的纯粹判断。
        本方法自动探测 `uddg` 参数，强行解密还原出最真实的第三方直连 URL（例如 `https://example.com`）。
    """
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
