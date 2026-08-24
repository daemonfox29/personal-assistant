"""Bounded JSON Lines storage for typed audit events."""

from dataclasses import dataclass
from datetime import timezone
import json
import os
from pathlib import Path
import stat
from threading import Lock

from personal_assistant.audit import (
    AuditEvent,
    AuditValidationError,
    AuditWriteError,
)


DEFAULT_MAX_FILE_BYTES = 1_048_576
DEFAULT_MAX_EVENT_BYTES = 16_384
DEFAULT_RETAINED_ROTATIONS = 5
MAX_FILE_BYTES = 67_108_864
MAX_EVENT_BYTES = 1_048_576
MAX_RETAINED_ROTATIONS = 20


@dataclass(frozen=True)
class AuditFileSettings:
    """Validated limits for one explicitly located local audit file."""

    path: Path
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES
    max_event_bytes: int = DEFAULT_MAX_EVENT_BYTES
    retained_rotations: int = DEFAULT_RETAINED_ROTATIONS

    def __post_init__(self) -> None:
        if not isinstance(self.path, Path) or not self.path.is_absolute():
            raise ValueError("The audit file path must be an explicit absolute path.")
        if self.path.name in {"", ".", ".."}:
            raise ValueError("The audit file path must name a file.")
        if (
            isinstance(self.max_file_bytes, bool)
            or not isinstance(self.max_file_bytes, int)
            or not 0 < self.max_file_bytes <= MAX_FILE_BYTES
        ):
            raise ValueError(
                "The audit file size limit must be a bounded positive integer."
            )
        if (
            isinstance(self.max_event_bytes, bool)
            or not isinstance(self.max_event_bytes, int)
            or not 0 < self.max_event_bytes <= MAX_EVENT_BYTES
        ):
            raise ValueError(
                "The audit event size limit must be a bounded positive integer."
            )
        if self.max_event_bytes > self.max_file_bytes:
            raise ValueError(
                "The audit event size limit cannot exceed the file size limit."
            )
        if (
            isinstance(self.retained_rotations, bool)
            or not isinstance(self.retained_rotations, int)
            or not 0 <= self.retained_rotations <= MAX_RETAINED_ROTATIONS
        ):
            raise ValueError(
                "The retained audit rotation count must be between 0 and "
                f"{MAX_RETAINED_ROTATIONS}."
            )


def _event_document(event: AuditEvent) -> dict[str, object]:
    timestamp = event.timestamp.astimezone(timezone.utc)
    return {
        "component": event.component.value,
        "correlation_id": str(event.correlation_id),
        "duration_ms": event.duration_ms,
        "event_id": str(event.event_id),
        "metadata": {item.key.value: item.value for item in event.metadata},
        "operation": event.operation.value,
        "outcome": event.outcome.value,
        "reason_code": event.reason_code.value,
        "timestamp": timestamp.isoformat(timespec="milliseconds").replace(
            "+00:00", "Z"
        ),
    }


class JsonLinesAuditSink:
    """Write validated events to a bounded, rotated, local JSON Lines file."""

    def __init__(self, settings: AuditFileSettings) -> None:
        self._settings = settings
        self._lock = Lock()

    def write(self, event: AuditEvent) -> None:
        if not isinstance(event, AuditEvent):
            raise AuditValidationError("Audit sink requires a typed event.")

        encoded = (
            json.dumps(
                _event_document(event),
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        if len(encoded) > self._settings.max_event_bytes:
            raise AuditValidationError("The serialized audit event is too large.")

        with self._lock:
            try:
                self._prepare_parent()
                self._reject_unsafe_existing_file(self._settings.path)
                if self._rotation_required(len(encoded)):
                    self._rotate()
                self._append(encoded)
            except AuditWriteError:
                raise
            except OSError as error:
                raise AuditWriteError(
                    "Audit event could not be recorded."
                ) from error

    def _prepare_parent(self) -> None:
        parent = self._settings.path.parent
        existed = parent.exists()
        parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        if not parent.is_dir():
            raise AuditWriteError("Audit event could not be recorded.")
        if not existed and os.name == "posix":
            parent.chmod(0o700)

    def _rotation_required(self, incoming_bytes: int) -> bool:
        path = self._settings.path
        if not path.exists():
            return False
        return path.stat().st_size + incoming_bytes > self._settings.max_file_bytes

    def _rotate(self) -> None:
        path = self._settings.path
        rotations = self._settings.retained_rotations
        if rotations == 0:
            self._unlink_regular_file(path)
            return

        oldest = self._rotation_path(rotations)
        if oldest.exists() or oldest.is_symlink():
            self._unlink_regular_file(oldest)

        for index in range(rotations - 1, 0, -1):
            source = self._rotation_path(index)
            destination = self._rotation_path(index + 1)
            if source.exists() or source.is_symlink():
                self._reject_unsafe_existing_file(source)
                self._reject_unsafe_existing_file(destination)
                os.replace(source, destination)

        self._reject_unsafe_existing_file(path)
        first_rotation = self._rotation_path(1)
        self._reject_unsafe_existing_file(first_rotation)
        os.replace(path, first_rotation)

    def _append(self, encoded: bytes) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        no_follow = getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self._settings.path, flags | no_follow, 0o600)
        try:
            if os.name == "posix":
                os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "ab", closefd=False) as audit_file:
                audit_file.write(encoded)
                audit_file.flush()
                os.fsync(audit_file.fileno())
        finally:
            os.close(descriptor)

    def _rotation_path(self, index: int) -> Path:
        path = self._settings.path
        return path.with_name(f"{path.name}.{index}")

    @staticmethod
    def _reject_unsafe_existing_file(path: Path) -> None:
        try:
            file_status = path.lstat()
        except FileNotFoundError:
            return
        if stat.S_ISLNK(file_status.st_mode) or not stat.S_ISREG(
            file_status.st_mode
        ):
            raise AuditWriteError("Audit event could not be recorded.")

    @staticmethod
    def _unlink_regular_file(path: Path) -> None:
        JsonLinesAuditSink._reject_unsafe_existing_file(path)
        path.unlink(missing_ok=True)
