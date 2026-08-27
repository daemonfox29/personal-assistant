"""Bounded, user-authored context resolution for conversational web queries."""

from dataclasses import dataclass
import re
import unicodedata

from personal_assistant.search_policy import strip_explicit_provider_language


MAX_RESOLVED_TOPIC_CHARS = 80

_REFERENCE = re.compile(
    r"\b(?:it|its|he|him|his|she|her|hers|they|them|their|theirs|"
    r"this|that|these|those|former|latter)\b",
    re.IGNORECASE,
)
_ELLIPTICAL_PREFIX = re.compile(r"^\s*(?:and\s+)?what about\b", re.IGNORECASE)
_DEICTIC_REFERENCE = re.compile(
    r"\b(?:the|these|those)\s+(?:[a-z]+\s+){0,3}(?:itself|themselves)\b",
    re.IGNORECASE,
)
_TOPIC_PATTERNS = (
    re.compile(
        r"\b(?:tell me|information|info|details?|background)\s+about\s+(.+)",
        re.I,
    ),
    re.compile(r"\b(?:about|on|regarding|concerning)\s+(.+)", re.I),
    re.compile(r"\b(?:who|what)\s+(?:is|was|are|were)\s+(.+)", re.I),
    re.compile(
        r"\b(?:explain|describe|summarize|research|find|look up|search for)\s+(.+)",
        re.I,
    ),
)
_CAPITALIZED_TOPIC = re.compile(
    r"\b[A-Z][A-Za-z'’-]{1,40}(?:\s+[A-Z][A-Za-z'’-]{1,40}){1,4}\b"
)
_SINGLE_CAPITALIZED_TOPIC = re.compile(r"\b[A-Z][A-Za-z'’-]{2,40}\b")
_CAPITALIZED_NON_TOPICS = frozenset(
    {
        "And",
        "Can",
        "Compare",
        "Find",
        "Give",
        "How",
        "Look",
        "Search",
        "Tell",
        "What",
        "When",
        "Where",
        "Which",
        "Who",
        "Why",
    }
)
_TRAILING_REQUEST = re.compile(
    r"\s*(?:,|\band\b|\bbut\b|\bthen\b)\s+"
    r"(?:tell|give|explain|summarize|put|compare|find|look|search|show)\b.*$",
    re.IGNORECASE,
)
_UNSAFE_TOPIC = re.compile(
    r"\b(?:my|mine|our|ours|password|passcode|passphrase|"
    r"security answer|api[-_ ]?key|access token|refresh token|private key|"
    r"secret key|seed phrase|recovery phrase|wallet seed|pin|cvv|cvc)\b",
    re.IGNORECASE,
)
_PERSONAL_SOURCE = re.compile(
    r"\b(?:my|mine|our|ours)\b|"
    r"\b(?:i|we)\s+(?:am|are|have|had|live|work|was|were|take|use|own|"
    r"know|feel|think|want|need)\b",
    re.IGNORECASE,
)
_URL_OR_EMAIL = re.compile(r"(?:https?://|www\.|\b\S+@\S+\b)", re.IGNORECASE)
_LONG_NUMBER = re.compile(r"\d{6,}")
_ONLY_GENERIC = re.compile(
    r"^(?:the|a|an|this|that|it|he|him|his|she|her|they|them|their|"
    r"topic|subject|person|thing)+$",
    re.IGNORECASE,
)
_ACKNOWLEDGEMENT = re.compile(
    r"^(?:thanks?|thank you|okay|ok|got it|yes|no|sure|sounds good)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SearchQueryResolution:
    query: str | None
    used_prior_user_context: bool = False


def resolve_search_query(
    current_user_text: str,
    prior_user_texts: tuple[str, ...],
) -> SearchQueryResolution:
    """Resolve simple follow-up references using only recent user-authored text."""

    if not isinstance(current_user_text, str) or not isinstance(
        prior_user_texts, tuple
    ):
        raise TypeError("Search context requires current and prior user text.")
    if not all(isinstance(value, str) for value in prior_user_texts):
        raise TypeError("Prior search context must contain only user text.")
    normalized_current = _normalize(current_user_text)
    if not normalized_current:
        return SearchQueryResolution(None)
    referential = bool(
        _REFERENCE.search(normalized_current)
        or _ELLIPTICAL_PREFIX.search(normalized_current)
        or _DEICTIC_REFERENCE.search(normalized_current)
    )
    if not referential:
        return SearchQueryResolution(normalized_current)
    if (
        _DEICTIC_REFERENCE.search(normalized_current) is None
        and _current_has_explicit_topic(normalized_current)
    ):
        return SearchQueryResolution(normalized_current)
    topic = next(
        (
            candidate
            for prior in reversed(prior_user_texts[-3:])
            if (candidate := _extract_safe_topic(prior)) is not None
        ),
        None,
    )
    if topic is None:
        return SearchQueryResolution(None)
    if _ELLIPTICAL_PREFIX.search(normalized_current):
        remainder = _ELLIPTICAL_PREFIX.sub("", normalized_current).strip(" ?.,")
        if _REFERENCE.search(remainder):
            resolved = _REFERENCE.sub(topic, remainder)
        else:
            resolved = f"{remainder} {topic}" if remainder else topic
    elif _REFERENCE.search(normalized_current):
        resolved = _REFERENCE.sub(topic, normalized_current)
    else:
        resolved = f"{normalized_current} {topic}"
    resolved = _normalize(resolved)
    if not resolved or len(resolved) > 256:
        return SearchQueryResolution(None)
    return SearchQueryResolution(resolved, used_prior_user_context=True)


def _extract_safe_topic(
    user_text: str,
    *,
    include_whole: bool = True,
) -> str | None:
    normalized = _normalize(strip_explicit_provider_language(user_text))
    if (
        not normalized
        or _PERSONAL_SOURCE.search(normalized)
        or _UNSAFE_TOPIC.search(normalized)
        or _URL_OR_EMAIL.search(normalized)
        or _LONG_NUMBER.search(normalized)
    ):
        return None
    candidates: list[str] = []
    for pattern in _TOPIC_PATTERNS:
        match = pattern.search(normalized)
        if match is not None:
            candidates.append(match.group(1))
    candidates.extend(
        match.group(0) for match in _CAPITALIZED_TOPIC.finditer(normalized)
    )
    if include_whole and len(normalized) <= MAX_RESOLVED_TOPIC_CHARS:
        candidates.append(normalized)
    for candidate in candidates:
        safe = _validated_topic(candidate)
        if safe is not None:
            return safe
    return None


def _current_has_explicit_topic(current_user_text: str) -> bool:
    for pattern in _TOPIC_PATTERNS:
        match = pattern.search(current_user_text)
        if match is not None and _REFERENCE.search(match.group(1)) is None:
            if _validated_topic(match.group(1)) is not None:
                return True
    for match in _SINGLE_CAPITALIZED_TOPIC.finditer(current_user_text):
        if match.start() == 0 or match.group(0) in _CAPITALIZED_NON_TOPICS:
            continue
        if _validated_topic(match.group(0)) is not None:
            return True
    return False


def _validated_topic(candidate: str) -> str | None:
    candidate = _TRAILING_REQUEST.sub("", candidate)
    candidate = candidate.strip(" \t\r\n?!.,:;()[]{}\"'")
    candidate = re.sub(r"^(?:the|a|an)\s+", "", candidate, flags=re.IGNORECASE)
    candidate = _normalize(candidate)
    if (
        not candidate
        or len(candidate) > MAX_RESOLVED_TOPIC_CHARS
        or _UNSAFE_TOPIC.search(candidate)
        or _URL_OR_EMAIL.search(candidate)
        or _LONG_NUMBER.search(candidate)
        or _REFERENCE.search(candidate)
        or _ONLY_GENERIC.fullmatch(candidate.replace(" ", ""))
        or _ACKNOWLEDGEMENT.fullmatch(candidate)
        or not any(character.isalpha() for character in candidate)
    ):
        return None
    return candidate


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = "".join(
        character
        for character in normalized
        if not unicodedata.category(character).startswith("C")
        or character in "\t\n\r"
    )
    return " ".join(normalized.split())
