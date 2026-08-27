"""Bounded loopback-only adapter for a separately hosted SearXNG service."""

from collections.abc import Callable, Mapping
from enum import StrEnum
import html
from html.parser import HTMLParser
from ipaddress import ip_address
import json
import unicodedata
from typing import BinaryIO, Protocol, runtime_checkable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request

from personal_assistant.local_http import open_local, validate_loopback_http_url
from personal_assistant.search_policy import (
    QUALITY_DEFAULT_SOURCES,
    SEARCH_ENGINE_NAMES,
    QualitySearchPolicy,
    SearchPlan,
    SearchPolicyError,
    SearchSource,
)
from personal_assistant.search_runtime import SearchRuntimeError


MAX_SEARCH_QUERY_CHARS = 256
MAX_SEARCH_RESPONSE_BYTES = 65_536
MAX_SEARCH_RESULTS = 5
MAX_SEARCH_TITLE_CHARS = 120
MAX_SEARCH_SNIPPET_CHARS = 240
MAX_SEARCH_PUBLISHED_CHARS = 40
MAX_SEARCH_URL_CHARS = 512
MAX_SEARCH_DATA_BYTES = 1_700


class WebSearchFailureCode(StrEnum):
    START = "WEB-START-01"
    CONNECT = "WEB-CONNECT-01"
    RESPONSE = "WEB-RESPONSE-01"
    PROVIDER = "WEB-PROVIDER-01"


class WebSearchError(RuntimeError):
    """A fixed safe failure at the read-only search boundary."""

    def __init__(self, message: str, code: WebSearchFailureCode) -> None:
        super().__init__(message)
        self.code = code


@runtime_checkable
class WebSearchProvider(Protocol):
    """Narrow replaceable behavior exposed to the registered search tool."""

    def search(self, query: str) -> Mapping[str, object]:
        """Return bounded untrusted public results for one validated query."""


@runtime_checkable
class SearchLifecycle(Protocol):
    """App-owned service lifecycle used around a bounded provider request."""

    def run_while_active(
        self,
        operation: Callable[[], Mapping[str, object]],
    ) -> Mapping[str, object]:
        """Run an operation while preventing idle service shutdown."""

    def close(self) -> None:
        """Release the app-owned search runtime."""


SearchOpener = Callable[[Request, float], BinaryIO]


class _PlainTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


