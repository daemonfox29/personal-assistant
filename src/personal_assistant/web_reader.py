"""Bounded reader for public HTTPS pages selected from current search results."""

from collections import OrderedDict
from collections.abc import Callable, Mapping
from html.parser import HTMLParser
from http.client import HTTPSConnection, HTTPResponse
from ipaddress import ip_address
import json
import socket
import ssl
from queue import Empty, Queue
from threading import BoundedSemaphore, Lock, Thread
import unicodedata
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from personal_assistant.web_search import validate_public_https_url


MAX_READ_PAGES = 3
MAX_PAGE_RESPONSE_BYTES = 524_288
MAX_PAGE_TEXT_CHARS = 1_800
MAX_PAGE_TITLE_CHARS = 120
MAX_PAGE_READING_DATA_BYTES = 7_000
MAX_READING_SESSIONS = 8
MAX_DNS_RESOLVERS = 4
ALLOWED_PAGE_CONTENT_TYPES = frozenset(
    {"application/xhtml+xml", "text/html", "text/plain"}
)


class WebPageReadError(RuntimeError):
    """A selected public page could not be read inside the fixed boundary."""


_DNS_RESOLVER_SLOTS = BoundedSemaphore(MAX_DNS_RESOLVERS)


class _ArticleTextParser(HTMLParser):
    _IGNORED = frozenset({"script", "style", "noscript", "svg", "template"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self._ignored_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, _attrs) -> None:
        normalized = tag.casefold()
        if normalized in self._IGNORED:
            self._ignored_depth += 1
        if normalized == "title" and self._ignored_depth == 0:
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.casefold()
        if normalized == "title":
            self._in_title = False
        if normalized in self._IGNORED and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        if self._in_title:
            self.title_parts.append(data)
        else:
            self.parts.append(data)


class _PinnedHTTPSConnection(HTTPSConnection):
    """Validate TLS for the hostname while connecting to one reviewed DNS result."""

    def __init__(
        self,
        hostname: str,
        address: str,
        *,
        timeout: float,
        context: ssl.SSLContext,
    ) -> None:
        super().__init__(hostname, 443, timeout=timeout, context=context)
        self._pinned_address = address

    def connect(self) -> None:
        raw_socket = socket.create_connection(
            (self._pinned_address, self.port),
            timeout=self.timeout,
        )
        try:
            self.sock = self._context.wrap_socket(
                raw_socket,
                server_hostname=self.host,
            )
        except Exception:
            raw_socket.close()
            raise


PageFetcher = Callable[[str, float], tuple[str, str, bytes]]


def _public_addresses(
    hostname: str,
    timeout_seconds: float = 2.0,
) -> tuple[str, ...]:
    if not _DNS_RESOLVER_SLOTS.acquire(blocking=False):
        raise WebPageReadError("Public address resolution is at capacity.")
    result: Queue[tuple[list[tuple] | None, OSError | None]] = Queue(maxsize=1)

    def resolve() -> None:
        try:
            answers = socket.getaddrinfo(
                hostname,
                443,
                family=socket.AF_UNSPEC,
                type=socket.SOCK_STREAM,
            )
            result.put((answers, None))
        except OSError as error:
            result.put((None, error))
        finally:
            _DNS_RESOLVER_SLOTS.release()

    Thread(target=resolve, name="public-page-dns", daemon=True).start()
    try:
        answers, resolution_error = result.get(timeout=timeout_seconds)
    except Empty as error:
        raise WebPageReadError("The public page address resolution timed out.") from error
    if resolution_error is not None or answers is None:
        raise WebPageReadError(
            "The public page address could not be resolved."
        ) from resolution_error
    addresses: list[str] = []
    for answer in answers[:16]:
        address = answer[4][0]
        try:
            parsed = ip_address(address)
        except ValueError as error:
            raise WebPageReadError("The public page address is invalid.") from error
        if not parsed.is_global:
            raise WebPageReadError("The public page resolved outside the public web.")
        normalized = parsed.compressed
        if normalized not in addresses:
            addresses.append(normalized)
    if not addresses:
        raise WebPageReadError("The public page address could not be resolved.")
    return tuple(addresses)


def _fetch_public_https(url: str, timeout_seconds: float) -> tuple[str, str, bytes]:
    approved_url = validate_public_https_url(url)
    parsed = urlsplit(approved_url)
    hostname = parsed.hostname
    if hostname is None:
        raise WebPageReadError("The public page URL is invalid.")
    addresses = _public_addresses(hostname, min(2.0, timeout_seconds))
    context = ssl.create_default_context()
    context.set_alpn_protocols(["http/1.1"])
    target = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    connection = _PinnedHTTPSConnection(
        hostname,
        addresses[0],
        timeout=timeout_seconds,
        context=context,
    )
    try:
        connection.request(
            "GET",
            target,
            headers={
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8",
                "Accept-Encoding": "identity",
                "Connection": "close",
                "User-Agent": "PersonalAssistant/0.1 bounded-page-reader",
            },
        )
        response: HTTPResponse = connection.getresponse()
        if response.status != 200:
            raise WebPageReadError("The public page returned an unusable status.")
        content_type = response.headers.get_content_type()
        if content_type not in ALLOWED_PAGE_CONTENT_TYPES:
            raise WebPageReadError("The public page is not supported text.")
        content_encoding = response.headers.get("Content-Encoding", "identity")
        if content_encoding.casefold() not in {"", "identity"}:
            raise WebPageReadError("The public page encoding is unsupported.")
        raw = response.read(MAX_PAGE_RESPONSE_BYTES)
        charset = response.headers.get_content_charset() or "utf-8"
        return content_type, charset, raw
    except WebPageReadError:
        raise
    except (OSError, ssl.SSLError, TimeoutError) as error:
        raise WebPageReadError("The public page could not be read.") from error
    finally:
        connection.close()


def _clean_text(value: str, limit: int) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    visible = "".join(
        character
        for character in normalized
        if not unicodedata.category(character).startswith("C")
    )
    return " ".join(visible.split())[:limit]


class PublicWebPageReader:
    """Fetch and extract bounded inert text from one approved public HTTPS URL."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 6.0,
        fetcher: PageFetcher = _fetch_public_https,
    ) -> None:
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not 0.5 <= float(timeout_seconds) <= 10.0
        ):
            raise ValueError("The page-read timeout is outside its safe range.")
        if not callable(fetcher):
            raise TypeError("The page reader requires a fixed fetcher.")
        self._timeout_seconds = float(timeout_seconds)
        self._fetcher = fetcher

    def read(self, url: str) -> Mapping[str, str]:
        approved_url = validate_public_https_url(url)
        content_type, charset, raw = self._fetcher(
            approved_url,
            self._timeout_seconds,
        )
        try:
            decoded = raw.decode(charset, errors="replace")
        except LookupError as error:
            raise WebPageReadError("The public page charset is unsupported.") from error
        if content_type == "text/plain":
            title = ""
            text = _clean_text(decoded, MAX_PAGE_TEXT_CHARS)
        else:
            parser = _ArticleTextParser()
            try:
                parser.feed(decoded)
                parser.close()
            except Exception as error:
                raise WebPageReadError("The public page markup is invalid.") from error
            title = _clean_text(" ".join(parser.title_parts), MAX_PAGE_TITLE_CHARS)
            text = _clean_text(" ".join(parser.parts), MAX_PAGE_TEXT_CHARS)
        if not text:
            raise WebPageReadError("The public page contained no usable text.")
        return {"text": text, "title": title, "url": approved_url}


class SearchReadingSession:
    """Bind page selections to URLs from one current correlated search request."""

    def __init__(self, reader: PublicWebPageReader) -> None:
        if not isinstance(reader, PublicWebPageReader):
            raise TypeError("Search reading requires the bounded page reader.")
        self._reader = reader
        self._lock = Lock()
        self._urls: OrderedDict[UUID, tuple[str, ...]] = OrderedDict()

    def remember(self, request_id: UUID, search_result: Mapping[str, object]) -> None:
        if not isinstance(request_id, UUID):
            raise TypeError("Search reading requires a request ID.")
        raw_results = search_result.get("results")
        if not isinstance(raw_results, list):
            raise WebPageReadError("Search results could not be bound safely.")
        urls: list[str] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            try:
                url = validate_public_https_url(item.get("url"))
            except ValueError:
                continue
            if url not in urls:
                urls.append(url)
        with self._lock:
            self._urls[request_id] = tuple(urls)
            self._urls.move_to_end(request_id)
            while len(self._urls) > MAX_READING_SESSIONS:
                self._urls.popitem(last=False)

    def read(self, request_id: UUID, result_numbers: tuple[int, ...]) -> Mapping[str, object]:
        if not isinstance(request_id, UUID):
            raise TypeError("Search reading requires a request ID.")
        if (
            not isinstance(result_numbers, tuple)
            or not result_numbers
            or len(result_numbers) > MAX_READ_PAGES
        ):
            raise WebPageReadError("Page selections are invalid.")
        with self._lock:
            urls = self._urls.pop(request_id, None)
        if urls is None:
            raise WebPageReadError("No current search results are available.")
        selected: list[str] = []
        for number in result_numbers:
            if isinstance(number, bool) or not isinstance(number, int):
                raise WebPageReadError("Page selections are invalid.")
            if number < 1:
                raise WebPageReadError("Page selection is outside current results.")
            if number > len(urls):
                continue
            url = urls[number - 1]
            if url not in selected:
                selected.append(url)
        if not selected:
            raise WebPageReadError("Page selection is outside current results.")
        pages: list[Mapping[str, str]] = []
        for url in selected:
            try:
                page = dict(self._reader.read(url))
            except WebPageReadError:
                continue
            while page["text"]:
                proposed = {
                    "pages": [*pages, page],
                    "trust": "untrusted_public_page_text",
                }
                encoded = json.dumps(
                    proposed,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
                if len(encoded) <= MAX_PAGE_READING_DATA_BYTES:
                    pages.append(page)
                    break
                page["text"] = page["text"][:-200]
        if not pages:
            raise WebPageReadError("Selected public pages could not be read.")
        return {
            "pages": pages,
            "trust": "untrusted_public_page_text",
        }
