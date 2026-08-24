"""Typed repository for encrypted, revisioned persistent memory."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from time import monotonic
from typing import Any
from uuid import UUID, uuid4

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
from personal_assistant.encrypted_database import EncryptedConnectionProvider
from personal_assistant.memory_types import (
    ActorType,
    AliasDraft,
    AliasSourceType,
    ChangeReason,
    ConfidenceBasis,
    EntityDraft,
    EntityLinkDraft,
    EntityRelationship,
    EntityStatus,
    EntityType,
    FeedbackType,
    InsightPayload,
    LinkSourceType,
    MemoryPayload,
    MemoryValidationError,
    MentionPolicy,
    Provenance,
    PurgeReason,
    RecordDraft,
    RecordKind,
    RecordLinkDraft,
    RecordRelationship,
    RecordStatus,
    Scope,
    ScopeType,
    Sensitivity,
    SourceType,
    canonical_json,
    normalize_alias,
    payload_from_data,
    payload_to_data,
)


PAYLOAD_VERSION = 1
CANDIDATE_LIFETIME = timedelta(days=30)
MINIMUM_INSIGHT_EVIDENCE = 3
MAX_EXPIRY_BATCH = 100


class MemoryRepositoryError(RuntimeError):
    """A safe expected failure at the memory repository boundary."""


class RecordNotFoundError(MemoryRepositoryError):
    """The requested opaque record does not exist in the active store."""


class EntityNotFoundError(MemoryRepositoryError):
    """The requested opaque entity does not exist in the active store."""


class RepositoryConflictError(MemoryRepositoryError):
    """A uniqueness or optimistic-concurrency rule rejected the operation."""


class LifecycleTransitionError(MemoryRepositoryError):
    """A requested memory state transition is not allowed."""


class RepositoryIntegrityError(MemoryRepositoryError):
    """Stored data failed deterministic validation or revision verification."""


class RepositoryOperationError(MemoryRepositoryError):
    """The repository operation failed without exposing database details."""


@dataclass(frozen=True)
class RecordRevision:
    revision: int
    payload: MemoryPayload
    status: RecordStatus
    sensitivity: Sensitivity
    mention_policy: MentionPolicy
    scope: Scope
    primary_entity_id: UUID | None
    valid_from: datetime | None
    valid_until: datetime | None
    candidate_expires_at: datetime | None
    provenance: Provenance
    reason: ChangeReason
    previous_hash: str | None
    content_hash: str
    created_at: datetime


@dataclass(frozen=True)
class MemoryRecord:
    record_id: UUID
    kind: RecordKind
    status: RecordStatus
    sensitivity: Sensitivity
    mention_policy: MentionPolicy
    scope: Scope
    primary_entity_id: UUID | None
    current_revision: int
    valid_from: datetime | None
    valid_until: datetime | None
    candidate_expires_at: datetime | None
    created_at: datetime
    updated_at: datetime
    row_version: int
    revision: RecordRevision


@dataclass(frozen=True)
class Entity:
    entity_id: UUID
    entity_type: EntityType
    status: EntityStatus
    merged_into_entity_id: UUID | None
    created_at: datetime
    updated_at: datetime
    row_version: int


@dataclass(frozen=True)
class EntityAlias:
    alias_id: UUID
    entity_id: UUID
    normalized_alias: str
    display_alias: str
    source_type: AliasSourceType
    source_ref: str
    confidence_basis: ConfidenceBasis
    created_at: datetime


@dataclass(frozen=True)
class RecordLink:
    link_id: UUID
    source_record_id: UUID
    target_record_id: UUID
    relationship: RecordRelationship
    source_type: LinkSourceType
    source_ref: str
    created_at: datetime


@dataclass(frozen=True)
class EntityLink:
    link_id: UUID
    source_entity_id: UUID
    target_entity_id: UUID
    relationship: EntityRelationship
    source_type: LinkSourceType
    source_ref: str
    created_at: datetime


@dataclass(frozen=True)
class DeletionLedgerEntry:
    purged_id: UUID
    purged_at: datetime
    reason: PurgeReason


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MemoryRepository:
    """Fixed typed operations over a verified encrypted connection provider."""

    def __init__(
        self,
        *,
        connection_provider: EncryptedConnectionProvider,
        audit_sink: AuditSink,
        clock: Callable[[], datetime] = _utc_now,
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        if not isinstance(connection_provider, EncryptedConnectionProvider):
            raise TypeError("Memory repository requires a connection provider.")
        if not isinstance(audit_sink, AuditSink):
            raise TypeError("Memory repository requires an audit sink.")
        if not callable(clock) or not callable(id_factory):
            raise TypeError("Memory repository factories must be callable.")
        self._connection_provider = connection_provider
        self._audit_sink = audit_sink
        self._clock = clock
        self._id_factory = id_factory

    def create_record(
        self,
        draft: RecordDraft,
        provenance: Provenance,
        correlation_id: UUID,
    ) -> MemoryRecord:
        self._validate_create_pair(draft, provenance)
        record_id = self._new_id()
        with self._audited(
            correlation_id,
            AuditOperation.REPOSITORY_WRITE,
            "record_create",
            record_id=record_id,
        ):
            with self._connection_provider.connect(correlation_id) as connection:
                with self._transaction(connection):
                    record = self._insert_record(
                        connection,
                        record_id,
                        draft,
                        provenance,
                        self._now(),
                    )
            return record

    def inspect_record(
        self,
        record_id: UUID,
        correlation_id: UUID,
    ) -> MemoryRecord:
        self._require_uuid(record_id, "Record ID")
        with self._audited(
            correlation_id,
            AuditOperation.REPOSITORY_READ,
            "record_inspect",
            record_id=record_id,
        ):
            with self._connection_provider.connect(correlation_id) as connection:
                return self._load_record(connection, record_id)

    def get_record_history(
        self,
        record_id: UUID,
        correlation_id: UUID,
    ) -> tuple[RecordRevision, ...]:
        self._require_uuid(record_id, "Record ID")
        with self._audited(
            correlation_id,
            AuditOperation.REPOSITORY_READ,
            "record_history",
            record_id=record_id,
        ):
            with self._connection_provider.connect(correlation_id) as connection:
                self._load_record(connection, record_id)
                rows = connection.execute(
                    "SELECT revision, payload_json, source_type, source_ref, "
                    "reason_code, actor_type, model_version, previous_hash, "
                    "content_hash, created_at FROM record_revisions "
                    "WHERE record_id = ? ORDER BY revision",
                    (str(record_id),),
                ).fetchall()
                revisions = tuple(self._revision_from_row(row) for row in rows)
                self._verify_revision_chain(revisions)
                return revisions

    def revise_record(
        self,
        record_id: UUID,
        expected_version: int,
        payload: MemoryPayload,
        provenance: Provenance,
        correlation_id: UUID,
    ) -> MemoryRecord:
        self._require_uuid(record_id, "Record ID")
        self._validate_expected_version(expected_version)
        payload_to_data(payload)
        if not isinstance(provenance, Provenance):
            raise MemoryValidationError("Memory provenance is invalid.")
        with self._audited(
            correlation_id,
            AuditOperation.REPOSITORY_WRITE,
            "record_revise",
            record_id=record_id,
        ):
            with self._connection_provider.connect(correlation_id) as connection:
                with self._transaction(connection):
                    current = self._load_record(connection, record_id)
                    self._require_version(current.row_version, expected_version)
                    if current.status in {
                        RecordStatus.SUPERSEDED,
                        RecordStatus.DELETED,
                    }:
                        raise LifecycleTransitionError(
                            "This record cannot be revised in its current state."
                        )
                    if (
                        provenance.source_type is SourceType.MODEL_CANDIDATE
                        and current.status is not RecordStatus.CANDIDATE
                    ):
                        raise LifecycleTransitionError(
                            "A model candidate cannot revise confirmed memory."
                        )
                    if self._kind_for_payload(payload) is not current.kind:
                        raise LifecycleTransitionError(
                            "A revision cannot change the record kind."
                        )
                    revised = self._append_revision(
                        connection,
                        current,
                        payload=payload,
                        status=current.status,
                        sensitivity=current.sensitivity,
                        mention_policy=current.mention_policy,
                        scope=current.scope,
                        primary_entity_id=current.primary_entity_id,
                        valid_from=current.valid_from,
                        valid_until=current.valid_until,
                        candidate_expires_at=current.candidate_expires_at,
                        provenance=provenance,
                        reason=ChangeReason.CORRECTED,
                        now=self._now(),
                    )
                    self._insert_feedback(
                        connection,
                        revised,
                        FeedbackType.EDIT,
                        self._now(),
                    )
            return revised

    def update_record_controls(
        self,
        record_id: UUID,
        expected_version: int,
        *,
        sensitivity: Sensitivity,
        mention_policy: MentionPolicy,
        scope: Scope,
        provenance: Provenance,
        correlation_id: UUID,
    ) -> MemoryRecord:
        self._require_uuid(record_id, "Record ID")
        self._validate_expected_version(expected_version)
        if not isinstance(sensitivity, Sensitivity) or sensitivity is Sensitivity.PROHIBITED:
            raise MemoryValidationError("Memory sensitivity is invalid.")
        if not isinstance(mention_policy, MentionPolicy) or not isinstance(scope, Scope):
            raise MemoryValidationError("Memory controls are invalid.")
        self._require_trusted_change_provenance(provenance)
        with self._audited(
            correlation_id,
            AuditOperation.REPOSITORY_WRITE,
            "record_controls_update",
            record_id=record_id,
        ):
            with self._connection_provider.connect(correlation_id) as connection:
                with self._transaction(connection):
                    current = self._load_record(connection, record_id)
                    self._require_version(current.row_version, expected_version)
                    if current.status in {
                        RecordStatus.SUPERSEDED,
                        RecordStatus.DELETED,
                    }:
                        raise LifecycleTransitionError(
                            "This record cannot change controls in its current state."
                        )
                    updated = self._append_revision(
                        connection,
                        current,
                        payload=current.revision.payload,
                        status=current.status,
                        sensitivity=sensitivity,
                        mention_policy=mention_policy,
                        scope=scope,
                        primary_entity_id=current.primary_entity_id,
                        valid_from=current.valid_from,
                        valid_until=current.valid_until,
                        candidate_expires_at=current.candidate_expires_at,
                        provenance=provenance,
                        reason=ChangeReason.CORRECTED,
                        now=self._now(),
                    )
            return updated

    def confirm_candidate(
        self,
        record_id: UUID,
        expected_version: int,
        provenance: Provenance,
        correlation_id: UUID,
    ) -> MemoryRecord:
        return self._transition_record(
            record_id,
            expected_version,
            required_statuses={RecordStatus.CANDIDATE},
            target_status=RecordStatus.CONFIRMED,
            provenance=provenance,
            reason=ChangeReason.CONFIRMED,
            feedback=FeedbackType.CONFIRM,
            action_kind="record_confirm",
            correlation_id=correlation_id,
        )

    def reject_candidate(
        self,
        record_id: UUID,
        expected_version: int,
        provenance: Provenance,
        correlation_id: UUID,
    ) -> MemoryRecord:
        return self._transition_record(
            record_id,
            expected_version,
            required_statuses={RecordStatus.CANDIDATE},
            target_status=RecordStatus.DELETED,
            provenance=provenance,
            reason=ChangeReason.REJECTED,
            feedback=FeedbackType.REJECT,
            action_kind="record_reject",
            correlation_id=correlation_id,
        )

    def archive_record(
        self,
        record_id: UUID,
        expected_version: int,
        provenance: Provenance,
        correlation_id: UUID,
    ) -> MemoryRecord:
        return self._transition_record(
            record_id,
            expected_version,
            required_statuses={RecordStatus.CONFIRMED},
            target_status=RecordStatus.ARCHIVED,
            provenance=provenance,
            reason=ChangeReason.ARCHIVED,
            feedback=None,
            action_kind="record_archive",
            correlation_id=correlation_id,
        )

    def restore_record(
        self,
        record_id: UUID,
        expected_version: int,
        provenance: Provenance,
        correlation_id: UUID,
    ) -> MemoryRecord:
        return self._transition_record(
            record_id,
            expected_version,
            required_statuses={RecordStatus.ARCHIVED, RecordStatus.DELETED},
            target_status=RecordStatus.CONFIRMED,
            provenance=provenance,
            reason=ChangeReason.RESTORED,
            feedback=FeedbackType.CONFIRM,
            action_kind="record_restore",
            correlation_id=correlation_id,
        )

    def delete_record(
        self,
        record_id: UUID,
        expected_version: int,
        provenance: Provenance,
        correlation_id: UUID,
    ) -> MemoryRecord:
        return self._transition_record(
            record_id,
            expected_version,
            required_statuses={
                RecordStatus.CANDIDATE,
                RecordStatus.CONFIRMED,
                RecordStatus.ARCHIVED,
            },
            target_status=RecordStatus.DELETED,
            provenance=provenance,
            reason=ChangeReason.DELETED,
            feedback=FeedbackType.DELETE,
            action_kind="record_delete",
            correlation_id=correlation_id,
        )

    def expire_candidates(
        self,
        correlation_id: UUID,
        *,
        limit: int = MAX_EXPIRY_BATCH,
    ) -> tuple[UUID, ...]:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= MAX_EXPIRY_BATCH
        ):
            raise MemoryValidationError("Candidate expiry limit is invalid.")
        with self._audited(
            correlation_id,
            AuditOperation.REPOSITORY_WRITE,
            "candidate_expire",
            item_count=limit,
        ):
            with self._connection_provider.connect(correlation_id) as connection:
                with self._transaction(connection):
                    now = self._now()
                    rows = connection.execute(
                        "SELECT record_id FROM records WHERE status = ? "
                        "AND candidate_expires_at <= ? "
                        "ORDER BY candidate_expires_at, record_id LIMIT ?",
                        (RecordStatus.CANDIDATE.value, now.isoformat(), limit),
                    ).fetchall()
                    expired_ids = tuple(UUID(row[0]) for row in rows)
                    provenance = Provenance(
                        SourceType.TRUSTED_INTERFACE,
                        "candidate-expiry-job",
                        ActorType.SYSTEM,
                    )
                    for record_id in expired_ids:
                        current = self._load_record(connection, record_id)
                        self._append_revision(
                            connection,
                            current,
                            payload=current.revision.payload,
                            status=RecordStatus.ARCHIVED,
                            sensitivity=current.sensitivity,
                            mention_policy=current.mention_policy,
                            scope=current.scope,
                            primary_entity_id=current.primary_entity_id,
                            valid_from=current.valid_from,
                            valid_until=current.valid_until,
                            candidate_expires_at=None,
                            provenance=provenance,
                            reason=ChangeReason.EXPIRED,
                            now=now,
                        )
            return expired_ids

    def supersede_record(
        self,
        record_id: UUID,
        expected_version: int,
        replacement: RecordDraft,
        provenance: Provenance,
        correlation_id: UUID,
    ) -> tuple[MemoryRecord, MemoryRecord, RecordLink]:
        self._require_uuid(record_id, "Record ID")
        self._validate_expected_version(expected_version)
        self._validate_create_pair(replacement, provenance)
        replacement_id = self._new_id()
        link_id = self._new_id()
        with self._audited(
            correlation_id,
            AuditOperation.REPOSITORY_WRITE,
            "record_supersede",
            record_id=record_id,
            item_count=2,
        ):
            with self._connection_provider.connect(correlation_id) as connection:
                with self._transaction(connection):
                    current = self._load_record(connection, record_id)
                    self._require_version(current.row_version, expected_version)
                    if current.status is not RecordStatus.CONFIRMED:
                        raise LifecycleTransitionError(
                            "Only a confirmed record can be superseded."
                        )
                    if replacement.status is not RecordStatus.CONFIRMED:
                        raise LifecycleTransitionError(
                            "A replacement record must be confirmed."
                        )
                    if replacement.kind is not current.kind:
                        raise LifecycleTransitionError(
                            "A replacement must use the same record kind."
                        )
                    now = self._now()
                    old_record = self._append_revision(
                        connection,
                        current,
                        payload=current.revision.payload,
                        status=RecordStatus.SUPERSEDED,
                        sensitivity=current.sensitivity,
                        mention_policy=current.mention_policy,
                        scope=current.scope,
                        primary_entity_id=current.primary_entity_id,
                        valid_from=current.valid_from,
                        valid_until=current.valid_until,
                        candidate_expires_at=None,
                        provenance=provenance,
                        reason=ChangeReason.SUPERSEDED,
                        now=now,
                    )
                    new_record = self._insert_record(
                        connection,
                        replacement_id,
                        replacement,
                        provenance,
                        now,
                    )
                    link = self._insert_record_link(
                        connection,
                        link_id,
                        RecordLinkDraft(
                            record_id,
                            replacement_id,
                            RecordRelationship.SUPERSESSION,
                            self._link_source_for_provenance(provenance),
                            provenance.source_ref,
                        ),
                        now,
                    )
                    self._insert_feedback(
                        connection,
                        old_record,
                        FeedbackType.EDIT,
                        now,
                    )
            return old_record, new_record, link

    def purge_record(
        self,
        record_id: UUID,
        expected_version: int,
        reason: PurgeReason,
        correlation_id: UUID,
    ) -> DeletionLedgerEntry:
        self._require_uuid(record_id, "Record ID")
        self._validate_expected_version(expected_version)
        if not isinstance(reason, PurgeReason):
            raise MemoryValidationError("Purge reason is invalid.")
        with self._audited(
            correlation_id,
            AuditOperation.REPOSITORY_WRITE,
            "record_purge",
            record_id=record_id,
        ):
            with self._connection_provider.connect(correlation_id) as connection:
                with self._transaction(connection):
                    existing = connection.execute(
                        "SELECT purged_at, reason_code FROM deletion_ledger "
                        "WHERE purged_id = ?",
                        (str(record_id),),
                    ).fetchone()
                    if existing is not None:
                        return DeletionLedgerEntry(
                            record_id,
                            self._parse_datetime(existing[0]),
                            PurgeReason(existing[1]),
                        )
                    current = self._load_record(connection, record_id)
                    self._require_version(current.row_version, expected_version)
                    now = self._now()
                    connection.execute(
                        "DELETE FROM records WHERE record_id = ?",
                        (str(record_id),),
                    )
                    connection.execute(
                        "INSERT INTO deletion_ledger "
                        "(purged_id, purged_at, reason_code) VALUES (?, ?, ?)",
                        (str(record_id), now.isoformat(), reason.value),
                    )
                    entry = DeletionLedgerEntry(record_id, now, reason)
            return entry

    def is_purged(self, record_id: UUID, correlation_id: UUID) -> bool:
        self._require_uuid(record_id, "Record ID")
        with self._audited(
            correlation_id,
            AuditOperation.REPOSITORY_READ,
            "purge_ledger_check",
            record_id=record_id,
        ):
            with self._connection_provider.connect(correlation_id) as connection:
                row = connection.execute(
                    "SELECT 1 FROM deletion_ledger WHERE purged_id = ?",
                    (str(record_id),),
                ).fetchone()
                return row is not None

    def create_entity(
        self,
        draft: EntityDraft,
        correlation_id: UUID,
    ) -> Entity:
        if not isinstance(draft, EntityDraft):
            raise MemoryValidationError("Entity draft is invalid.")
        entity_id = self._new_id()
        with self._audited(
            correlation_id,
            AuditOperation.REPOSITORY_WRITE,
            "entity_create",
            entity_id=entity_id,
        ):
            with self._connection_provider.connect(correlation_id) as connection:
                with self._transaction(connection):
                    now = self._now()
                    connection.execute(
                        "INSERT INTO entities "
                        "(entity_id, entity_type, status, merged_into_entity_id, "
                        "created_at, updated_at, row_version) "
                        "VALUES (?, ?, ?, NULL, ?, ?, 1)",
                        (
                            str(entity_id),
                            draft.entity_type.value,
                            EntityStatus.ACTIVE.value,
                            now.isoformat(),
                            now.isoformat(),
                        ),
                    )
                    entity = Entity(
                        entity_id,
                        draft.entity_type,
                        EntityStatus.ACTIVE,
                        None,
                        now,
                        now,
                        1,
                    )
            return entity

    def add_entity_alias(
        self,
        entity_id: UUID,
        draft: AliasDraft,
        correlation_id: UUID,
    ) -> EntityAlias:
        self._require_uuid(entity_id, "Entity ID")
        if not isinstance(draft, AliasDraft):
            raise MemoryValidationError("Alias draft is invalid.")
        if draft.source_type is AliasSourceType.MODEL_CANDIDATE:
            raise MemoryValidationError(
                "Model-suggested aliases require a future review workflow."
            )
        alias_id = self._new_id()
        with self._audited(
            correlation_id,
            AuditOperation.REPOSITORY_WRITE,
            "entity_alias_create",
            entity_id=entity_id,
        ):
            with self._connection_provider.connect(correlation_id) as connection:
                with self._transaction(connection):
                    self._require_active_entity(connection, entity_id)
                    normalized = normalize_alias(draft.display_alias)
                    existing = connection.execute(
                        "SELECT 1 FROM entity_aliases "
                        "WHERE entity_id = ? AND normalized_alias = ?",
                        (str(entity_id), normalized),
                    ).fetchone()
                    if existing is not None:
                        raise RepositoryConflictError(
                            "This entity already has that exact alias."
                        )
                    now = self._now()
                    connection.execute(
                        "INSERT INTO entity_aliases "
                        "(alias_id, entity_id, normalized_alias, display_alias, "
                        "source_type, source_ref, confidence_basis, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            str(alias_id),
                            str(entity_id),
                            normalized,
                            draft.display_alias,
                            draft.source_type.value,
                            draft.source_ref,
                            draft.confidence_basis.value,
                            now.isoformat(),
                        ),
                    )
                    alias = EntityAlias(
                        alias_id,
                        entity_id,
                        normalized,
                        draft.display_alias,
                        draft.source_type,
                        draft.source_ref,
                        draft.confidence_basis,
                        now,
                    )
            return alias

    def find_entities_by_alias(
        self,
        alias: str,
        correlation_id: UUID,
    ) -> tuple[Entity, ...]:
        normalized = normalize_alias(alias)
        with self._audited(
            correlation_id,
            AuditOperation.REPOSITORY_READ,
            "entity_alias_lookup",
        ):
            with self._connection_provider.connect(correlation_id) as connection:
                rows = connection.execute(
                    "SELECT e.entity_id, e.entity_type, e.status, "
                    "e.merged_into_entity_id, e.created_at, e.updated_at, "
                    "e.row_version FROM entity_aliases a "
                    "JOIN entities e ON e.entity_id = a.entity_id "
                    "WHERE a.normalized_alias = ? AND e.status = ? "
                    "ORDER BY e.entity_id LIMIT 32",
                    (normalized, EntityStatus.ACTIVE.value),
                ).fetchall()
                return tuple(self._entity_from_row(row) for row in rows)

    def archive_entity(
        self,
        entity_id: UUID,
        expected_version: int,
        correlation_id: UUID,
    ) -> Entity:
        self._require_uuid(entity_id, "Entity ID")
        self._validate_expected_version(expected_version)
        with self._audited(
            correlation_id,
            AuditOperation.REPOSITORY_WRITE,
            "entity_archive",
            entity_id=entity_id,
        ):
            with self._connection_provider.connect(correlation_id) as connection:
                with self._transaction(connection):
                    entity = self._load_entity(connection, entity_id)
                    self._require_version(entity.row_version, expected_version)
                    if entity.status is not EntityStatus.ACTIVE:
                        raise LifecycleTransitionError(
                            "Only an active entity can be archived."
                        )
                    now = self._now()
                    cursor = connection.execute(
                        "UPDATE entities SET status = ?, updated_at = ?, "
                        "row_version = row_version + 1 "
                        "WHERE entity_id = ? AND row_version = ?",
                        (
                            EntityStatus.ARCHIVED.value,
                            now.isoformat(),
                            str(entity_id),
                            expected_version,
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise RepositoryConflictError(
                            "Entity changed before the update completed."
                        )
                    archived = Entity(
                        entity.entity_id,
                        entity.entity_type,
                        EntityStatus.ARCHIVED,
                        None,
                        entity.created_at,
                        now,
                        entity.row_version + 1,
                    )
            return archived

    def create_record_link(
        self,
        draft: RecordLinkDraft,
        correlation_id: UUID,
    ) -> RecordLink:
        if not isinstance(draft, RecordLinkDraft):
            raise MemoryValidationError("Record link draft is invalid.")
        link_id = self._new_id()
        with self._audited(
            correlation_id,
            AuditOperation.REPOSITORY_WRITE,
            "record_link_create",
            link_id=link_id,
        ):
            with self._connection_provider.connect(correlation_id) as connection:
                with self._transaction(connection):
                    link = self._insert_record_link(
                        connection,
                        link_id,
                        draft,
                        self._now(),
                    )
            return link

    def create_entity_link(
        self,
        draft: EntityLinkDraft,
        correlation_id: UUID,
    ) -> EntityLink:
        if not isinstance(draft, EntityLinkDraft):
            raise MemoryValidationError("Entity link draft is invalid.")
        if draft.source_type is LinkSourceType.MODEL_CANDIDATE:
            raise MemoryValidationError(
                "Model-suggested entity links require a future review workflow."
            )
        link_id = self._new_id()
        with self._audited(
            correlation_id,
            AuditOperation.REPOSITORY_WRITE,
            "entity_link_create",
            link_id=link_id,
        ):
            with self._connection_provider.connect(correlation_id) as connection:
                with self._transaction(connection):
                    self._require_active_entity(connection, draft.source_entity_id)
                    self._require_active_entity(connection, draft.target_entity_id)
                    now = self._now()
                    existing = connection.execute(
                        "SELECT 1 FROM entity_links WHERE source_entity_id = ? "
                        "AND target_entity_id = ? AND relationship = ?",
                        (
                            str(draft.source_entity_id),
                            str(draft.target_entity_id),
                            draft.relationship.value,
                        ),
                    ).fetchone()
                    if existing is not None:
                        raise RepositoryConflictError(
                            "This exact entity link already exists."
                        )
                    connection.execute(
                        "INSERT INTO entity_links "
                        "(link_id, source_entity_id, target_entity_id, relationship, "
                        "source_type, source_ref, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            str(link_id),
                            str(draft.source_entity_id),
                            str(draft.target_entity_id),
                            draft.relationship.value,
                            draft.source_type.value,
                            draft.source_ref,
                            now.isoformat(),
                        ),
                    )
                    link = EntityLink(
                        link_id,
                        draft.source_entity_id,
                        draft.target_entity_id,
                        draft.relationship,
                        draft.source_type,
                        draft.source_ref,
                        now,
                    )
            return link

    def _transition_record(
        self,
        record_id: UUID,
        expected_version: int,
        *,
        required_statuses: set[RecordStatus],
        target_status: RecordStatus,
        provenance: Provenance,
        reason: ChangeReason,
        feedback: FeedbackType | None,
        action_kind: str,
        correlation_id: UUID,
    ) -> MemoryRecord:
        self._require_uuid(record_id, "Record ID")
        self._validate_expected_version(expected_version)
        if not isinstance(provenance, Provenance):
            raise MemoryValidationError("Memory provenance is invalid.")
        self._require_trusted_change_provenance(provenance)
        with self._audited(
            correlation_id,
            AuditOperation.REPOSITORY_WRITE,
            action_kind,
            record_id=record_id,
        ):
            with self._connection_provider.connect(correlation_id) as connection:
                with self._transaction(connection):
                    current = self._load_record(connection, record_id)
                    self._require_version(current.row_version, expected_version)
                    if current.status not in required_statuses:
                        raise LifecycleTransitionError(
                            "This record state transition is not allowed."
                        )
                    if (
                        target_status is RecordStatus.CONFIRMED
                        and isinstance(current.revision.payload, InsightPayload)
                    ):
                        evidence_count = connection.execute(
                            "SELECT count(DISTINCT target_record_id) FROM record_links "
                            "WHERE source_record_id = ? AND relationship = ?",
                            (str(record_id), RecordRelationship.EVIDENCE.value),
                        ).fetchone()[0]
                        if evidence_count < MINIMUM_INSIGHT_EVIDENCE:
                            raise LifecycleTransitionError(
                                "An insight needs at least three evidence records."
                            )
                    expiry = (
                        current.candidate_expires_at
                        if target_status is RecordStatus.CANDIDATE
                        else None
                    )
                    updated = self._append_revision(
                        connection,
                        current,
                        payload=current.revision.payload,
                        status=target_status,
                        sensitivity=current.sensitivity,
                        mention_policy=current.mention_policy,
                        scope=current.scope,
                        primary_entity_id=current.primary_entity_id,
                        valid_from=current.valid_from,
                        valid_until=current.valid_until,
                        candidate_expires_at=expiry,
                        provenance=provenance,
                        reason=reason,
                        now=self._now(),
                    )
                    if feedback is not None:
                        self._insert_feedback(
                            connection,
                            updated,
                            feedback,
                            self._now(),
                        )
            return updated

    def _insert_record(
        self,
        connection: Any,
        record_id: UUID,
        draft: RecordDraft,
        provenance: Provenance,
        now: datetime,
    ) -> MemoryRecord:
        if connection.execute(
            "SELECT 1 FROM deletion_ledger WHERE purged_id = ?",
            (str(record_id),),
        ).fetchone() is not None:
            raise RepositoryConflictError("Generated record ID is permanently purged.")
        if draft.primary_entity_id is not None:
            self._require_active_entity(connection, draft.primary_entity_id)
        expiry = now + CANDIDATE_LIFETIME if draft.status is RecordStatus.CANDIDATE else None
        snapshot = self._snapshot_json(
            kind=draft.kind,
            payload=draft.payload,
            status=draft.status,
            sensitivity=draft.sensitivity,
            mention_policy=draft.mention_policy,
            scope=draft.scope,
            primary_entity_id=draft.primary_entity_id,
            valid_from=draft.valid_from,
            valid_until=draft.valid_until,
            candidate_expires_at=expiry,
        )
        content_hash = sha256(snapshot.encode("utf-8")).hexdigest()
        connection.execute(
            "INSERT INTO records "
            "(record_id, kind, status, sensitivity, mention_policy, scope_type, "
            "scope_id, primary_entity_id, current_revision, valid_from, valid_until, "
            "candidate_expires_at, created_at, updated_at, row_version) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, 1)",
            (
                str(record_id),
                draft.kind.value,
                draft.status.value,
                draft.sensitivity.value,
                draft.mention_policy.value,
                draft.scope.type.value,
                None if draft.scope.id is None else str(draft.scope.id),
                None if draft.primary_entity_id is None else str(draft.primary_entity_id),
                self._format_datetime(draft.valid_from),
                self._format_datetime(draft.valid_until),
                self._format_datetime(expiry),
                now.isoformat(),
                now.isoformat(),
            ),
        )
        self._insert_revision_row(
            connection,
            record_id,
            1,
            snapshot,
            provenance,
            ChangeReason.CREATED,
            None,
            content_hash,
            now,
        )
        return self._load_record(connection, record_id)

    def _append_revision(
        self,
        connection: Any,
        current: MemoryRecord,
        *,
        payload: MemoryPayload,
        status: RecordStatus,
        sensitivity: Sensitivity,
        mention_policy: MentionPolicy,
        scope: Scope,
        primary_entity_id: UUID | None,
        valid_from: datetime | None,
        valid_until: datetime | None,
        candidate_expires_at: datetime | None,
        provenance: Provenance,
        reason: ChangeReason,
        now: datetime,
    ) -> MemoryRecord:
        if primary_entity_id is not None:
            self._require_active_entity(connection, primary_entity_id)
        revision = current.current_revision + 1
        snapshot = self._snapshot_json(
            kind=current.kind,
            payload=payload,
            status=status,
            sensitivity=sensitivity,
            mention_policy=mention_policy,
            scope=scope,
            primary_entity_id=primary_entity_id,
            valid_from=valid_from,
            valid_until=valid_until,
            candidate_expires_at=candidate_expires_at,
        )
        content_hash = sha256(snapshot.encode("utf-8")).hexdigest()
        self._insert_revision_row(
            connection,
            current.record_id,
            revision,
            snapshot,
            provenance,
            reason,
            current.revision.content_hash,
            content_hash,
            now,
        )
        cursor = connection.execute(
            "UPDATE records SET status = ?, sensitivity = ?, mention_policy = ?, "
            "scope_type = ?, scope_id = ?, primary_entity_id = ?, "
            "current_revision = ?, valid_from = ?, valid_until = ?, "
            "candidate_expires_at = ?, updated_at = ?, row_version = row_version + 1 "
            "WHERE record_id = ? AND row_version = ?",
            (
                status.value,
                sensitivity.value,
                mention_policy.value,
                scope.type.value,
                None if scope.id is None else str(scope.id),
                None if primary_entity_id is None else str(primary_entity_id),
                revision,
                self._format_datetime(valid_from),
                self._format_datetime(valid_until),
                self._format_datetime(candidate_expires_at),
                now.isoformat(),
                str(current.record_id),
                current.row_version,
            ),
        )
        if cursor.rowcount != 1:
            raise RepositoryConflictError(
                "Record changed before the update completed."
            )
        return self._load_record(connection, current.record_id)

    @staticmethod
    def _insert_revision_row(
        connection: Any,
        record_id: UUID,
        revision: int,
        snapshot: str,
        provenance: Provenance,
        reason: ChangeReason,
        previous_hash: str | None,
        content_hash: str,
        now: datetime,
    ) -> None:
        connection.execute(
            "INSERT INTO record_revisions "
            "(record_id, revision, payload_version, payload_json, source_type, "
            "source_ref, reason_code, actor_type, model_version, previous_hash, "
            "content_hash, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(record_id),
                revision,
                PAYLOAD_VERSION,
                snapshot,
                provenance.source_type.value,
                provenance.source_ref,
                reason.value,
                provenance.actor_type.value,
                provenance.model_version,
                previous_hash,
                content_hash,
                now.isoformat(),
            ),
        )

    def _insert_record_link(
        self,
        connection: Any,
        link_id: UUID,
        draft: RecordLinkDraft,
        now: datetime,
    ) -> RecordLink:
        source = self._load_record(connection, draft.source_record_id)
        target = self._load_record(connection, draft.target_record_id)
        if RecordStatus.DELETED in {source.status, target.status}:
            raise LifecycleTransitionError("Deleted records cannot receive new links.")
        if (
            draft.source_type is LinkSourceType.MODEL_CANDIDATE
            and source.status is not RecordStatus.CANDIDATE
        ):
            raise LifecycleTransitionError(
                "Model-suggested links must originate from a candidate record."
            )
        existing = connection.execute(
            "SELECT 1 FROM record_links WHERE source_record_id = ? "
            "AND target_record_id = ? AND relationship = ?",
            (
                str(draft.source_record_id),
                str(draft.target_record_id),
                draft.relationship.value,
            ),
        ).fetchone()
        if existing is not None:
            raise RepositoryConflictError("This exact record link already exists.")
        connection.execute(
            "INSERT INTO record_links "
            "(link_id, source_record_id, target_record_id, relationship, "
            "source_type, source_ref, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                str(link_id),
                str(draft.source_record_id),
                str(draft.target_record_id),
                draft.relationship.value,
                draft.source_type.value,
                draft.source_ref,
                now.isoformat(),
            ),
        )
        return RecordLink(
            link_id,
            draft.source_record_id,
            draft.target_record_id,
            draft.relationship,
            draft.source_type,
            draft.source_ref,
            now,
        )

    def _insert_feedback(
        self,
        connection: Any,
        record: MemoryRecord,
        feedback_type: FeedbackType,
        now: datetime,
    ) -> None:
        feedback_id = self._new_id()
        connection.execute(
            "INSERT INTO memory_feedback "
            "(feedback_id, record_id, feedback_type, memory_kind, scoring_label, "
            "created_at) VALUES (?, ?, ?, ?, NULL, ?)",
            (
                str(feedback_id),
                str(record.record_id),
                feedback_type.value,
                record.kind.value,
                now.isoformat(),
            ),
        )

    def _load_record(self, connection: Any, record_id: UUID) -> MemoryRecord:
        row = connection.execute(
            "SELECT r.record_id, r.kind, r.status, r.sensitivity, "
            "r.mention_policy, r.scope_type, r.scope_id, r.primary_entity_id, "
            "r.current_revision, r.valid_from, r.valid_until, "
            "r.candidate_expires_at, r.created_at, r.updated_at, r.row_version, "
            "v.revision, v.payload_json, v.source_type, v.source_ref, "
            "v.reason_code, v.actor_type, v.model_version, v.previous_hash, "
            "v.content_hash, v.created_at "
            "FROM records r JOIN record_revisions v "
            "ON v.record_id = r.record_id AND v.revision = r.current_revision "
            "WHERE r.record_id = ?",
            (str(record_id),),
        ).fetchone()
        if row is None:
            if connection.execute(
                "SELECT 1 FROM deletion_ledger WHERE purged_id = ?",
                (str(record_id),),
            ).fetchone() is not None:
                raise RecordNotFoundError("The record was permanently purged.")
            raise RecordNotFoundError("The record does not exist.")
        try:
            revision = self._revision_from_row(row[15:])
            record = MemoryRecord(
                UUID(row[0]),
                RecordKind(row[1]),
                RecordStatus(row[2]),
                Sensitivity(row[3]),
                MentionPolicy(row[4]),
                Scope(ScopeType(row[5]), None if row[6] is None else UUID(row[6])),
                None if row[7] is None else UUID(row[7]),
                row[8],
                self._parse_optional_datetime(row[9]),
                self._parse_optional_datetime(row[10]),
                self._parse_optional_datetime(row[11]),
                self._parse_datetime(row[12]),
                self._parse_datetime(row[13]),
                row[14],
                revision,
            )
        except (MemoryValidationError, TypeError, ValueError) as error:
            raise RepositoryIntegrityError("Stored record is invalid.") from error
        self._verify_record_snapshot(record)
        return record

    def _revision_from_row(self, row: Any) -> RecordRevision:
        try:
            revision_number = row[0]
            snapshot_text = row[1]
            if not isinstance(snapshot_text, str):
                raise ValueError
            snapshot = json.loads(snapshot_text)
            if not isinstance(snapshot, dict) or snapshot.get("schema_version") != 1:
                raise ValueError
            required = {
                "schema_version",
                "kind",
                "status",
                "sensitivity",
                "mention_policy",
                "scope_type",
                "scope_id",
                "primary_entity_id",
                "valid_from",
                "valid_until",
                "candidate_expires_at",
                "payload",
            }
            if set(snapshot) != required:
                raise ValueError
            kind = RecordKind(snapshot["kind"])
            payload = payload_from_data(snapshot["payload"])
            if self._kind_for_payload(payload) is not kind:
                raise ValueError
            stored_hash = row[8]
            if sha256(snapshot_text.encode("utf-8")).hexdigest() != stored_hash:
                raise ValueError
            return RecordRevision(
                revision_number,
                payload,
                RecordStatus(snapshot["status"]),
                Sensitivity(snapshot["sensitivity"]),
                MentionPolicy(snapshot["mention_policy"]),
                Scope(
                    ScopeType(snapshot["scope_type"]),
                    None if snapshot["scope_id"] is None else UUID(snapshot["scope_id"]),
                ),
                None
                if snapshot["primary_entity_id"] is None
                else UUID(snapshot["primary_entity_id"]),
                self._parse_optional_datetime(snapshot["valid_from"]),
                self._parse_optional_datetime(snapshot["valid_until"]),
                self._parse_optional_datetime(snapshot["candidate_expires_at"]),
                Provenance(
                    SourceType(row[2]),
                    row[3],
                    ActorType(row[5]),
                    row[6],
                ),
                ChangeReason(row[4]),
                row[7],
                stored_hash,
                self._parse_datetime(row[9]),
            )
        except (
            json.JSONDecodeError,
            KeyError,
            MemoryValidationError,
            TypeError,
            ValueError,
        ) as error:
            raise RepositoryIntegrityError("Stored revision is invalid.") from error

    @staticmethod
    def _verify_revision_chain(revisions: tuple[RecordRevision, ...]) -> None:
        if not revisions:
            raise RepositoryIntegrityError("Record has no revision history.")
        prior_hash: str | None = None
        for expected, revision in enumerate(revisions, start=1):
            if revision.revision != expected or revision.previous_hash != prior_hash:
                raise RepositoryIntegrityError("Record revision chain is invalid.")
            prior_hash = revision.content_hash

    @staticmethod
    def _verify_record_snapshot(record: MemoryRecord) -> None:
        revision = record.revision
        if (
            revision.revision != record.current_revision
            or MemoryRepository._kind_for_payload(revision.payload) is not record.kind
            or revision.status is not record.status
            or revision.sensitivity is not record.sensitivity
            or revision.mention_policy is not record.mention_policy
            or revision.scope != record.scope
            or revision.primary_entity_id != record.primary_entity_id
            or revision.valid_from != record.valid_from
            or revision.valid_until != record.valid_until
            or revision.candidate_expires_at != record.candidate_expires_at
        ):
            raise RepositoryIntegrityError("Current record and revision do not match.")

    def _load_entity(self, connection: Any, entity_id: UUID) -> Entity:
        row = connection.execute(
            "SELECT entity_id, entity_type, status, merged_into_entity_id, "
            "created_at, updated_at, row_version FROM entities WHERE entity_id = ?",
            (str(entity_id),),
        ).fetchone()
        if row is None:
            raise EntityNotFoundError("The entity does not exist.")
        return self._entity_from_row(row)

    def _require_active_entity(self, connection: Any, entity_id: UUID) -> Entity:
        entity = self._load_entity(connection, entity_id)
        if entity.status is not EntityStatus.ACTIVE:
            raise LifecycleTransitionError("The entity is not active.")
        return entity

    def _entity_from_row(self, row: Any) -> Entity:
        try:
            return Entity(
                UUID(row[0]),
                EntityType(row[1]),
                EntityStatus(row[2]),
                None if row[3] is None else UUID(row[3]),
                self._parse_datetime(row[4]),
                self._parse_datetime(row[5]),
                row[6],
            )
        except (TypeError, ValueError) as error:
            raise RepositoryIntegrityError("Stored entity is invalid.") from error

    @staticmethod
    def _snapshot_json(
        *,
        kind: RecordKind,
        payload: MemoryPayload,
        status: RecordStatus,
        sensitivity: Sensitivity,
        mention_policy: MentionPolicy,
        scope: Scope,
        primary_entity_id: UUID | None,
        valid_from: datetime | None,
        valid_until: datetime | None,
        candidate_expires_at: datetime | None,
    ) -> str:
        return canonical_json(
            {
                "schema_version": PAYLOAD_VERSION,
                "kind": kind.value,
                "status": status.value,
                "sensitivity": sensitivity.value,
                "mention_policy": mention_policy.value,
                "scope_type": scope.type.value,
                "scope_id": None if scope.id is None else str(scope.id),
                "primary_entity_id": (
                    None if primary_entity_id is None else str(primary_entity_id)
                ),
                "valid_from": MemoryRepository._format_datetime(valid_from),
                "valid_until": MemoryRepository._format_datetime(valid_until),
                "candidate_expires_at": MemoryRepository._format_datetime(
                    candidate_expires_at
                ),
                "payload": payload_to_data(payload),
            }
        )

    @staticmethod
    def _validate_create_pair(draft: RecordDraft, provenance: Provenance) -> None:
        if not isinstance(draft, RecordDraft) or not isinstance(provenance, Provenance):
            raise MemoryValidationError("Memory draft or provenance is invalid.")
        if provenance.source_type is SourceType.MODEL_CANDIDATE:
            if draft.status is not RecordStatus.CANDIDATE:
                raise MemoryValidationError("Model output can create candidates only.")
        elif draft.status is RecordStatus.CANDIDATE:
            raise MemoryValidationError("Candidates require model-candidate provenance.")
        if isinstance(draft.payload, InsightPayload) and (
            draft.status is RecordStatus.CONFIRMED
        ):
            raise MemoryValidationError(
                "Insights must begin as candidates and collect evidence."
            )
        if provenance.source_type is SourceType.EXPLICIT_USER and (
            provenance.actor_type is not ActorType.USER
            or draft.status is not RecordStatus.CONFIRMED
        ):
            raise MemoryValidationError("Explicit user memory must be confirmed.")

    @staticmethod
    def _kind_for_payload(payload: MemoryPayload) -> RecordKind:
        return RecordDraft(
            payload,
            RecordStatus.CONFIRMED,
            Sensitivity.NORMAL,
            MentionPolicy.MAY_MENTION_WHEN_RELEVANT,
            Scope(ScopeType.GLOBAL),
        ).kind

    @staticmethod
    def _require_trusted_change_provenance(provenance: Provenance) -> None:
        if not isinstance(provenance, Provenance):
            raise MemoryValidationError("Memory provenance is invalid.")
        if provenance.source_type is SourceType.MODEL_CANDIDATE:
            raise MemoryValidationError(
                "Model candidates cannot change an existing memory directly."
            )

    @staticmethod
    def _link_source_for_provenance(provenance: Provenance) -> LinkSourceType:
        if provenance.source_type is SourceType.EXPLICIT_USER:
            return LinkSourceType.EXPLICIT_USER
        if provenance.source_type is SourceType.TRUSTED_INTERFACE:
            return LinkSourceType.TRUSTED_INTERFACE
        return LinkSourceType.DETERMINISTIC_RULE

    @staticmethod
    def _require_uuid(value: UUID, label: str) -> None:
        if not isinstance(value, UUID):
            raise MemoryValidationError(f"{label} must be a UUID.")

    @staticmethod
    def _validate_expected_version(value: int) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise MemoryValidationError("Expected version must be a positive integer.")

    @staticmethod
    def _require_version(current: int, expected: int) -> None:
        if current != expected:
            raise RepositoryConflictError("Record version does not match.")

    def _new_id(self) -> UUID:
        value = self._id_factory()
        if not isinstance(value, UUID):
            raise RepositoryOperationError("ID generator returned an invalid value.")
        return value

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise RepositoryOperationError("Clock returned an invalid time.")
        if value.utcoffset() is None:
            raise RepositoryOperationError("Clock returned an invalid time.")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _format_datetime(value: datetime | None) -> str | None:
        return None if value is None else value.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _parse_datetime(value: object) -> datetime:
        if not isinstance(value, str):
            raise ValueError("Timestamp is invalid.")
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("Timestamp is invalid.")
        return parsed

    @staticmethod
    def _parse_optional_datetime(value: object) -> datetime | None:
        return None if value is None else MemoryRepository._parse_datetime(value)

    @staticmethod
    @contextmanager
    def _transaction(connection: Any) -> Iterator[None]:
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield
            connection.commit()
        except Exception:
            try:
                connection.rollback()
            except Exception:
                pass
            raise

    @contextmanager
    def _audited(
        self,
        correlation_id: UUID,
        operation: AuditOperation,
        action_kind: str,
        *,
        record_id: UUID | None = None,
        entity_id: UUID | None = None,
        link_id: UUID | None = None,
        item_count: int | None = None,
    ) -> Iterator[None]:
        self._require_uuid(correlation_id, "Correlation ID")
        started = monotonic()
        metadata = [
            AuditMetadataItem(AuditMetadataKey.ACTION_KIND, action_kind),
            AuditMetadataItem(AuditMetadataKey.TARGET_CLASS, "encrypted_memory"),
        ]
        if record_id is not None:
            metadata.append(
                AuditMetadataItem(AuditMetadataKey.RECORD_ID, str(record_id))
            )
        if entity_id is not None:
            metadata.append(
                AuditMetadataItem(AuditMetadataKey.ENTITY_ID, str(entity_id))
            )
        if link_id is not None:
            metadata.append(AuditMetadataItem(AuditMetadataKey.LINK_ID, str(link_id)))
        if item_count is not None:
            metadata.append(
                AuditMetadataItem(AuditMetadataKey.ITEM_COUNT, item_count)
            )
        self._emit(
            correlation_id,
            operation,
            AuditOutcome.STARTED,
            AuditReasonCode.NORMAL,
            tuple(metadata),
            started,
        )
        try:
            yield
        except MemoryRepositoryError as error:
            if isinstance(error, RepositoryConflictError):
                reason = AuditReasonCode.VERSION_CONFLICT
            elif isinstance(error, (RecordNotFoundError, EntityNotFoundError)):
                reason = AuditReasonCode.RECORD_NOT_FOUND
            elif isinstance(error, LifecycleTransitionError):
                reason = AuditReasonCode.LIFECYCLE_BLOCKED
            elif isinstance(error, RepositoryIntegrityError):
                reason = AuditReasonCode.INTEGRITY_FAILED
            else:
                reason = AuditReasonCode.SAFE_INTERNAL_FAILURE
            self._emit(
                correlation_id,
                operation,
                AuditOutcome.FAILED,
                reason,
                tuple(metadata),
                started,
            )
            raise
        except Exception as error:
            self._emit(
                correlation_id,
                operation,
                AuditOutcome.FAILED,
                AuditReasonCode.SAFE_INTERNAL_FAILURE,
                tuple(metadata),
                started,
            )
            raise RepositoryOperationError(
                "Memory repository operation failed safely."
            ) from error
        else:
            self._emit(
                correlation_id,
                operation,
                AuditOutcome.SUCCEEDED,
                AuditReasonCode.NORMAL,
                tuple(metadata),
                started,
            )

    def _emit(
        self,
        correlation_id: UUID,
        operation: AuditOperation,
        outcome: AuditOutcome,
        reason: AuditReasonCode,
        metadata: tuple[AuditMetadataItem, ...],
        started: float,
    ) -> None:
        self._audit_sink.write(
            AuditEvent(
                correlation_id=correlation_id,
                component=AuditComponent.DATABASE,
                operation=operation,
                outcome=outcome,
                reason_code=reason,
                metadata=metadata,
                duration_ms=max(0, int((monotonic() - started) * 1_000)),
            )
        )
