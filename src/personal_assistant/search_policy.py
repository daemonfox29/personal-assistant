"""Code-owned quality routing for the reviewed public-search sources."""

from dataclasses import dataclass
from enum import StrEnum
import re
from threading import Lock


class SearchSource(StrEnum):
    GOOGLE = "google"
    GOOGLE_SCHOLAR = "google_scholar"
    OPENALEX = "openalex"
    CROSSREF = "crossref"
    PUBMED = "pubmed"
    SEMANTIC_SCHOLAR = "semantic_scholar"
    ARXIV = "arxiv"
    WIKIPEDIA = "wikipedia"
    ENCYCLOPEDIA_COM = "encyclopedia_com"
    DUCKDUCKGO = "duckduckgo"


SEARCH_SOURCE_LABELS: dict[SearchSource, str] = {
    SearchSource.GOOGLE: "Google Web",
    SearchSource.GOOGLE_SCHOLAR: "Google Scholar",
    SearchSource.OPENALEX: "OpenAlex",
    SearchSource.CROSSREF: "Crossref",
    SearchSource.PUBMED: "PubMed",
    SearchSource.SEMANTIC_SCHOLAR: "Semantic Scholar",
    SearchSource.ARXIV: "arXiv",
    SearchSource.WIKIPEDIA: "Wikipedia",
    SearchSource.ENCYCLOPEDIA_COM: "Encyclopedia.com",
    SearchSource.DUCKDUCKGO: "DuckDuckGo",
}
SEARCH_ENGINE_NAMES: dict[SearchSource, str] = {
    SearchSource.GOOGLE: "google",
    SearchSource.GOOGLE_SCHOLAR: "google scholar",
    SearchSource.OPENALEX: "openalex",
    SearchSource.CROSSREF: "crossref",
    SearchSource.PUBMED: "pubmed",
    SearchSource.SEMANTIC_SCHOLAR: "semantic scholar",
    SearchSource.ARXIV: "arxiv",
    SearchSource.WIKIPEDIA: "wikipedia",
    SearchSource.ENCYCLOPEDIA_COM: "google",
    SearchSource.DUCKDUCKGO: "duckduckgo",
}
QUALITY_DEFAULT_SOURCES: tuple[SearchSource, ...] = (
    SearchSource.GOOGLE,
    SearchSource.GOOGLE_SCHOLAR,
    SearchSource.OPENALEX,
    SearchSource.CROSSREF,
    SearchSource.PUBMED,
    SearchSource.SEMANTIC_SCHOLAR,
    SearchSource.ARXIV,
    SearchSource.WIKIPEDIA,
    SearchSource.ENCYCLOPEDIA_COM,
)
MAX_AUTOMATIC_SEARCH_SOURCES = 3

_RESEARCH_TERMS = re.compile(
    r"\b(research|scholarly|study|studies|paper|papers|journal|journals|"
    r"peer[- ]reviewed|evidence|literature review|citation|citations)\b",
    re.IGNORECASE,
)
_HEALTH_TERMS = re.compile(
    r"\b(health|medical|medicine|clinical|disease|disorder|diagnosis|treatment|"
    r"symptom|symptoms|drug|medication|nutrition|therapy)\b",
    re.IGNORECASE,
)
_REFERENCE_TERMS = re.compile(
    r"\b(encyclopedia|wikipedia|reference overview|background on)\b",
    re.IGNORECASE,
)
_PRIVATE_CONTEXT_TERMS = re.compile(
    r"\b(my (?:health|symptoms?|diagnos(?:is|es)|medications?|condition|"
    r"history|memory|memories)|remember (?:when|what)|have i (?:ever|told)|"
    r"did i (?:ever|tell)|i told you|we (?:discussed|talked about)|"
    r"saved (?:context|memory|memories))\b",
    re.IGNORECASE,
)
_VERIFICATION_TERMS = re.compile(
    r"\b(double[- ]check|cross[- ]check|"
    r"verify (?:this|that|it|your answer|the answer|the information|the result)|"
    r"check (?:your work|the sources|the evidence|(?:this|that|it) carefully))\b",
    re.IGNORECASE,
)
_EXPLICIT_PATTERNS: tuple[tuple[SearchSource, tuple[str, ...]], ...] = (
    (SearchSource.GOOGLE_SCHOLAR, ("google scholar", "scholar")),
    (SearchSource.SEMANTIC_SCHOLAR, ("semantic scholar",)),
    (SearchSource.ENCYCLOPEDIA_COM, ("encyclopedia.com", "encyclopedia")),
    (SearchSource.DUCKDUCKGO, ("duckduckgo", "duck duck go")),
    (SearchSource.OPENALEX, ("openalex", "open alex")),
    (SearchSource.CROSSREF, ("crossref", "cross ref")),
    (SearchSource.PUBMED, ("pubmed", "pub med")),
    (SearchSource.WIKIPEDIA, ("wikipedia",)),
    (SearchSource.ARXIV, ("arxiv",)),
    (SearchSource.GOOGLE, ("google",)),
)
_PROVIDER_ALIAS_TEXT = "|".join(
    sorted(
        {
            re.escape(alias)
            for _source, aliases in _EXPLICIT_PATTERNS
            for alias in aliases
        },
        key=len,
        reverse=True,
    )
)
_LEADING_PROVIDER_COMMAND = re.compile(
    rf"^\s*(?:(?:only\s+search|search\s+only|search|check)\s+"
    rf"(?:the\s+)?(?:{_PROVIDER_ALIAS_TEXT})(?:\s+(?:web\s+)?search)?\s+for\s+|"
    rf"use\s+(?:only\s+)?(?:{_PROVIDER_ALIAS_TEXT})\s+to\s+"
    rf"(?:search\s+for|find|look\s+up)\s+)",
    re.IGNORECASE,
)
_TRAILING_PROVIDER_CLAUSE = re.compile(
    rf"\s+\b(?:on|with|using)\s+(?:{_PROVIDER_ALIAS_TEXT})\b",
    re.IGNORECASE,
)


