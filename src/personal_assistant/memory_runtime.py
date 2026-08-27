"""Compose encrypted persistence components for the trusted local runtime."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable
from uuid import UUID, uuid4

from personal_assistant.audit import AuditSink
from personal_assistant.assistant_preferences import (
    EncryptedAssistantPreferenceStore,
)
from personal_assistant.authorization import authorize_action
from personal_assistant.audit_file import AuditFileSettings, JsonLinesAuditSink
from personal_assistant.backup import (
    BackupSettings,
    BackupSnapshot,
    EncryptedBackupManager,
)
from personal_assistant.config import MemorySettings
from personal_assistant.conversation_history import ConversationHistoryRepository
from personal_assistant.encrypted_database import (
    EncryptedDatabase,
    EncryptedDatabaseSettings,
)
from personal_assistant.memory_capture import (
    CaptureDecision,
    ExplicitMemoryRequest,
    MemoryCaptureCoordinator,
)
from personal_assistant.memory_context import RepositoryMemoryContextProvider
from personal_assistant.memory_repository import MemoryRecord, MemoryRepository
from personal_assistant.memory_scopes import (
    detect_explicit_named_scope,
    named_scope_needs_clarification,
)
from personal_assistant.retrieval_language import safe_topic_labels
from personal_assistant.memory_types import (
    ActorType,
    FactPayload,
    MemoryValidationError,
    MentionPolicy,
    Provenance,
    Scope,
    ScopeType,
    Sensitivity,
    SourceType,
)
from personal_assistant.migration import MigrationRunner, PackageMigrationSource
from personal_assistant.permissions import ActionKind
from personal_assistant.portable_security import (
    PasscodeApprovalGate,
    PortableSecurityManager,
    PortableSecuritySettings,
    SessionDatabaseKeyProvider,
)


@runtime_checkable
class ExplicitMemoryHandler(Protocol):
    """Handle a user instruction intercepted before model submission."""

    def remember(
        self,
        content: str,
        correlation_id: UUID,
        *,
        source_ref: str | None = None,
    ) -> str:
        """Return a fixed user-facing outcome without echoing content."""


@dataclass
class MemoryRuntime:
    """Owned runtime components and lifecycle for one unlocked session."""

    settings: MemorySettings
    security: PortableSecurityManager
    key_provider: SessionDatabaseKeyProvider
    audit_sink: AuditSink
    database: EncryptedDatabase
    repository: MemoryRepository
    conversation_history: ConversationHistoryRepository
    assistant_preferences: EncryptedAssistantPreferenceStore
    capture: MemoryCaptureCoordinator
    context_provider: RepositoryMemoryContextProvider
    approval_gate: PasscodeApprovalGate
    backup_manager: EncryptedBackupManager | None

    @classmethod
    def open(
        cls,
        settings: MemorySettings,
        recovery_passphrase: str,
        *,
        audit_sink: AuditSink | None = None,
        create_database: bool = False,
    ) -> "MemoryRuntime":
        """Unlock, migrate, expire candidates, and compose runtime adapters."""

        if not isinstance(settings, MemorySettings) or not settings.enabled:
            raise ValueError("Persistent memory runtime is not enabled.")
        if not isinstance(create_database, bool):
            raise ValueError("Database creation policy must be explicit.")
        sink = audit_sink or JsonLinesAuditSink(
            AuditFileSettings(settings.data_directory / "audit.jsonl")
        )
        security = PortableSecurityManager(
            PortableSecuritySettings(settings.data_directory / "security.json"),
            audit_sink=sink,
        )
        key_provider = security.unlock(recovery_passphrase, uuid4())
        try:
            database_path = settings.data_directory / "memory.db"
            database = EncryptedDatabase(
                EncryptedDatabaseSettings(
                    database_path,
                    "primary-memory-key",
                    require_existing=not create_database,
                ),
                key_provider=key_provider,
                audit_sink=sink,
            )
            migrations = PackageMigrationSource()
            MigrationRunner(
                connection_provider=database,
                migration_source=migrations,
                audit_sink=sink,
            ).migrate(uuid4())
            repository = MemoryRepository(
                connection_provider=database,
                audit_sink=sink,
            )
            conversation_history = ConversationHistoryRepository(database, sink)
            assistant_preferences = EncryptedAssistantPreferenceStore(
                database,
                sink,
            )
            repository.expire_candidates(uuid4())
            capture = MemoryCaptureCoordinator(repository, sink)
            context = RepositoryMemoryContextProvider(
                repository,
                token_limit=settings.context_tokens,
            )
            approval_gate = PasscodeApprovalGate(
                security,
                audit_sink=sink,
                state_path=settings.data_directory / "approval-rate-limit.json",
            )
            backup_manager = None
            if settings.backup_directory is not None:
                backup_manager = EncryptedBackupManager(
                    BackupSettings(database_path, settings.backup_directory),
                    live_database=database,
                    database_factory=lambda path: EncryptedDatabase(
                        EncryptedDatabaseSettings(path, "primary-memory-key"),
                        key_provider=key_provider,
                        audit_sink=sink,
                    ),
                    migration_source=migrations,
                    audit_sink=sink,
                )
            return cls(
                settings,
                security,
                key_provider,
                sink,
                database,
                repository,
                conversation_history,
                assistant_preferences,
                capture,
                context,
                approval_gate,
                backup_manager,
            )
        except Exception:
            key_provider.close()
            raise

    def remember(
        self,
        content: str,
        correlation_id: UUID,
        *,
        source_ref: str | None = None,
    ) -> str:
        """Persist one explicit low-risk fact or return a safe fixed outcome."""

        normalized = " ".join(content.split())
        if not normalized:
            return "Usage: /remember <information to remember>"
        if named_scope_needs_clarification(normalized):
            return (
                "Memory needs clarification: the statement appears contextual. "
                "State the context first, such as ‘At work, ...’, so it is not "
                "saved as a global fact."
            )
        subject = normalized[:256]
        try:
            detected_scope = detect_explicit_named_scope(normalized)
            scope = (
                Scope(ScopeType.GLOBAL)
                if detected_scope is None
                else self.repository.resolve_named_scope(
                    detected_scope.scope_type,
                    detected_scope.display_label,
                    correlation_id,
                )
            )
            result = self.capture.remember_explicitly(
                ExplicitMemoryRequest(
                    FactPayload(subject, normalized),
                    Sensitivity.NORMAL,
                    MentionPolicy.MAY_MENTION_WHEN_RELEVANT,
                    scope,
                    source_ref or f"turn:{correlation_id}",
                ),
                correlation_id,
            )
        except MemoryValidationError:
            return "That information cannot be stored under the memory safety rules."

        labels = safe_topic_labels(normalized, fallback="personal fact")
        topics = (
            labels[0]
            if len(labels) == 1
            else f"{', '.join(labels[:-1])} and {labels[-1]}"
        )
        return {
            CaptureDecision.CREATED_CONFIRMED: f"Memory updated: {topics}.",
            CaptureDecision.DUPLICATE: (
                f"Memory unchanged: {topics}. That information is already "
                "confirmed."
            ),
            CaptureDecision.CONFIRMED_EXISTING_CANDIDATE: (
                f"Memory confirmed: {topics}."
            ),
            CaptureDecision.CLARIFICATION_REQUIRED: (
                f"Memory needs clarification: {topics}. Related saved information "
                "may conflict, so I did not overwrite it."
            ),
            CaptureDecision.EXPLICIT_HIGHER_RISK_REVIEW_REQUIRED: (
                f"Memory not saved: {topics}. Higher-risk review is required."
            ),
        }.get(result.decision, f"Memory not saved: {topics}.")

    def create_daily_backup(self, correlation_id: UUID) -> BackupSnapshot | None:
        if self.backup_manager is None:
            return None
        return self.backup_manager.create_daily(correlation_id)

    def confirm_candidate(
        self,
        record_id: UUID,
        correlation_id: UUID,
        *,
        expected_version: int | None = None,
        high_risk_passcode: str | None = None,
    ) -> None:
        """Confirm one candidate; sensitive categories require the passcode gate."""

        record = self.repository.inspect_record(record_id, correlation_id)
        if expected_version is not None and record.row_version != expected_version:
            raise ValueError("The candidate changed before it was reviewed.")
        if record.sensitivity in {Sensitivity.SENSITIVE, Sensitivity.RESTRICTED}:
            arguments = {
                "record_id": str(record.record_id),
                "row_version": record.row_version,
                "sensitivity": record.sensitivity.value,
            }
            if high_risk_passcode is None:
                raise ValueError("High-risk passcode is required.")
            grant = self.approval_gate.approve(
                ActionKind.MEMORY_CONFIRM_SENSITIVE,
                arguments,
                high_risk_passcode,
                correlation_id,
            )
            authorization = authorize_action(
                ActionKind.MEMORY_CONFIRM_SENSITIVE,
                arguments=arguments,
                approval_receipt=grant.receipt,
                approval_authority=grant.authority,
            )
            if not authorization.allowed:
                raise ValueError("Sensitive memory confirmation was not authorized.")
        self.repository.confirm_candidate(
            record.record_id,
            record.row_version,
            Provenance(
                SourceType.TRUSTED_INTERFACE,
                "candidate-review",
                ActorType.USER,
            ),
            correlation_id,
        )

    def reject_candidate(self, record_id: UUID, correlation_id: UUID) -> None:
        record = self.repository.inspect_record(record_id, correlation_id)
        self.repository.reject_candidate(
            record.record_id,
            record.row_version,
            Provenance(
                SourceType.TRUSTED_INTERFACE,
                "candidate-review",
                ActorType.USER,
            ),
            correlation_id,
        )

    def review_candidate(
        self,
        record_id: UUID,
        correlation_id: UUID,
        *,
        high_risk_passcode: str | None = None,
    ) -> MemoryRecord:
        """Return one candidate after exact passcode approval when protected."""

        record = self.repository.inspect_record(record_id, correlation_id)
        if record.sensitivity in {Sensitivity.SENSITIVE, Sensitivity.RESTRICTED}:
            arguments = {
                "decision": "view",
                "record_id": str(record.record_id),
                "row_version": record.row_version,
                "sensitivity": record.sensitivity.value,
            }
            if high_risk_passcode is None:
                raise ValueError("High-risk passcode is required.")
            grant = self.approval_gate.approve(
                ActionKind.MEMORY_REVIEW_SENSITIVE,
                arguments,
                high_risk_passcode,
                correlation_id,
            )
            authorization = authorize_action(
                ActionKind.MEMORY_REVIEW_SENSITIVE,
                arguments=arguments,
                approval_receipt=grant.receipt,
                approval_authority=grant.authority,
            )
            if not authorization.allowed:
                raise ValueError("Sensitive memory review was not authorized.")
        return record

    def authorize_sensitive_candidate_decision(
        self,
        record_id: UUID,
        expected_version: int,
        decision: str,
        content_digest: str,
        high_risk_passcode: str | None,
        correlation_id: UUID,
        *,
        target_id: UUID | None = None,
        target_version: int = 0,
        effective_date: str = "",
    ) -> MemoryRecord:
        """Authorize one exact protected candidate decision without exposing authority."""

        record = self.repository.inspect_record(record_id, correlation_id)
        if record.row_version != expected_version:
            raise ValueError("The candidate changed before it was reviewed.")
        if record.sensitivity not in {Sensitivity.SENSITIVE, Sensitivity.RESTRICTED}:
            return record
        if decision not in {"confirm", "correct", "successor"}:
            raise ValueError("Sensitive candidate decision is invalid.")
        if (
            not isinstance(content_digest, str)
            or len(content_digest) != 64
            or any(character not in "0123456789abcdef" for character in content_digest)
        ):
            raise ValueError("Sensitive candidate content digest is invalid.")
        if decision == "confirm":
            if target_id is not None or target_version != 0 or effective_date:
                raise ValueError("Sensitive confirmation arguments are invalid.")
        elif not isinstance(target_id, UUID) or target_version < 1:
            raise ValueError("Sensitive reconciliation target is invalid.")
        if decision == "successor" and not effective_date:
            raise ValueError("Sensitive reconciliation date is required.")
        if decision != "successor" and effective_date:
            raise ValueError("Sensitive reconciliation date is invalid.")
        if high_risk_passcode is None:
            raise ValueError("High-risk passcode is required.")
        arguments = {
            "content_digest": content_digest,
            "decision": decision,
            "effective_date": effective_date,
            "record_id": str(record.record_id),
            "row_version": record.row_version,
            "sensitivity": record.sensitivity.value,
            "target_id": "" if target_id is None else str(target_id),
            "target_version": target_version,
        }
        grant = self.approval_gate.approve(
            ActionKind.MEMORY_CONFIRM_SENSITIVE,
            arguments,
            high_risk_passcode,
            correlation_id,
        )
        authorization = authorize_action(
            ActionKind.MEMORY_CONFIRM_SENSITIVE,
            arguments=arguments,
            approval_receipt=grant.receipt,
            approval_authority=grant.authority,
        )
        if not authorization.allowed:
            raise ValueError("Sensitive memory decision was not authorized.")
        return record

    def restore_backup(
        self,
        snapshot_path: Path,
        high_risk_passcode: str,
        correlation_id: UUID,
    ) -> None:
        """Plan, authenticate, and restore through the exact trusted boundary."""

        if self.backup_manager is None:
            raise ValueError("A backup destination is not configured.")
        plan = self.backup_manager.plan_restore(snapshot_path, correlation_id)
        grant = self.approval_gate.approve(
            ActionKind.MEMORY_BACKUP_RESTORE,
            plan.approval_arguments,
            high_risk_passcode,
            correlation_id,
        )
        self.backup_manager.restore(
            plan,
            correlation_id,
            approval_receipt=grant.receipt,
            approval_authority=grant.authority,
        )

    def close(self) -> None:
        self.key_provider.close()

    def __enter__(self) -> "MemoryRuntime":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
