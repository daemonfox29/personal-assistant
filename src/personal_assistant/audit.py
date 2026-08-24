"""Typed, content-minimizing contracts for security audit events."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import re
from threading import Lock
from typing import Protocol, runtime_checkable
from uuid import UUID, uuid4


_SAFE_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
MAX_AUDIT_INTEGER = 9_223_372_036_854_775_807
MAX_AUDIT_METADATA_ITEMS = 16


class AuditError(RuntimeError):
    """A safe expected failure at the audit boundary."""


class AuditValidationError(AuditError):
    """An audit event contains data outside the safe schema."""


class AuditWriteError(AuditError):
    """An audit sink could not durably record an event."""


class AuditComponent(StrEnum):
    """Trusted components that may emit audit events."""

    APPLICATION = "application"
    MODEL = "model"
    AUTHORIZATION = "authorization"
    TOOL = "tool"
    DATABASE = "database"
    BACKUP = "backup"
    AUDIT = "audit"


class AuditOperation(StrEnum):
    """Stable operation categories, not free-form log messages."""

    STARTUP = "startup"
    SHUTDOWN = "shutdown"
    CONFIGURATION_VALIDATE = "configuration_validate"
    MODEL_REQUEST = "model_request"
    PERMISSION_EVALUATE = "permission_evaluate"
    APPROVAL_ISSUE = "approval_issue"
    APPROVAL_VERIFY = "approval_verify"
    TOOL_EXECUTE = "tool_execute"
    DATABASE_OPEN = "database_open"
    DATABASE_MIGRATE = "database_migrate"
    REPOSITORY_READ = "repository_read"
    REPOSITORY_WRITE = "repository_write"
    BACKUP_CREATE = "backup_create"
    BACKUP_RESTORE = "backup_restore"
    AUDIT_WRITE = "audit_write"


class AuditOutcome(StrEnum):
    """Bounded outcomes shared by all operations."""

    STARTED = "started"
    SUCCEEDED = "succeeded"
    DENIED = "denied"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class AuditReasonCode(StrEnum):
    """Safe diagnostic reasons that do not embed exception or user text."""

    NORMAL = "normal"
    POLICY_ALLOWED = "policy_allowed"
    POLICY_DENIED = "policy_denied"
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_INVALID = "approval_invalid"
    APPROVAL_EXPIRED = "approval_expired"
    APPROVAL_MISMATCH = "approval_mismatch"
    REDIRECT_BLOCKED = "redirect_blocked"
    REMOTE_DESTINATION_BLOCKED = "remote_destination_blocked"
    INVALID_CONFIGURATION = "invalid_configuration"
    INVALID_DATA = "invalid_data"
    MODEL_UNAVAILABLE = "model_unavailable"
    KEY_UNAVAILABLE = "key_unavailable"
    ENCRYPTION_UNAVAILABLE = "encryption_unavailable"
    DATABASE_UNLOCK_FAILED = "database_unlock_failed"
    MIGRATION_FAILED = "migration_failed"
    AUDIT_UNAVAILABLE = "audit_unavailable"
    USER_CANCELLED = "user_cancelled"
    RESOURCE_LIMIT = "resource_limit"
    SAFE_INTERNAL_FAILURE = "safe_internal_failure"


class AuditMetadataKey(StrEnum):
    """Allowlisted metadata keys whose values must remain non-content labels."""

    ACTION_KIND = "action_kind"
    AGENT_ID = "agent_id"
    APPROVAL_STATE = "approval_state"
    BYTE_COUNT = "byte_count"
    DESTINATION_CLASS = "destination_class"
    ERROR_CATEGORY = "error_category"
    HTTP_STATUS = "http_status"
    ITEM_COUNT = "item_count"
    MIGRATION_VERSION = "migration_version"
    MODEL_ADAPTER = "model_adapter"
    RECORD_ID = "record_id"
    TARGET_CLASS = "target_class"
    TASK_ID = "task_id"


AuditMetadataValue = str | int


_INTEGER_METADATA_KEYS = {
    AuditMetadataKey.BYTE_COUNT,
    AuditMetadataKey.HTTP_STATUS,
    AuditMetadataKey.ITEM_COUNT,
    AuditMetadataKey.MIGRATION_VERSION,
}


@dataclass(frozen=True)
class AuditMetadataItem:
    """One allowlisted, bounded, content-free metadata value."""

    key: AuditMetadataKey
    value: AuditMetadataValue

    def __post_init__(self) -> None:
        if not isinstance(self.key, AuditMetadataKey):
            raise AuditValidationError("Audit metadata uses an unknown key.")
        if self.key in _INTEGER_METADATA_KEYS:
            if (
                isinstance(self.value, bool)
                or not isinstance(self.value, int)
                or not 0 <= self.value <= MAX_AUDIT_INTEGER
            ):
                raise AuditValidationError(
                    "Audit numeric metadata must be a bounded non-negative integer."
                )
            return
        if isinstance(self.value, str) and _SAFE_LABEL.fullmatch(self.value):
            return
        raise AuditValidationError(
            "Audit label metadata must be a bounded safe label."
        )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class AuditEvent:
    """A structured audit event that deliberately cannot contain free-form text."""

    correlation_id: UUID
    component: AuditComponent
    operation: AuditOperation
    outcome: AuditOutcome
    reason_code: AuditReasonCode
    metadata: tuple[AuditMetadataItem, ...] = field(default_factory=tuple)
    duration_ms: int | None = None
    event_id: UUID = field(default_factory=uuid4)
    timestamp: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        if not isinstance(self.event_id, UUID) or not isinstance(
            self.correlation_id, UUID
        ):
            raise AuditValidationError("Audit identifiers must be UUID values.")
        if not isinstance(self.component, AuditComponent):
            raise AuditValidationError("Audit component is not recognized.")
        if not isinstance(self.operation, AuditOperation):
            raise AuditValidationError("Audit operation is not recognized.")
        if not isinstance(self.outcome, AuditOutcome):
            raise AuditValidationError("Audit outcome is not recognized.")
        if not isinstance(self.reason_code, AuditReasonCode):
            raise AuditValidationError("Audit reason code is not recognized.")
        if not isinstance(self.timestamp, datetime) or self.timestamp.tzinfo is None:
            raise AuditValidationError("Audit timestamps must include a timezone.")
        if self.timestamp.utcoffset() is None:
            raise AuditValidationError("Audit timestamps must include a timezone.")
        if self.duration_ms is not None:
            if (
                isinstance(self.duration_ms, bool)
                or not isinstance(self.duration_ms, int)
                or not 0 <= self.duration_ms <= MAX_AUDIT_INTEGER
            ):
                raise AuditValidationError(
                    "Audit duration must be a non-negative integer."
                )
        if not isinstance(self.metadata, tuple):
            raise AuditValidationError("Audit metadata must be an immutable tuple.")
        if len(self.metadata) > MAX_AUDIT_METADATA_ITEMS:
            raise AuditValidationError("Audit event contains too many metadata items.")

        seen_keys: set[AuditMetadataKey] = set()
        for item in self.metadata:
            if not isinstance(item, AuditMetadataItem):
                raise AuditValidationError("Audit metadata item is not recognized.")
            if item.key in seen_keys:
                raise AuditValidationError("Audit metadata keys must be unique.")
            seen_keys.add(item.key)


@runtime_checkable
class AuditSink(Protocol):
    """The behavior required from replaceable audit destinations."""

    def write(self, event: AuditEvent) -> None:
        """Record one validated event or raise a safe audit error."""


class InMemoryAuditSink:
    """A content-minimizing sink for tests that never writes to disk."""

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []
        self._lock = Lock()

    def write(self, event: AuditEvent) -> None:
        if not isinstance(event, AuditEvent):
            raise AuditValidationError("Audit sink requires a typed event.")
        with self._lock:
            self._events.append(event)

    @property
    def events(self) -> tuple[AuditEvent, ...]:
        """Return an immutable snapshot of recorded events."""

        with self._lock:
            return tuple(self._events)