class SearchPolicyError(RuntimeError):
    """The requested reviewed source route is unavailable."""


@dataclass(frozen=True)
class SearchPlan:
    sources: tuple[SearchSource, ...]
    explicit: bool = False


def validate_search_sources(values: object) -> tuple[SearchSource, ...]:
    if not isinstance(values, (tuple, list)) or not values:
        raise ValueError("At least one reviewed search source must be enabled.")
    try:
        sources = tuple(SearchSource(value) for value in values)
    except (TypeError, ValueError) as error:
        raise ValueError("The search-source selection is invalid.") from error
    if len(sources) != len(set(sources)):
        raise ValueError("Search sources must not be duplicated.")
    return sources


class QualitySearchPolicy:
    """Select a bounded reviewed route from owner-enabled sources only."""

    def __init__(
        self,
        enabled_sources: tuple[SearchSource, ...] = QUALITY_DEFAULT_SOURCES,
    ) -> None:
        self._lock = Lock()
        self._enabled = validate_search_sources(enabled_sources)

    @property
    def enabled_sources(self) -> tuple[SearchSource, ...]:
        with self._lock:
            return self._enabled

    def configure(self, enabled_sources: tuple[SearchSource, ...]) -> None:
        selected = validate_search_sources(enabled_sources)
        with self._lock:
            self._enabled = selected

    def plan_for(self, user_text: str) -> SearchPlan:
        if not isinstance(user_text, str):
            raise TypeError("Search routing requires the current user message.")
        enabled = self.enabled_sources
        explicit = _explicit_source(user_text)
        if explicit is not None:
            if explicit not in enabled:
                raise SearchPolicyError(
                    f"{SEARCH_SOURCE_LABELS[explicit]} is disabled in Search settings."
                )
            return SearchPlan((explicit,), explicit=True)
        if _PRIVATE_CONTEXT_TERMS.search(user_text):
            raise SearchPolicyError(
                "Personal-context queries require an explicit enabled source."
            )
        if _HEALTH_TERMS.search(user_text):
            limit = 2
            ordered = (
                SearchSource.PUBMED,
                SearchSource.GOOGLE_SCHOLAR,
                SearchSource.OPENALEX,
                SearchSource.SEMANTIC_SCHOLAR,
            )
        elif _RESEARCH_TERMS.search(user_text):
            limit = MAX_AUTOMATIC_SEARCH_SOURCES
            ordered = (
                SearchSource.GOOGLE_SCHOLAR,
                SearchSource.OPENALEX,
                SearchSource.SEMANTIC_SCHOLAR,
                SearchSource.CROSSREF,
                SearchSource.ARXIV,
                SearchSource.PUBMED,
            )
        elif _REFERENCE_TERMS.search(user_text):
            limit = 2
            ordered = (
                SearchSource.WIKIPEDIA,
                SearchSource.ENCYCLOPEDIA_COM,
                SearchSource.GOOGLE,
            )
        else:
            limit = 1
            ordered = (
                SearchSource.GOOGLE,
                SearchSource.DUCKDUCKGO,
                SearchSource.WIKIPEDIA,
            )
        selected = tuple(source for source in ordered if source in enabled)[
            :limit
        ]
        if not selected:
            selected = enabled[:1]
        return SearchPlan(selected)


def _explicit_source(user_text: str) -> SearchSource | None:
    normalized = " ".join(user_text.casefold().split())
    for source, aliases in _EXPLICIT_PATTERNS:
        for alias in aliases:
            escaped = re.escape(alias)
            patterns = (
                rf"\bonly search {escaped}\b",
                rf"\bsearch only {escaped}\b",
                rf"\bcheck {escaped} for\b",
                rf"\bcheck (?:the )?{escaped}(?: web)? search for\b",
                rf"\bsearch {escaped} for\b",
                rf"\buse only {escaped}\b",
                rf"\buse {escaped} to (?:search for|find|look up)\b",
                rf"\blook (?:this |that |it )?up (?:on|with|using) {escaped}\b",
                rf"\b(?:look up|find|search for|check)\b.{{0,192}}"
                rf"\b(?:on|with|using) {escaped}\b",
            )
            if any(re.search(pattern, normalized) for pattern in patterns):
                return source
    return None


def requests_explicit_search(user_text: str) -> bool:
    return isinstance(user_text, str) and _explicit_source(user_text) is not None


def strip_explicit_provider_language(user_text: str) -> str:
    """Remove only recognized provider commands from prior topic text."""

    if not isinstance(user_text, str):
        raise TypeError("Provider language requires user text.")
    if _explicit_source(user_text) is None:
        return user_text
    stripped = _LEADING_PROVIDER_COMMAND.sub("", user_text, count=1)
    stripped = _TRAILING_PROVIDER_CLAUSE.sub("", stripped)
    return " ".join(stripped.split())


def requests_quality_search(user_text: str) -> bool:
    """Identify clear research/reference requests worth deterministic prefetch."""

    if not isinstance(user_text, str):
        return False
    if requests_explicit_search(user_text):
        return True
    if _PRIVATE_CONTEXT_TERMS.search(user_text):
        return False
    return bool(
        _HEALTH_TERMS.search(user_text)
        or _RESEARCH_TERMS.search(user_text)
        or _REFERENCE_TERMS.search(user_text)
    )


def requests_search_verification(user_text: str) -> bool:
    """Return whether the owner explicitly requested a second evidence pass."""

    return isinstance(user_text, str) and bool(_VERIFICATION_TERMS.search(user_text))
