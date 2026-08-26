"""Shared bounded word normalization and deterministic topic connections."""

import re
from collections.abc import Set


_WORD = re.compile(r"[\w'’-]+", re.UNICODE)
_TOPIC_CONNECTIONS = (
    ("digestive health", ("gut", "digestive", "digestion", "gluten", "celiac")),
    (
        "sensitivity or allergy",
        ("sensitivity", "intolerance", "allergy", "allergic"),
    ),
    ("pet", ("pet", "dog", "cat")),
    (
        "home or location",
        ("home", "residence", "reside", "live", "location", "based"),
    ),
)


def normalized_term(term: str) -> str:
    """Apply small deterministic English inflections without semantic guessing."""

    if len(term) > 2 and term.endswith(("'s", "’s")):
        term = term[:-2]
    if len(term) > 4 and term.endswith("ies"):
        return f"{term[:-3]}y"
    if (
        len(term) > 3
        and term.endswith("s")
        and not term.endswith(("as", "is", "ss", "us"))
    ):
        return term[:-1]
    return term


def normalized_terms(
    text: str,
    *,
    stop_words: Set[str] = frozenset(),
    minimum_length: int = 1,
    maximum_terms: int = 16,
) -> tuple[str, ...]:
    """Return stable unique normalized terms within fixed caller-selected bounds."""

    terms: list[str] = []
    for raw_term in _WORD.findall(text.casefold()):
        term = normalized_term(raw_term)
        if len(term) < minimum_length or term in stop_words:
            continue
        if term not in terms:
            terms.append(term)
        if len(terms) == maximum_terms:
            break
    return tuple(terms)


def connected_topic_terms(
    terms: tuple[str, ...],
    *,
    maximum_terms: int = 16,
) -> tuple[str, ...]:
    """Expand only reviewed low-risk topic groups; never use model-generated terms."""

    expanded = list(dict.fromkeys(terms))
    present = set(expanded)
    for _, group in _TOPIC_CONNECTIONS:
        if not present.intersection(group):
            continue
        for term in group:
            if term not in expanded:
                expanded.append(term)
            if len(expanded) == maximum_terms:
                return tuple(expanded)
    return tuple(expanded[:maximum_terms])


def safe_topic_labels(text: str, *, fallback: str) -> tuple[str, ...]:
    """Return only reviewed generic labels suitable for trusted UI notices."""

    if not isinstance(text, str) or not isinstance(fallback, str):
        raise ValueError("Memory topic label input is invalid.")
    terms = set(normalized_terms(text, maximum_terms=64))
    labels = tuple(
        label for label, group in _TOPIC_CONNECTIONS if terms.intersection(group)
    )
    return labels or ((fallback,) if fallback else ())


def safe_topic_key(text: str) -> str | None:
    """Return a stable reviewed key for conservative same-topic comparisons."""

    labels = safe_topic_labels(text, fallback="") if text else ()
    return "|".join(labels) or None
