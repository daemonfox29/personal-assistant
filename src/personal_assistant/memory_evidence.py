"""Deterministic checks shared by memory capture, retrieval, and inventory."""

import re
import unicodedata

from personal_assistant.memory_types import (
    EventPayload,
    FactPayload,
    InsightPayload,
    MemoryPayload,
    NotePayload,
    PolicyPreferencePayload,
    PreferencePayload,
)


_QUESTION_LIKE = re.compile(
    r"^\s*(?:what|when|where|why|who|how|have|has|had|do|does|did|"
    r"am|are|is|was|were|can|could|would|should|will)\b",
    re.IGNORECASE,
)
_UNCERTAIN = re.compile(
    r"\b(?:maybe|might|possibly|probably|i\s+(?:think|guess|suspect)|"
    r"i['’]m\s+not\s+sure|i\s+am\s+not\s+sure)\b",
    re.IGNORECASE,
)
_CONTEXT_DEPENDENT_ENDING = re.compile(
    r"\b(?:there|here|this|that|it)\s*[.!]*$",
    re.IGNORECASE,
)
_SUPPORTED_ASSERTION = re.compile(
    r"\b(?:"
    r"i\s+(?:live|lived|prefer|like|love|dislike|avoid|work|worked|grew|"
    r"was\s+born|was\s+raised|was\s+born\s+and\s+raised|want|own|usually|"
    r"always|never|cannot|can['’]t)\b|"
    r"i(?:\s+am|['’]m)\s+(?:from|based|located|(?:[\w'-]+\s+){0,4}"
    r"(?:allergic|sensitive|intolerant)|a\b|an\b|\d{1,3}\b)|"
    r"i\s+(?:have|do\s+not\s+have|don['’]t\s+have)\s+"
    r"(?:a\s+|an\s+)?(?:[\w'-]+\s+){0,5}"
    r"(?:allerg\w*|sensitiv\w*|intoleran\w*|dog|cat|pet|child|sibling|"
    r"partner|spouse)|"
    r"my\s+(?:name|dog|cat|pet|vet|veterinarian|favorite|preference|"
    r"allerg\w*|sensitiv\w*|"
    r"intoleran\w*|birthday|birth\s+date|age|home|city|state|country|job|"
    r"career|profession|pronouns?|schedule|goal|values?|hobb(?:y|ies)|diet)\b|"
    r"is\s+my\s+(?:dog|cat|pet|partner|spouse)\b"
    r")",
    re.IGNORECASE,
)
_EQUIVALENCE_WORD = re.compile(r"[\w'’-]+", re.UNICODE)


def is_standalone_direct_memory_statement(text: str) -> bool:
    """Accept a bounded declarative personal statement, never a question."""

    if not isinstance(text, str) or not text.strip():
        return False
    stripped = text.strip()
    return bool(
        not stripped.endswith("?")
        and not _QUESTION_LIKE.search(stripped)
        and not _UNCERTAIN.search(stripped)
        and not _CONTEXT_DEPENDENT_ENDING.search(stripped)
        and _SUPPORTED_ASSERTION.search(stripped)
    )


def normalized_memory_text(text: str) -> str:
    """Normalize case, spacing, punctuation, and simple possessives for equality."""

    normalized = unicodedata.normalize("NFKC", text).casefold()
    words: list[str] = []
    for word in _EQUIVALENCE_WORD.findall(normalized):
        if len(word) > 2 and word.endswith(("'s", "’s")):
            word = word[:-2]
        words.append(word)
    return " ".join(words)


def memory_payload_equivalence_key(payload: MemoryPayload) -> tuple[str, ...]:
    """Return a conservative content key that ignores model-authored subjects."""

    if isinstance(payload, FactPayload):
        return ("fact", normalized_memory_text(payload.statement))
    if isinstance(payload, PreferencePayload):
        return ("preference", normalized_memory_text(payload.preference))
    if isinstance(payload, EventPayload):
        return (
            "event",
            normalized_memory_text(payload.summary),
            payload.occurred_at.isoformat(),
        )
    if isinstance(payload, NotePayload):
        return (
            "note",
            normalized_memory_text(payload.title),
            normalized_memory_text(payload.body),
        )
    if isinstance(payload, InsightPayload):
        return ("insight", normalized_memory_text(payload.observation))
    if isinstance(payload, PolicyPreferencePayload):
        return (
            "policy_preference",
            normalized_memory_text(payload.subject),
            payload.mention_policy.value,
        )
    raise TypeError("Memory payload type is not supported for equivalence.")
