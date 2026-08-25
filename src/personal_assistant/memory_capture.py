"""Trusted coordination for explicit memories and quarantined suggestions."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import re
from threading import Lock
from time import monotonic
from uuid import UUID

from personal_assistant.audit import (
    AuditComponent,
    AuditEvent,
    AuditMetadataItem,
    AuditMetadataKey,
    AuditOperation,
    AuditOutcome,
    AuditReasonCode,
    AuditSink,
)
from personal_assistant.memory_repository import (
    MAX_CAPTURE_NEIGHBORS,
    MAX_CANDIDATES_PER_SOURCE,
    CandidateLimitError,
    MemoryRecord,
    MemoryRepository,
)
from personal_assistant.memory_types import (
    ActorType,
    FactPayload,
    InsightPayload,
    MemoryPayload,
    MemoryValidationError,
    MentionPolicy,
    NotePayload,
    PolicyPreferencePayload,
    PreferencePayload,
    Provenance,
    RecordDraft,
    RecordStatus,
    Scope,
    Sensitivity,
    SourceType,
    canonical_json,
    payload_to_data,
)


DEFAULT_CANDIDATES_PER_SOURCE = 3


class CaptureDecision(StrEnum):
    """Stable outcomes that contain no memory or model text."""

    CREATED_CONFIRMED = "created_confirmed"
    CREATED_CANDIDATE = "created_candidate"
    CREATED_CANDIDATE_REVIEW_REQUIRED = "created_candidate_review_required"
    DUPLICATE = "duplicate"
    CONFIRMED_EXISTING_CANDIDATE = "confirmed_existing_candidate"
    CLARIFICATION_REQUIRED = "clarification_required"
    EXPLICIT_HIGHER_RISK_REVIEW_REQUIRED = "explicit_higher_risk_review_required"
    CANDIDATE_LIMIT_REACHED = "candidate_limit_reached"


@dataclass(frozen=True)
class ExplicitMemoryRequest:
    """One typed request derived from an explicit user remember instruction."""

    payload: MemoryPayload
    sensitivity: Sensitivity
    mention_policy: MentionPolicy
    scope: Scope
    source_ref: str
    primary_entity_id: UUID | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None

    def __post_init__(self) -> None:
        Provenance(SourceType.EXPLICIT_USER, self.source_ref, ActorType.USER)
        self.to_draft()

    def to_draft(self) -> RecordDraft:
        return RecordDraft(
            self.payload,
            RecordStatus.CONFIRMED,
            self.sensitivity,
            self.mention_policy,
            self.scope,
            self.primary_entity_id,
            self.valid_from,
            self.valid_until,
        )


@dataclass(frozen=True)
class AutomaticMemorySuggestion:
    """One untrusted model proposal after structural parsing and validation."""

    payload: MemoryPayload
    proposed_sensitivity: Sensitivity
    proposed_mention_policy: MentionPolicy
    scope: Scope
    source_ref: str
    model_version: str
    resolved_primary_entity_id: UUID | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None

    def __post_init__(self) -> None:
        Provenance(
            SourceType.MODEL_CANDIDATE,
            self.source_ref,
            ActorType.MODEL_CANDIDATE,
            self.model_version,
        )
        self.to_draft()

    def to_draft(self) -> RecordDraft:
        sensitivity = _automatic_sensitivity(
            self.payload,
            self.proposed_sensitivity,
        )
        mention_policy = _automatic_mention_policy(
            sensitivity,
            self.proposed_mention_policy,
        )
        return RecordDraft(
            self.payload,
            RecordStatus.CANDIDATE,
            sensitivity,
            mention_policy,
            self.scope,
            self.resolved_primary_entity_id,
            self.valid_from,
            self.valid_until,
        )


@dataclass(frozen=True)
class CaptureResult:
    """A typed decision and records intended only for a trusted interface."""

    decision: CaptureDecision
    record: MemoryRecord | None = None
    related_record_ids: tuple[UUID, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.decision, CaptureDecision):
            raise MemoryValidationError("Capture decision is invalid.")
        if self.record is not None and not isinstance(self.record, MemoryRecord):
            raise MemoryValidationError("Capture result record is invalid.")
        if not isinstance(self.related_record_ids, tuple) or not all(
            isinstance(record_id, UUID) for record_id in self.related_record_ids
        ):
            raise MemoryValidationError("Capture result record IDs are invalid.")


@dataclass(frozen=True)
class SuggestionBatchResult:
    """Bounded results from a cancellable post-response suggestion batch."""

    results: tuple[CaptureResult, ...]
    cancelled: bool

    def __post_init__(self) -> None:
        if not isinstance(self.results, tuple) or not all(
            isinstance(result, CaptureResult) for result in self.results
        ):
            raise MemoryValidationError("Suggestion batch results are invalid.")
        if not isinstance(self.cancelled, bool):
            raise MemoryValidationError("Suggestion cancellation state is invalid.")


class MemoryCaptureCoordinator:
    """Apply capture policy before calling fixed encrypted repository operations."""

    def __init__(
        self,
        repository: MemoryRepository,
        audit_sink: AuditSink,
        *,
        candidates_per_source: int = DEFAULT_CANDIDATES_PER_SOURCE,
    ) -> None:
        if not isinstance(repository, MemoryRepository):
            raise TypeError("Memory capture requires a repository.")
        if not isinstance(audit_sink, AuditSink):
            raise TypeError("Memory capture requires an audit sink.")
        if (
            isinstance(candidates_per_source, bool)
            or not isinstance(candidates_per_source, int)
            or not 1 <= candidates_per_source <= MAX_CANDIDATES_PER_SOURCE
        ):
            raise ValueError("Automatic candidate limit is invalid.")
        self._repository = repository
        self._audit_sink = audit_sink
        self._candidates_per_source = candidates_per_source
        self._lock = Lock()

    def remember_explicitly(
        self,
        request: ExplicitMemoryRequest,
        correlation_id: UUID,
    ) -> CaptureResult:
        """Create confirmed low-risk memory or return a safe review decision."""

        if not isinstance(request, ExplicitMemoryRequest):
            raise MemoryValidationError("Explicit memory request is invalid.")
        started = monotonic()
        self._emit(
            correlation_id,
            "explicit_remember",
            AuditOutcome.STARTED,
            AuditReasonCode.NORMAL,
            started,
        )
        try:
            result = self._remember_explicitly(request, correlation_id)
        except Exception:
            self._emit(
                correlation_id,
                "explicit_remember",
                AuditOutcome.FAILED,
                AuditReasonCode.SAFE_INTERNAL_FAILURE,
                started,
            )
            raise
        self._emit_result(correlation_id, "explicit_remember", result, started)
        return result

    def _remember_explicitly(
        self,
        request: ExplicitMemoryRequest,
        correlation_id: UUID,
    ) -> CaptureResult:
        classified_sensitivity = _deterministic_sensitivity(request.payload)
        sensitivity = max(
            (request.sensitivity, classified_sensitivity),
            key=_SENSITIVITY_ORDER.__getitem__,
        )
        draft = RecordDraft(
            request.payload,
            RecordStatus.CONFIRMED,
            sensitivity,
            request.mention_policy,
            request.scope,
            request.primary_entity_id,
            request.valid_from,
            request.valid_until,
        )
        provenance = Provenance(
            SourceType.EXPLICIT_USER,
            request.source_ref,
            ActorType.USER,
        )
        if draft.sensitivity not in {Sensitivity.NORMAL, Sensitivity.PERSONAL}:
            return CaptureResult(CaptureDecision.EXPLICIT_HIGHER_RISK_REVIEW_REQUIRED)

        with self._lock:
            neighbors = self._repository.find_capture_neighbors(
                draft,
                correlation_id,
            )
            if len(neighbors) > MAX_CAPTURE_NEIGHBORS:
                return self._clarification(neighbors)
            exact, topical = _classify_neighbors(draft.payload, neighbors)
            confirmed = tuple(
                record for record in exact if record.status is RecordStatus.CONFIRMED
            )
            if confirmed:
                return CaptureResult(
                    CaptureDecision.DUPLICATE,
                    related_record_ids=tuple(
                        record.record_id for record in confirmed
                    ),
                )
            candidates = tuple(
                record for record in exact if record.status is RecordStatus.CANDIDATE
            )
            if len(candidates) == 1:
                existing = candidates[0]
                confirmed_record = self._repository.confirm_candidate(
                    existing.record_id,
                    existing.row_version,
                    provenance,
                    correlation_id,
                )
                return CaptureResult(
                    CaptureDecision.CONFIRMED_EXISTING_CANDIDATE,
                    confirmed_record,
                    (existing.record_id,),
                )
            if len(candidates) > 1 or topical:
                return self._clarification(candidates + topical)
            record = self._repository.create_record(
                draft,
                provenance,
                correlation_id,
            )
            return CaptureResult(CaptureDecision.CREATED_CONFIRMED, record)

    def suggest_automatically(
        self,
        suggestion: AutomaticMemorySuggestion,
        correlation_id: UUID,
    ) -> CaptureResult:
        """Create only a bounded quarantined candidate from model output."""

        if not isinstance(suggestion, AutomaticMemorySuggestion):
            raise MemoryValidationError("Automatic memory suggestion is invalid.")
        started = monotonic()
        self._emit(
            correlation_id,
            "automatic_suggestion",
            AuditOutcome.STARTED,
            AuditReasonCode.NORMAL,
            started,
        )
        try:
            result = self._suggest_automatically(suggestion, correlation_id)
        except Exception:
            self._emit(
                correlation_id,
                "automatic_suggestion",
                AuditOutcome.FAILED,
                AuditReasonCode.SAFE_INTERNAL_FAILURE,
                started,
            )
            raise
        self._emit_result(correlation_id, "automatic_suggestion", result, started)
        return result

    def process_suggestion_batch(
        self,
        suggestions: tuple[AutomaticMemorySuggestion, ...],
        correlation_id: UUID,
        *,
        is_cancelled: Callable[[], bool] = lambda: False,
    ) -> SuggestionBatchResult:
        """Process a small post-response batch that a session may cancel safely."""

        if not isinstance(suggestions, tuple) or not all(
            isinstance(suggestion, AutomaticMemorySuggestion)
            for suggestion in suggestions
        ):
            raise MemoryValidationError("Automatic suggestion batch is invalid.")
        if len(suggestions) > self._candidates_per_source:
            raise MemoryValidationError("Automatic suggestion batch is too large.")
        if suggestions and len({item.source_ref for item in suggestions}) != 1:
            raise MemoryValidationError(
                "Automatic suggestion batch must come from one completed turn."
            )
        if not callable(is_cancelled):
            raise MemoryValidationError("Suggestion cancellation check is invalid.")
        results: list[CaptureResult] = []
        for suggestion in suggestions:
            if is_cancelled():
                return SuggestionBatchResult(tuple(results), True)
            results.append(
                self.suggest_automatically(suggestion, correlation_id)
            )
        return SuggestionBatchResult(tuple(results), False)

    def _suggest_automatically(
        self,
        suggestion: AutomaticMemorySuggestion,
        correlation_id: UUID,
    ) -> CaptureResult:
        draft = suggestion.to_draft()
        provenance = Provenance(
            SourceType.MODEL_CANDIDATE,
            suggestion.source_ref,
            ActorType.MODEL_CANDIDATE,
            suggestion.model_version,
        )
        with self._lock:
            neighbors = self._repository.find_capture_neighbors(
                draft,
                correlation_id,
            )
            if len(neighbors) > MAX_CAPTURE_NEIGHBORS:
                return self._clarification(neighbors)
            exact, topical = _classify_neighbors(draft.payload, neighbors)
            if exact:
                return CaptureResult(
                    CaptureDecision.DUPLICATE,
                    related_record_ids=tuple(record.record_id for record in exact),
                )
            try:
                record = self._repository.create_bounded_candidate(
                    draft,
                    provenance,
                    correlation_id,
                    source_limit=self._candidates_per_source,
                )
            except CandidateLimitError:
                return CaptureResult(CaptureDecision.CANDIDATE_LIMIT_REACHED)
            if topical:
                return CaptureResult(
                    CaptureDecision.CREATED_CANDIDATE_REVIEW_REQUIRED,
                    record,
                    tuple(item.record_id for item in topical),
                )
            return CaptureResult(CaptureDecision.CREATED_CANDIDATE, record)

    @staticmethod
    def _clarification(records: tuple[MemoryRecord, ...]) -> CaptureResult:
        return CaptureResult(
            CaptureDecision.CLARIFICATION_REQUIRED,
            related_record_ids=tuple(record.record_id for record in records),
        )

    def _emit_result(
        self,
        correlation_id: UUID,
        action_kind: str,
        result: CaptureResult,
        started: float,
    ) -> None:
        if result.decision in {
            CaptureDecision.CREATED_CONFIRMED,
            CaptureDecision.CREATED_CANDIDATE,
            CaptureDecision.CREATED_CANDIDATE_REVIEW_REQUIRED,
            CaptureDecision.CONFIRMED_EXISTING_CANDIDATE,
        }:
            outcome = AuditOutcome.SUCCEEDED
            reason = (
                AuditReasonCode.CLARIFICATION_REQUIRED
                if result.decision
                is CaptureDecision.CREATED_CANDIDATE_REVIEW_REQUIRED
                else AuditReasonCode.NORMAL
            )
        elif result.decision is CaptureDecision.DUPLICATE:
            outcome = AuditOutcome.SKIPPED
            reason = AuditReasonCode.DUPLICATE
        elif result.decision is CaptureDecision.CANDIDATE_LIMIT_REACHED:
            outcome = AuditOutcome.SKIPPED
            reason = AuditReasonCode.RESOURCE_LIMIT
        elif result.decision is CaptureDecision.CLARIFICATION_REQUIRED:
            outcome = AuditOutcome.SKIPPED
            reason = AuditReasonCode.CLARIFICATION_REQUIRED
        else:
            outcome = AuditOutcome.DENIED
            reason = AuditReasonCode.POLICY_DENIED
        self._emit(
            correlation_id,
            action_kind,
            outcome,
            reason,
            started,
            result,
        )

    def _emit(
        self,
        correlation_id: UUID,
        action_kind: str,
        outcome: AuditOutcome,
        reason: AuditReasonCode,
        started: float,
        result: CaptureResult | None = None,
    ) -> None:
        metadata = [
            AuditMetadataItem(AuditMetadataKey.ACTION_KIND, action_kind),
            AuditMetadataItem(AuditMetadataKey.TARGET_CLASS, "encrypted_memory"),
        ]
        if result is not None and result.record is not None:
            metadata.append(
                AuditMetadataItem(
                    AuditMetadataKey.RECORD_ID,
                    str(result.record.record_id),
                )
            )
        elif result is not None and result.related_record_ids:
            metadata.append(
                AuditMetadataItem(
                    AuditMetadataKey.RECORD_ID,
                    str(result.related_record_ids[0]),
                )
            )
        if result is not None and result.related_record_ids:
            metadata.append(
                AuditMetadataItem(
                    AuditMetadataKey.ITEM_COUNT,
                    len(result.related_record_ids),
                )
            )
        self._audit_sink.write(
            AuditEvent(
                correlation_id=correlation_id,
                component=AuditComponent.APPLICATION,
                operation=AuditOperation.MEMORY_CAPTURE,
                outcome=outcome,
                reason_code=reason,
                metadata=tuple(metadata),
                duration_ms=max(0, int((monotonic() - started) * 1_000)),
            )
        )


_SENSITIVITY_ORDER = {
    Sensitivity.NORMAL: 0,
    Sensitivity.PERSONAL: 1,
    Sensitivity.SENSITIVE: 2,
    Sensitivity.RESTRICTED: 3,
}
_MENTION_ORDER = {
    MentionPolicy.MAY_MENTION_WHEN_RELEVANT: 0,
    MentionPolicy.ASK_BEFORE_MENTIONING: 1,
    MentionPolicy.ONLY_WHEN_DIRECTLY_ASKED: 2,
    MentionPolicy.NEVER_MENTION: 3,
}
_AUTOMATIC_MENTION_FLOOR = {
    Sensitivity.NORMAL: MentionPolicy.MAY_MENTION_WHEN_RELEVANT,
    Sensitivity.PERSONAL: MentionPolicy.ASK_BEFORE_MENTIONING,
    Sensitivity.SENSITIVE: MentionPolicy.ONLY_WHEN_DIRECTLY_ASKED,
    Sensitivity.RESTRICTED: MentionPolicy.NEVER_MENTION,
}
_RESTRICTED_CONTENT = re.compile(
    r"\b(?:childhood\s+trauma|trauma|abuse|assault|self[- ]?harm|suicid\w*|"
    r"diagnos\w*|medical\s+condition|therap(?:y|ist)|psychiatr\w*|addiction|"
    r"bank\s+account|financial\s+account|routing\s+number|income|debt|"
    r"legal\s+case|lawsuit)\b",
    re.IGNORECASE,
)
_SENSITIVE_CONTENT = re.compile(
    r"\b(?:emotion\w*|anxi\w*|depress\w*|grief|relationship|conflict|"
    r"health|money|financial|location|address|workplace|date\s+of\s+birth|"
    r"birth\s*date|phone(?:\s+number)?|email(?:\s+address)?)\b",
    re.IGNORECASE,
)
_RESTRICTED_IDENTITY_CONTENT = re.compile(
    r"\b(?:social\s+security(?:\s+number)?|ssn|tax(?:payer)?\s+(?:id|number)|"
    r"passport(?:\s+number)?|driver(?:'s)?\s+licen[cs]e(?:\s+number)?|"
    r"national\s+(?:id|identifier)|insurance\s+(?:id|number))\b",
    re.IGNORECASE,
)


def _automatic_sensitivity(
    payload: MemoryPayload,
    proposed: Sensitivity,
) -> Sensitivity:
    if not isinstance(proposed, Sensitivity) or proposed is Sensitivity.PROHIBITED:
        raise MemoryValidationError("Automatic sensitivity is invalid.")
    type_floor = (
        Sensitivity.PERSONAL
        if isinstance(payload, (InsightPayload, NotePayload))
        else Sensitivity.NORMAL
    )
    deterministic = _deterministic_sensitivity(payload)
    return max(
        (type_floor, deterministic, proposed),
        key=_SENSITIVITY_ORDER.__getitem__,
    )


def _deterministic_sensitivity(payload: MemoryPayload) -> Sensitivity:
    text = canonical_json(payload_to_data(payload))
    if _RESTRICTED_CONTENT.search(text) or _RESTRICTED_IDENTITY_CONTENT.search(text):
        return Sensitivity.RESTRICTED
    if _SENSITIVE_CONTENT.search(text):
        return Sensitivity.SENSITIVE
    return Sensitivity.NORMAL


def _automatic_mention_policy(
    sensitivity: Sensitivity,
    proposed: MentionPolicy,
) -> MentionPolicy:
    if not isinstance(proposed, MentionPolicy):
        raise MemoryValidationError("Automatic mention policy is invalid.")
    floor = _AUTOMATIC_MENTION_FLOOR[sensitivity]
    return max((floor, proposed), key=_MENTION_ORDER.__getitem__)


def _classify_neighbors(
    payload: MemoryPayload,
    neighbors: tuple[MemoryRecord, ...],
) -> tuple[tuple[MemoryRecord, ...], tuple[MemoryRecord, ...]]:
    identity = canonical_json(payload_to_data(payload))
    topic = _payload_topic(payload)
    exact: list[MemoryRecord] = []
    topical: list[MemoryRecord] = []
    for record in neighbors:
        stored_payload = record.revision.payload
        if canonical_json(payload_to_data(stored_payload)) == identity:
            exact.append(record)
        elif topic is not None and _payload_topic(stored_payload) == topic:
            topical.append(record)
    return tuple(exact), tuple(topical)


def _payload_topic(payload: MemoryPayload) -> str | None:
    value: str | None = None
    if isinstance(payload, (FactPayload, PreferencePayload, PolicyPreferencePayload)):
        value = payload.subject
    elif isinstance(payload, NotePayload):
        value = payload.title
    if value is None:
        return None
    return " ".join(value.casefold().split())
