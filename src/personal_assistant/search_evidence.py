"""Deterministic provenance checks for current-request search citations."""

import json
from typing import Iterable

from personal_assistant.web_search import validate_public_https_url


_CITATION_BOUNDARIES = frozenset(" \t\r\n)]}>,.;:'\"")


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
