"""Typed, bounded values accepted by the persistent-memory repository."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import json
import re
import unicodedata
from typing import Any, TypeAlias
from uuid import UUID


MAX_PAYLOAD_BYTES = 16_384
MAX_CONTENT_CHARS = 8_000
MAX_SUMMARY_CHARS = 4_000
MAX_SUBJECT_CHARS = 256
MAX_REFERENCE_CHARS = 128

_SAFE_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_PROHIBITED_CREDENTIAL_TERMS = re.compile(
    r"\b(?:password|passcode|passphrase|security\s+answer|api[-_ ]?key|"
    r"access\s+token|refresh\s+token|private\s+key|secret\s+key|"
    r"seed\s+phrase|recovery\s+phrase|wallet\s+seed|pin|"
    r"credit\s+card\s+number|"
    r"card\s+verification\s+(?:code|value)|cvv|cvc|"
    r"(?:login|authentication|verification|one[- ]?time|2fa)\s+code)\b",
    re.IGNORECASE,
)
_OBFUSCATED_CREDENTIAL_TERMS = re.compile(
    r"(?:password|passcode|passphrase|securityanswer|apikey|accesstoken|"
    r"refreshtoken|privatekey|secretkey|seedphrase|recoveryphrase|"
    r"walletseed|creditcardnumber|cardverification(?:code|value))",
    re.IGNORECASE,
)
_PAYMENT_CARD_CANDIDATE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_PROHIBITED_SECRET_MARKERS = (
    "-----BEGIN PRIVATE KEY-----",
    "-----BEGIN OPENSSH PRIVATE KEY-----",
    "-----BEGIN PGP PRIVATE KEY BLOCK-----",
)
_BIDI_CONTROLS = {
    "\u061c",
    "\u200e",
    "\u200f",
    "\u202a",
    "\u202b",
    "\u202c",
    "\u202d",
    "\u202e",
    "\u2066",
    "\u2067",
    "\u2068",
    "\u2069",
}


class MemoryValidationError(ValueError):
    """A memory value violates its deterministic schema or privacy limits."""


class RecordKind(StrEnum):
    FACT = "fact"
    PREFERENCE = "preference"
    EVENT = "event"
    NOTE = "note"
    INSIGHT = "insight"
    POLICY_PREFERENCE = "policy_preference"


class RecordStatus(StrEnum):
    CANDIDATE = "candidate"
    CONFIRMED = "confirmed"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"
    DELETED = "deleted"


class Sensitivity(StrEnum):
    NORMAL = "normal"
    PERSONAL = "personal"
    SENSITIVE = "sensitive"
    RESTRICTED = "restricted"
    PROHIBITED = "prohibited"


class MentionPolicy(StrEnum):
    MAY_MENTION_WHEN_RELEVANT = "may_mention_when_relevant"
    ASK_BEFORE_MENTIONING = "ask_before_mentioning"
    ONLY_WHEN_DIRECTLY_ASKED = "only_when_directly_asked"
    NEVER_MENTION = "never_mention"


class ScopeType(StrEnum):
    GLOBAL = "global"
    CONVERSATION_DOMAIN = "conversation_domain"
    TOPIC = "topic"
    ENTITY = "entity"
    PROJECT = "project"
    PLACE = "place"


class SourceType(StrEnum):
    EXPLICIT_USER = "explicit_user"
    TRUSTED_INTERFACE = "trusted_interface"
    MODEL_CANDIDATE = "model_candidate"
    MIGRATION = "migration"


class ActorType(StrEnum):
    USER = "user"
    SYSTEM = "system"
    MODEL_CANDIDATE = "model_candidate"


class ChangeReason(StrEnum):
    CREATED = "created"
    CORRECTED = "corrected"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    ARCHIVED = "archived"
    RESTORED = "restored"
    SUPERSEDED = "superseded"
    DELETED = "deleted"
    EXPIRED = "expired"


class EntityType(StrEnum):
    PERSON = "person"
    PET = "pet"
    PLACE = "place"
    PROJECT = "project"
    ORGANIZATION = "organization"
    OTHER = "other"


class EntityStatus(StrEnum):
    ACTIVE = "active"
    MERGED = "merged"
    ARCHIVED = "archived"
    DELETED = "deleted"


class AliasSourceType(StrEnum):
    EXPLICIT_USER = "explicit_user"
    TRUSTED_INTERFACE = "trusted_interface"
    DETERMINISTIC_MATCH = "deterministic_match"
    MODEL_CANDIDATE = "model_candidate"


class ConfidenceBasis(StrEnum):
    EXPLICIT = "explicit"
    EXACT_MATCH = "exact_match"
    CANDIDATE = "candidate"


class RecordRelationship(StrEnum):
    EVIDENCE = "evidence"
    CONTRADICTION = "contradiction"
    SUPERSESSION = "supersession"
    RELATED = "related"


class EntityRelationship(StrEnum):
    RELATED = "related"
    MEMBER_OF = "member_of"
    LOCATED_AT = "located_at"
    ASSOCIATED_WITH = "associated_with"


class LinkSourceType(StrEnum):
    EXPLICIT_USER = "explicit_user"
    TRUSTED_INTERFACE = "trusted_interface"
    DETERMINISTIC_RULE = "deterministic_rule"
    MODEL_CANDIDATE = "model_candidate"


class FeedbackType(StrEnum):
    CONFIRM = "confirm"
    REJECT = "reject"
    EDIT = "edit"
    DELETE = "delete"
    RELEVANT = "relevant"
    IRRELEVANT = "irrelevant"


class InsightConfidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PurgeReason(StrEnum):
    USER_REQUESTED = "user_requested"
    SECURITY_RESPONSE = "security_response"
    RESTORE_SUPPRESSION = "restore_suppression"


def _validate_text(value: str, label: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise MemoryValidationError(f"{label} must be text.")
    normalized = unicodedata.normalize("NFKC", value)
    if not normalized.strip() or len(normalized) > maximum:
        raise MemoryValidationError(f"{label} is empty or too large.")
    for character in normalized:
        if character in _BIDI_CONTROLS:
            raise MemoryValidationError(f"{label} contains unsafe formatting.")
        category = unicodedata.category(character)
        if category == "Cf":
            raise MemoryValidationError(f"{label} contains unsafe formatting.")
        if category == "Cc" and character not in {"\n", "\t"}:
            raise MemoryValidationError(f"{label} contains unsafe controls.")
    return normalized


def _validate_reference(value: str, label: str) -> str:
    if not isinstance(value, str) or not _SAFE_REFERENCE.fullmatch(value):
        raise MemoryValidationError(f"{label} must be a bounded opaque reference.")
    return value


def _validate_datetime(value: datetime | None, label: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise MemoryValidationError(f"{label} must include a timezone.")
    if value.utcoffset() is None:
        raise MemoryValidationError(f"{label} must include a timezone.")
    return value


def _reject_credentials(values: tuple[str, ...]) -> None:
    combined = "\n".join(values)
    if _PROHIBITED_CREDENTIAL_TERMS.search(combined):
        raise MemoryValidationError("Credential-related content cannot be stored.")
    compact = "".join(character for character in combined if character.isalnum())
    if _OBFUSCATED_CREDENTIAL_TERMS.search(compact):
        raise MemoryValidationError("Credential-related content cannot be stored.")
    for match in _PAYMENT_CARD_CANDIDATE.finditer(combined):
        digits = "".join(character for character in match.group() if character.isdigit())
        if _passes_luhn_check(digits):
            raise MemoryValidationError("Credential-related content cannot be stored.")
    upper = combined.upper()
    if any(marker in upper for marker in _PROHIBITED_SECRET_MARKERS):
        raise MemoryValidationError("Credential-related content cannot be stored.")


def _passes_luhn_check(digits: str) -> bool:
    if not 13 <= len(digits) <= 19 or len(set(digits)) == 1:
        return False
    total = 0
    parity = len(digits) % 2
    for index, character in enumerate(digits):
        value = int(character)
        if index % 2 == parity:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


@dataclass(frozen=True)
class FactPayload:
    subject: str
    statement: str

    def __post_init__(self) -> None:
        subject = _validate_text(self.subject, "Fact subject", MAX_SUBJECT_CHARS)
        statement = _validate_text(
            self.statement, "Fact statement", MAX_SUMMARY_CHARS
        )
        _reject_credentials((subject, statement))
        object.__setattr__(self, "subject", subject)
        object.__setattr__(self, "statement", statement)


@dataclass(frozen=True)
class PreferencePayload:
    subject: str
    preference: str

    def __post_init__(self) -> None:
        subject = _validate_text(
            self.subject, "Preference subject", MAX_SUBJECT_CHARS
        )
        preference = _validate_text(
            self.preference, "Preference", MAX_SUMMARY_CHARS
        )
        _reject_credentials((subject, preference))
        object.__setattr__(self, "subject", subject)
        object.__setattr__(self, "preference", preference)


@dataclass(frozen=True)
class EventPayload:
    summary: str
    occurred_at: datetime

    def __post_init__(self) -> None:
        summary = _validate_text(self.summary, "Event summary", MAX_SUMMARY_CHARS)
        occurred_at = _validate_datetime(self.occurred_at, "Event time")
        if occurred_at is None:
            raise MemoryValidationError("Event time is required.")
        _reject_credentials((summary,))
        object.__setattr__(self, "summary", summary)
        object.__setattr__(self, "occurred_at", occurred_at)


@dataclass(frozen=True)
class NotePayload:
    title: str
    body: str

    def __post_init__(self) -> None:
        title = _validate_text(self.title, "Note title", MAX_SUBJECT_CHARS)
        body = _validate_text(self.body, "Note body", MAX_CONTENT_CHARS)
        _reject_credentials((title, body))
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "body", body)


@dataclass(frozen=True)
class InsightPayload:
    observation: str
    confidence: InsightConfidence
    contradictions_considered: str
    range_start: datetime
    range_end: datetime

    def __post_init__(self) -> None:
        observation = _validate_text(
            self.observation, "Insight observation", MAX_SUMMARY_CHARS
        )
        contradictions = _validate_text(
            self.contradictions_considered,
            "Insight contradictions",
            MAX_SUMMARY_CHARS,
        )
        if not isinstance(self.confidence, InsightConfidence):
            raise MemoryValidationError("Insight confidence is invalid.")
        range_start = _validate_datetime(self.range_start, "Insight range start")
        range_end = _validate_datetime(self.range_end, "Insight range end")
        if range_start is None or range_end is None or range_start > range_end:
            raise MemoryValidationError("Insight time range is invalid.")
        _reject_credentials((observation, contradictions))
        object.__setattr__(self, "observation", observation)
        object.__setattr__(self, "contradictions_considered", contradictions)
        object.__setattr__(self, "range_start", range_start)
        object.__setattr__(self, "range_end", range_end)


@dataclass(frozen=True)
class PolicyPreferencePayload:
    subject: str
    mention_policy: MentionPolicy

    def __post_init__(self) -> None:
        subject = _validate_text(
            self.subject, "Policy preference subject", MAX_SUBJECT_CHARS
        )
        _reject_credentials((subject,))
        if not isinstance(self.mention_policy, MentionPolicy):
            raise MemoryValidationError("Policy preference is invalid.")
        object.__setattr__(self, "subject", subject)


MemoryPayload: TypeAlias = (
    FactPayload
    | PreferencePayload
    | EventPayload
    | NotePayload
    | InsightPayload
    | PolicyPreferencePayload
)


_PAYLOAD_KINDS: dict[type[object], RecordKind] = {
    FactPayload: RecordKind.FACT,
    PreferencePayload: RecordKind.PREFERENCE,
    EventPayload: RecordKind.EVENT,
    NotePayload: RecordKind.NOTE,
    InsightPayload: RecordKind.INSIGHT,
    PolicyPreferencePayload: RecordKind.POLICY_PREFERENCE,
}


@dataclass(frozen=True)
class Scope:
    type: ScopeType
    id: UUID | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.type, ScopeType):
            raise MemoryValidationError("Memory scope type is invalid.")
        if self.type is ScopeType.GLOBAL and self.id is not None:
            raise MemoryValidationError("Global memory cannot have a scope ID.")
        if self.type is not ScopeType.GLOBAL and not isinstance(self.id, UUID):
            raise MemoryValidationError("Scoped memory requires an opaque UUID.")


@dataclass(frozen=True)
class Provenance:
    source_type: SourceType
    source_ref: str
    actor_type: ActorType
    model_version: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source_type, SourceType) or not isinstance(
            self.actor_type, ActorType
        ):
            raise MemoryValidationError("Memory provenance is invalid.")
        source_ref = _validate_reference(self.source_ref, "Source reference")
        model_version = self.model_version
        if self.source_type is SourceType.MODEL_CANDIDATE:
            if self.actor_type is not ActorType.MODEL_CANDIDATE:
                raise MemoryValidationError("Model candidate provenance is invalid.")
            if model_version is None:
                raise MemoryValidationError("Model candidates require a model version.")
            model_version = _validate_reference(model_version, "Model version")
        elif self.actor_type is ActorType.MODEL_CANDIDATE or model_version is not None:
            raise MemoryValidationError("Non-model provenance cannot claim a model.")
        object.__setattr__(self, "source_ref", source_ref)
        object.__setattr__(self, "model_version", model_version)


@dataclass(frozen=True)
class RecordDraft:
    payload: MemoryPayload
    status: RecordStatus
    sensitivity: Sensitivity
    mention_policy: MentionPolicy
    scope: Scope
    primary_entity_id: UUID | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None

    def __post_init__(self) -> None:
        if type(self.payload) not in _PAYLOAD_KINDS:
            raise MemoryValidationError("Memory payload type is not registered.")
        if self.status not in {RecordStatus.CANDIDATE, RecordStatus.CONFIRMED}:
            raise MemoryValidationError("New memory must be candidate or confirmed.")
        if not isinstance(self.sensitivity, Sensitivity):
            raise MemoryValidationError("Memory sensitivity is invalid.")
        if self.sensitivity is Sensitivity.PROHIBITED:
            raise MemoryValidationError("Prohibited content cannot be stored.")
        if not isinstance(self.mention_policy, MentionPolicy):
            raise MemoryValidationError("Memory mention policy is invalid.")
        if not isinstance(self.scope, Scope):
            raise MemoryValidationError("Memory scope is invalid.")
        if self.primary_entity_id is not None and not isinstance(
            self.primary_entity_id, UUID
        ):
            raise MemoryValidationError("Primary entity ID must be a UUID.")
        valid_from = _validate_datetime(self.valid_from, "Valid-from time")
        valid_until = _validate_datetime(self.valid_until, "Valid-until time")
        if (
            valid_from is not None
            and valid_until is not None
            and valid_from > valid_until
        ):
            raise MemoryValidationError("Memory validity range is invalid.")
        object.__setattr__(self, "valid_from", valid_from)
        object.__setattr__(self, "valid_until", valid_until)

    @property
    def kind(self) -> RecordKind:
        return _PAYLOAD_KINDS[type(self.payload)]


@dataclass(frozen=True)
class EntityDraft:
    entity_type: EntityType

    def __post_init__(self) -> None:
        if not isinstance(self.entity_type, EntityType):
            raise MemoryValidationError("Entity type is invalid.")


@dataclass(frozen=True)
class AliasDraft:
    display_alias: str
    source_type: AliasSourceType
    source_ref: str
    confidence_basis: ConfidenceBasis

    def __post_init__(self) -> None:
        alias = _validate_text(
            self.display_alias, "Entity alias", MAX_SUBJECT_CHARS * 2
        )
        _reject_credentials((alias,))
        if not isinstance(self.source_type, AliasSourceType) or not isinstance(
            self.confidence_basis, ConfidenceBasis
        ):
            raise MemoryValidationError("Entity alias provenance is invalid.")
        source_ref = _validate_reference(self.source_ref, "Alias source reference")
        object.__setattr__(self, "display_alias", alias)
        object.__setattr__(self, "source_ref", source_ref)


@dataclass(frozen=True)
class RecordLinkDraft:
    source_record_id: UUID
    target_record_id: UUID
    relationship: RecordRelationship
    source_type: LinkSourceType
    source_ref: str

    def __post_init__(self) -> None:
        if not isinstance(self.source_record_id, UUID) or not isinstance(
            self.target_record_id, UUID
        ):
            raise MemoryValidationError("Record link IDs must be UUID values.")
        if self.source_record_id == self.target_record_id:
            raise MemoryValidationError("A record cannot link to itself.")
        if not isinstance(self.relationship, RecordRelationship) or not isinstance(
            self.source_type, LinkSourceType
        ):
            raise MemoryValidationError("Record link type is invalid.")
        source_ref = _validate_reference(self.source_ref, "Link source reference")
        object.__setattr__(self, "source_ref", source_ref)


@dataclass(frozen=True)
class EntityLinkDraft:
    source_entity_id: UUID
    target_entity_id: UUID
    relationship: EntityRelationship
    source_type: LinkSourceType
    source_ref: str

    def __post_init__(self) -> None:
        if not isinstance(self.source_entity_id, UUID) or not isinstance(
            self.target_entity_id, UUID
        ):
            raise MemoryValidationError("Entity link IDs must be UUID values.")
        if self.source_entity_id == self.target_entity_id:
            raise MemoryValidationError("An entity cannot link to itself.")
        if not isinstance(self.relationship, EntityRelationship) or not isinstance(
            self.source_type, LinkSourceType
        ):
            raise MemoryValidationError("Entity link type is invalid.")
        source_ref = _validate_reference(self.source_ref, "Link source reference")
        object.__setattr__(self, "source_ref", source_ref)


def normalize_alias(value: str) -> str:
    """Return a deterministic exact-match key without guessing identity."""

    validated = _validate_text(value, "Entity alias", MAX_SUBJECT_CHARS * 2)
    normalized = " ".join(validated.casefold().split())
    if not normalized:
        raise MemoryValidationError("Entity alias is empty.")
    return normalized


def payload_to_data(payload: MemoryPayload) -> dict[str, Any]:
    """Serialize only registered payload classes into versioned JSON data."""

    if isinstance(payload, FactPayload):
        return {"type": "fact", "subject": payload.subject, "statement": payload.statement}
    if isinstance(payload, PreferencePayload):
        return {
            "type": "preference",
            "subject": payload.subject,
            "preference": payload.preference,
        }
    if isinstance(payload, EventPayload):
        return {
            "type": "event",
            "summary": payload.summary,
            "occurred_at": payload.occurred_at.isoformat(),
        }
    if isinstance(payload, NotePayload):
        return {"type": "note", "title": payload.title, "body": payload.body}
    if isinstance(payload, InsightPayload):
        return {
            "type": "insight",
            "observation": payload.observation,
            "confidence": payload.confidence.value,
            "contradictions_considered": payload.contradictions_considered,
            "range_start": payload.range_start.isoformat(),
            "range_end": payload.range_end.isoformat(),
        }
    if isinstance(payload, PolicyPreferencePayload):
        return {
            "type": "policy_preference",
            "subject": payload.subject,
            "mention_policy": payload.mention_policy.value,
        }
    raise MemoryValidationError("Memory payload type is not registered.")


def payload_from_data(data: object) -> MemoryPayload:
    """Rebuild a typed payload while reapplying every content validator."""

    if not isinstance(data, dict) or not isinstance(data.get("type"), str):
        raise MemoryValidationError("Stored memory payload is invalid.")
    try:
        payload_type = data["type"]
        if payload_type == "fact" and set(data) == {"type", "subject", "statement"}:
            return FactPayload(data["subject"], data["statement"])
        if payload_type == "preference" and set(data) == {
            "type",
            "subject",
            "preference",
        }:
            return PreferencePayload(data["subject"], data["preference"])
        if payload_type == "event" and set(data) == {
            "type",
            "summary",
            "occurred_at",
        }:
            return EventPayload(
                data["summary"], datetime.fromisoformat(data["occurred_at"])
            )
        if payload_type == "note" and set(data) == {"type", "title", "body"}:
            return NotePayload(data["title"], data["body"])
        if payload_type == "insight" and set(data) == {
            "type",
            "observation",
            "confidence",
            "contradictions_considered",
            "range_start",
            "range_end",
        }:
            return InsightPayload(
                data["observation"],
                InsightConfidence(data["confidence"]),
                data["contradictions_considered"],
                datetime.fromisoformat(data["range_start"]),
                datetime.fromisoformat(data["range_end"]),
            )
        if payload_type == "policy_preference" and set(data) == {
            "type",
            "subject",
            "mention_policy",
        }:
            return PolicyPreferencePayload(
                data["subject"], MentionPolicy(data["mention_policy"])
            )
    except (KeyError, TypeError, ValueError) as error:
        raise MemoryValidationError("Stored memory payload is invalid.") from error
    raise MemoryValidationError("Stored memory payload is invalid.")


def canonical_json(data: object) -> str:
    """Encode bounded canonical JSON for stable revision hashing."""

    try:
        encoded = json.dumps(
            data,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as error:
        raise MemoryValidationError("Memory payload could not be encoded.") from error
    if len(encoded.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise MemoryValidationError("Memory payload exceeds its storage limit.")
    return encoded
