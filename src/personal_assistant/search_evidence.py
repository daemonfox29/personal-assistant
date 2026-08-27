"""Deterministic provenance checks for current-request search citations."""

from dataclasses import dataclass
import json
import re
from typing import Iterable
import unicodedata

from personal_assistant.web_search import validate_public_https_url


_CITATION_BOUNDARIES = frozenset(" \t\r\n)]}>,.;:'\"")
_CITATION_MARKER = re.compile(r"\[S(\d{1,3})\]", re.IGNORECASE)
_MARKDOWN_LINK_TEMPLATE = r"\[[^\]\n]{{0,200}}\]\({url}\)"
_SOURCE_LINK_TERMS = re.compile(
    r"\b(links?|urls?|web addresses?)\b",
    re.IGNORECASE,
)
_LABEL_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_MARKDOWN_LABEL_CHARS = str.maketrans(
    {character: " " for character in "\\`*_{}[]<>#~|"}
)


@dataclass(frozen=True)
class EvidenceSource:
    citation_id: str
    label: str
    url: str


def requests_source_links(user_text: str) -> bool:
    """Return whether the owner asked to see source URLs, not only labels."""

    return isinstance(user_text, str) and bool(_SOURCE_LINK_TERMS.search(user_text))


def evidence_sources_from_tool_content(content: str) -> tuple[EvidenceSource, ...]:
    """Extract a bounded code-owned source catalog from one tool envelope."""

    if not isinstance(content, str):
        return ()
    try:
        document = json.loads(content)
    except json.JSONDecodeError:
        return ()
    if not isinstance(document, dict) or document.get("ok") is not True:
        return ()
    data = document.get("data")
    if not isinstance(data, dict):
        return ()
    sources: list[EvidenceSource] = []
    for key in ("results", "pages"):
        items = data.get(key)
        if not isinstance(items, list):
            continue
        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                continue
            try:
                url = validate_public_https_url(item.get("url"))
            except ValueError:
                continue
            if any(source.url == url for source in sources):
                continue
            citation_id = item.get("citation_id", f"S{index}")
            if citation_id != f"S{index}" or index > 5:
                continue
            label = _source_label(item.get("title"), url)
            sources.append(EvidenceSource(citation_id, label, url))
    return tuple(sources)


def evidence_urls_from_tool_content(content: str) -> tuple[str, ...]:
    """Extract only normalized URLs from one successful bounded tool envelope."""

    if not isinstance(content, str):
        return ()
    try:
        document = json.loads(content)
    except json.JSONDecodeError:
        return ()
    if not isinstance(document, dict) or document.get("ok") is not True:
        return ()
    data = document.get("data")
    if not isinstance(data, dict):
        return ()
    values: list[object] = []
    for key in ("results", "pages"):
        items = data.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict):
                values.append(item.get("url"))
    urls: list[str] = []
    for value in values:
        try:
            url = validate_public_https_url(value)
        except ValueError:
            continue
        if url not in urls:
            urls.append(url)
    return tuple(urls)


def render_grounded_answer(
    answer: str,
    sources: Iterable[EvidenceSource],
    *,
    show_links: bool,
) -> tuple[str, str | None]:
    """Validate current citations and render trusted labels, with optional URLs."""

    if not isinstance(answer, str) or not answer.strip():
        return "", "missing_answer"
    catalog = tuple(sources)
    if not catalog:
        return answer, "missing_evidence"
    catalog_by_id = {source.citation_id.casefold(): source for source in catalog}
    if len(catalog_by_id) != len(catalog):
        return answer, "invalid_evidence_catalog"
    cited: set[str] = set()
    markers = tuple(_CITATION_MARKER.finditer(answer))
    for marker in markers:
        citation_id = f"s{int(marker.group(1))}"
        if citation_id not in catalog_by_id:
            return answer, "unknown_citation_marker"
        cited.add(citation_id)
    position = answer.find("https://")
    while position >= 0:
        matched = False
        for source in catalog:
            if not answer.startswith(source.url, position):
                continue
            boundary_position = position + len(source.url)
            if (
                boundary_position == len(answer)
                or answer[boundary_position] in _CITATION_BOUNDARIES
            ):
                cited.add(source.citation_id.casefold())
                matched = True
                break
        if not matched:
            return answer, "unknown_citation"
        position = answer.find("https://", position + 8)
    if not cited:
        return answer, "missing_citation"
    rendered = answer
    placeholders: list[tuple[str, EvidenceSource]] = []
    for index, source in enumerate(catalog, start=1):
        placeholder = f"\x00verified-source-{index}\x00"
        placeholders.append((placeholder, source))
        source_prefix = (
            rf"Source\s+{re.escape(source.citation_id)}\s*[—-]\s*"
            rf"{re.escape(source.label)}"
        )
        rendered = re.sub(
            rf"{source_prefix}(?:\s*:\s*)?(?:{re.escape(source.url)}|"
            rf"\[{re.escape(source.citation_id)}\])",
            placeholder,
            rendered,
            flags=re.IGNORECASE,
        )
        rendered = re.sub(
            _MARKDOWN_LINK_TEMPLATE.format(url=re.escape(source.url)),
            placeholder,
            rendered,
        )
        rendered = rendered.replace(source.url, placeholder)
        rendered = re.sub(
            rf"\[{re.escape(source.citation_id)}\]",
            placeholder,
            rendered,
            flags=re.IGNORECASE,
        )
    for placeholder, source in placeholders:
        rendered = rendered.replace(
            placeholder,
            _rendered_source(source, show_links=show_links),
        )
    return rendered, None


def grounded_answer_error(answer: str, allowed_urls: Iterable[str]) -> str | None:
    """Return a fixed reason when a searched answer lacks current provenance."""

    if not isinstance(answer, str) or not answer.strip():
        return "missing_answer"
    normalized_allowed: list[str] = []
    for value in allowed_urls:
        try:
            url = validate_public_https_url(value)
        except ValueError:
            continue
        if url not in normalized_allowed:
            normalized_allowed.append(url)
    allowed = tuple(normalized_allowed)
    if not allowed:
        return "missing_evidence"
    cited = tuple(url for url in allowed if url in answer)
    if not cited:
        return "missing_citation"
    position = answer.find("https://")
    while position >= 0:
        matched = False
        for url in allowed:
            if not answer.startswith(url, position):
                continue
            boundary_position = position + len(url)
            if (
                boundary_position == len(answer)
                or answer[boundary_position] in _CITATION_BOUNDARIES
            ):
                matched = True
                break
        if not matched:
            return "unknown_citation"
        position = answer.find("https://", position + 8)
    return None


def _source_label(value: object, url: str) -> str:
    if isinstance(value, str):
        normalized = " ".join(unicodedata.normalize("NFKC", value).split())
        normalized = "".join(
            character
            for character in normalized
            if not unicodedata.category(character).startswith("C")
        )
        normalized = _LABEL_URL.sub("", normalized)
        normalized = " ".join(normalized.translate(_MARKDOWN_LABEL_CHARS).split())
        if normalized:
            return normalized[:120]
    hostname = url.split("/", 3)[2]
    return hostname[:120]


def _rendered_source(source: EvidenceSource, *, show_links: bool) -> str:
    base = f"Source {source.citation_id} — {source.label}"
    if not show_links:
        return base
    return f"Source {source.citation_id} — {source.label}: {source.url}"
