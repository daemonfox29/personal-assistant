"""Deterministic named-context recognition without model inference."""

from dataclasses import dataclass
import re
import unicodedata

from personal_assistant.memory_types import (
    MemoryValidationError,
    PreferencePayload,
    ScopeType,
)


MAX_SCOPE_LABEL_CHARS = 64
MAX_NAMED_SCOPES = 1_000
MAX_MATCHED_SCOPES = 8
_LABEL = r"[\w'’-]+(?:\s+[\w'’-]+){0,4}"
_SCOPE_PATTERNS = (
    (
        ScopeType.PROJECT,
        re.compile(
            rf"^\s*for\s+(?:my\s+)?project\s+(?P<label>{_LABEL})\s*,",
            re.IGNORECASE,
        ),
        "",
    ),
    (
        ScopeType.PROJECT,
        re.compile(
            rf"^\s*(?:when|while)\s+working\s+on\s+(?P<label>{_LABEL})\s*,",
            re.IGNORECASE,
        ),
        "",
    ),
    (
        ScopeType.TOPIC,
        re.compile(
            rf"^\s*(?:when|while)\s+(?:discussing|talking\s+about)\s+"
            rf"(?P<label>{_LABEL})\s*,",
            re.IGNORECASE,
        ),
        "",
    ),
    (
        ScopeType.TOPIC,
        re.compile(
            rf"^\s*in\s+(?:the\s+)?context\s+of\s+(?P<label>{_LABEL})\s*,",
            re.IGNORECASE,
        ),
        "",
    ),
    (
        ScopeType.PLACE,
        re.compile(
            rf"^\s*(?:at|while\s+at)\s+(?:my\s+|the\s+)?"
            rf"(?P<label>{_LABEL})\s*,",
            re.IGNORECASE,
        ),
        "",
    ),
)
_QUERY_WORD = re.compile(r"[^\w'’-]+", re.UNICODE)
_CONTEXT_SIGNAL = re.compile(
    r"\b(?:at\s+(?:work|home|school)|for\s+(?:my\s+)?project\b|"
    r"when\s+(?:discussing|talking\s+about|working\s+on)\b|"
    r"in\s+(?:the\s+)?context\s+of\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DetectedNamedScope:
    scope_type: ScopeType
    display_label: str


def detect_explicit_named_scope(text: str) -> DetectedNamedScope | None:
    """Recognize only explicit leading context phrases with a comma boundary."""

    if not isinstance(text, str):
        return None
    for scope_type, pattern, prefix in _SCOPE_PATTERNS:
        match = pattern.search(text)
        if match is None:
            continue
        label = f"{prefix}{match.group('label')}"
        try:
            return DetectedNamedScope(scope_type, validate_scope_label(label))
        except MemoryValidationError:
            return None
    return None


def named_scope_needs_clarification(text: str) -> bool:
    """Flag context-bearing wording that is not explicit enough to scope."""

    return bool(
        isinstance(text, str)
        and _CONTEXT_SIGNAL.search(text)
        and detect_explicit_named_scope(text) is None
    )


def validate_scope_label(value: str) -> str:
    """Validate a short owner-visible label using existing secret controls."""

    if not isinstance(value, str):
        raise MemoryValidationError("Memory scope label must be text.")
    label = " ".join(value.split()).strip(" ,")
    if not label or len(label) > MAX_SCOPE_LABEL_CHARS:
        raise MemoryValidationError("Memory scope label is invalid.")
    return PreferencePayload("memory scope label", label).preference


def normalize_scope_label(value: str) -> str:
    """Return a stable, conservative comparison key for a validated label."""

    label = validate_scope_label(value)
    normalized = unicodedata.normalize("NFKC", label).casefold()
    normalized = " ".join(_QUERY_WORD.sub(" ", normalized).split())
    if not normalized or len(normalized) > MAX_SCOPE_LABEL_CHARS:
        raise MemoryValidationError("Memory scope label is invalid.")
    return normalized


def normalize_scope_query(value: str) -> str:
    """Normalize a bounded query without storing or classifying its content."""

    if not isinstance(value, str) or len(value) > 1_000:
        raise MemoryValidationError("Memory scope query is invalid.")
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(_QUERY_WORD.sub(" ", normalized).split())