class SearXNGSearchProvider:
    """Read JSON results from one fixed numeric-loopback SearXNG endpoint."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8888",
        *,
        timeout_seconds: float = 5.0,
        opener: SearchOpener = open_local,
        lifecycle: SearchLifecycle | None = None,
        enabled_sources: tuple[SearchSource, ...] = QUALITY_DEFAULT_SOURCES,
    ) -> None:
        self._base_url = validate_loopback_http_url(base_url, base_url=True)
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not 0.1 <= float(timeout_seconds) <= 5.0
        ):
            raise ValueError("The search timeout is outside its safe range.")
        if not callable(opener):
            raise TypeError("The search adapter requires a local opener.")
        if lifecycle is not None and not isinstance(lifecycle, SearchLifecycle):
            raise TypeError("The search adapter requires a managed lifecycle.")
        self._timeout_seconds = float(timeout_seconds)
        self._opener = opener
        self._lifecycle = lifecycle
        self._policy = QualitySearchPolicy(enabled_sources)

    @property
    def base_url(self) -> str:
        return self._base_url

    def search(self, query: str) -> Mapping[str, object]:
        query = validate_search_query(query)
        try:
            plan = self._policy.plan_for(query)
            operation = lambda: self._search_plan(query, plan)
            if self._lifecycle is not None:
                return self._lifecycle.run_while_active(operation)
            return operation()
        except SearchPolicyError as error:
            raise WebSearchError(
                str(error),
                WebSearchFailureCode.PROVIDER,
            ) from error
        except SearchRuntimeError as error:
            raise WebSearchError(
                "The local search service could not start.",
                WebSearchFailureCode.START,
            ) from error

    @property
    def enabled_sources(self) -> tuple[SearchSource, ...]:
        return self._policy.enabled_sources

    def configure_sources(self, sources: tuple[SearchSource, ...]) -> None:
        self._policy.configure(sources)

    def close(self) -> None:
        if self._lifecycle is not None:
            self._lifecycle.close()

    def _search_plan(self, query: str, plan: SearchPlan) -> Mapping[str, object]:
        regular = tuple(
            source
            for source in plan.sources
            if source is not SearchSource.ENCYCLOPEDIA_COM
        )
        documents: list[Mapping[str, object]] = []
        if regular:
            documents.append(self._search(query, regular))
        if SearchSource.ENCYCLOPEDIA_COM in plan.sources:
            site_filter = " site:encyclopedia.com"
            site_query = query[: MAX_SEARCH_QUERY_CHARS - len(site_filter)].rstrip()
            documents.append(
                self._search(
                    f"{site_query}{site_filter}",
                    (SearchSource.ENCYCLOPEDIA_COM,),
                )
            )
        results: list[object] = []
        seen: set[str] = set()
        source_values = [source.value for source in plan.sources]
        result_groups = [document["results"] for document in documents]
        result_index = 0
        while len(results) < MAX_SEARCH_RESULTS:
            added = False
            for group in result_groups:
                if result_index >= len(group):
                    continue
                item = group[result_index]
                if not isinstance(item, dict):
                    continue
                url = item.get("url")
                if not isinstance(url, str) or url in seen:
                    continue
                proposed = {
                    "provider": "searxng",
                    "results": [*results, item],
                    "sources": source_values,
                    "trust": "untrusted_web_search_results",
                }
                if len(_compact_json(proposed)) > MAX_SEARCH_DATA_BYTES:
                    continue
                seen.add(url)
                results.append(item)
                added = True
                if len(results) >= MAX_SEARCH_RESULTS:
                    break
            result_index += 1
            if not added and all(result_index >= len(group) for group in result_groups):
                break
        return {
            "provider": "searxng",
            "results": results,
            "sources": source_values,
            "trust": "untrusted_web_search_results",
        }

    def _search(
        self,
        query: str,
        sources: tuple[SearchSource, ...],
    ) -> Mapping[str, object]:
        form = urlencode(
            {
                "categories": "general",
                "engines": ",".join(SEARCH_ENGINE_NAMES[source] for source in sources),
                "format": "json",
                "language": "en",
                "pageno": "1",
                "q": query,
                "safesearch": "1",
            }
        ).encode("utf-8")
        request = Request(
            f"{self._base_url}/search",
            data=form,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "PersonalAssistant/0.1 local-search-adapter",
            },
            method="POST",
        )
        try:
            with self._opener(request, self._timeout_seconds) as response:
                status = getattr(response, "status", None)
                if status != 200:
                    raise WebSearchError(
                        "The local search service rejected the request.",
                        WebSearchFailureCode.RESPONSE,
                    )
                headers = getattr(response, "headers", None)
                content_type = (
                    headers.get_content_type()
                    if headers is not None and hasattr(headers, "get_content_type")
                    else ""
                )
                if content_type != "application/json":
                    raise WebSearchError(
                        "The local search service response is invalid.",
                        WebSearchFailureCode.RESPONSE,
                    )
                raw = response.read(MAX_SEARCH_RESPONSE_BYTES + 1)
        except WebSearchError:
            raise
        except (HTTPError, URLError, OSError, TimeoutError) as error:
            raise WebSearchError(
                "The local search service is unavailable.",
                WebSearchFailureCode.CONNECT,
            ) from error
        if not isinstance(raw, bytes) or len(raw) > MAX_SEARCH_RESPONSE_BYTES:
            raise WebSearchError(
                "The local search service response is invalid.",
                WebSearchFailureCode.RESPONSE,
            )
        try:
            document = json.loads(raw)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise WebSearchError(
                "The local search service response is invalid.",
                WebSearchFailureCode.RESPONSE,
            ) from error
        return _validated_search_document(document)


def validate_search_query(value: object) -> str:
    """Normalize one outbound query while rejecting hidden control channels."""

    if not isinstance(value, str):
        raise ValueError("A search query must be text.")
    normalized = " ".join(unicodedata.normalize("NFKC", value).split())
    if not 2 <= len(normalized) <= MAX_SEARCH_QUERY_CHARS:
        raise ValueError("The search query is outside its safe length.")
    if any(unicodedata.category(character).startswith("C") for character in value):
        raise ValueError("The search query contains hidden control characters.")
    return normalized


def query_is_derived_from_user_text(query: str, user_text: str) -> bool:
    """Require the complete normalized query to occur in the current message."""

    if not isinstance(user_text, str):
        return False
    try:
        normalized_query = validate_search_query(query).casefold()
    except ValueError:
        return False
    normalized_user = " ".join(
        unicodedata.normalize("NFKC", user_text).casefold().split()
    )
    return normalized_query in normalized_user


def _validated_search_document(value: object) -> Mapping[str, object]:
    if not isinstance(value, dict) or not isinstance(value.get("results"), list):
        raise WebSearchError(
            "The local search service response is invalid.",
            WebSearchFailureCode.RESPONSE,
        )
    results: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for item in value["results"]:
        if len(results) >= MAX_SEARCH_RESULTS:
            break
        if not isinstance(item, dict):
            continue
        title = _plain_text(item.get("title"), MAX_SEARCH_TITLE_CHARS)
        snippet = _plain_text(item.get("content"), MAX_SEARCH_SNIPPET_CHARS)
        source_url = _public_result_url(item.get("url"))
        if not title or source_url is None or source_url in seen_urls:
            continue
        candidate = {
            "snippet": snippet,
            "title": title,
            "url": source_url,
        }
        published = _plain_text(
            item.get("publishedDate", item.get("published_date")),
            MAX_SEARCH_PUBLISHED_CHARS,
        )
        if published:
            candidate["published"] = published
        proposed = {
            "provider": "searxng",
            "results": [*results, candidate],
            "trust": "untrusted_web_search_results",
        }
        encoded = _compact_json(proposed)
        if len(encoded) > MAX_SEARCH_DATA_BYTES:
            break
        seen_urls.add(source_url)
        results.append(candidate)
    return {
        "provider": "searxng",
        "results": results,
        "trust": "untrusted_web_search_results",
    }


def _compact_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _plain_text(value: object, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    parser = _PlainTextParser()
    try:
        parser.feed(value)
        parser.close()
    except Exception:
        return ""
    text = html.unescape(" ".join(parser.parts))
    text = "".join(
        character
        for character in text
        if not unicodedata.category(character).startswith("C")
    ).strip()
    text = " ".join(text.split())
    return text[:limit]


def _public_result_url(value: object) -> str | None:
    if not isinstance(value, str) or not value or len(value) > MAX_SEARCH_URL_CHARS:
        return None
    if any(unicodedata.category(character).startswith("C") for character in value):
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
    ):
        return None
    try:
        hostname = parsed.hostname.encode("idna").decode("ascii").casefold()
    except UnicodeError:
        return None
    if not hostname or "." not in hostname or hostname.startswith("."):
        return None
    try:
        address = ip_address(hostname)
    except ValueError:
        pass
    else:
        if not address.is_global:
            return None
    netloc = hostname if port is None else f"{hostname}:{port}"
    normalized = urlunsplit(("https", netloc, parsed.path or "/", parsed.query, ""))
    return normalized if len(normalized) <= MAX_SEARCH_URL_CHARS else None


def validate_public_https_url(value: object) -> str:
    """Return one normalized public HTTPS URL or reject it."""

    normalized = _public_result_url(value)
    if normalized is None:
        raise ValueError("A public HTTPS URL is required.")
    return normalized
