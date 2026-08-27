"""Bounded JSON Lines storage for typed audit events."""

from dataclasses import dataclass
from datetime import timezone
import json
import os
from pathlib import Path
import stat
from threading import Lock

from personal_assistant.audit import (
    AuditComponent,
    AuditEvent,
    AuditOperation,
    AuditOutcome,
    AuditReasonCode,
    AuditValidationError,
    AuditWriteError,
)


DEFAULT_MAX_FILE_BYTES = 1_048_576
DEFAULT_MAX_EVENT_BYTES = 16_384
DEFAULT_RETAINED_ROTATIONS = 5
MAX_FILE_BYTES = 67_108_864
MAX_EVENT_BYTES = 1_048_576
MAX_RETAINED_ROTATIONS = 20
DEFAULT_AUDIT_PAGE_SIZE = 100
MAX_VISIBLE_AUDIT_EVENTS = 1_000
_READ_CHUNK_BYTES = 65_536


@dataclass(frozen=True)
class AuditLogItem:
    """One display-safe audit summary with no identifiers or free-form content."""

    timestamp: str
    component: str
    operation: str
    outcome: str
    reason_code: str


@dataclass(frozen=True)
class AuditLogPage:
    items: tuple[AuditLogItem, ...]
    next_offset: int | None


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
        try:
            status = parent.lstat()
        except FileNotFoundError:
            parent.mkdir(parents=True, mode=0o700)
            status = parent.lstat()
        if stat.S_ISLNK(status.st_mode) or not stat.S_ISDIR(status.st_mode):
            raise AuditWriteError("Audit event could not be recorded.")
        if os.name == "posix":
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


class JsonLinesAuditReader:
    """Read a bounded newest-first, content-minimized view of audit events."""

    def __init__(self, settings: AuditFileSettings) -> None:
        self._settings = settings

    def read_page(self, offset: int = 0) -> AuditLogPage:
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise AuditWriteError("The audit page cursor is invalid.")
        if offset >= MAX_VISIBLE_AUDIT_EVENTS:
            return AuditLogPage((), None)
        limit = min(
            DEFAULT_AUDIT_PAGE_SIZE,
            MAX_VISIBLE_AUDIT_EVENTS - offset,
        )
        summaries: list[AuditLogItem] = []
        valid_index = 0
        has_more = False
        try:
            for path in self._newest_files():
                for encoded in self._reverse_lines(path):
                    item = self._safe_item(encoded)
                    if item is None:
                        raise AuditWriteError(
                            "Audit history contains an invalid entry."
                        )
                    if valid_index < offset:
                        valid_index += 1
                        continue
                    if len(summaries) < limit:
                        summaries.append(item)
                        valid_index += 1
                        continue
                    has_more = True
                    break
                if has_more:
                    break
        except AuditWriteError:
            raise
        except OSError as error:
            raise AuditWriteError("Audit history could not be read safely.") from error
        next_offset = offset + len(summaries) if has_more else None
        return AuditLogPage(tuple(summaries), next_offset)

    def _newest_files(self) -> tuple[Path, ...]:
        paths = [self._settings.path]
        paths.extend(
            self._settings.path.with_name(f"{self._settings.path.name}.{index}")
            for index in range(1, self._settings.retained_rotations + 1)
        )
        return tuple(
            path for path in paths if path.exists() or path.is_symlink()
        )

    def _reverse_lines(self, path: Path):
        JsonLinesAuditSink._reject_unsafe_existing_file(path)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            status = os.fstat(descriptor)
            if not stat.S_ISREG(status.st_mode):
                raise AuditWriteError("Audit history could not be read safely.")
            position = status.st_size
            remainder = b""
            while position > 0:
                size = min(_READ_CHUNK_BYTES, position)
                position -= size
                os.lseek(descriptor, position, os.SEEK_SET)
                block = os.read(descriptor, size) + remainder
                lines = block.split(b"\n")
                remainder = lines[0]
                for line in reversed(lines[1:]):
                    if line:
                        yield line
            if remainder:
                yield remainder
        finally:
            os.close(descriptor)

    def _safe_item(self, encoded: bytes) -> AuditLogItem | None:
        if len(encoded) > self._settings.max_event_bytes:
            return None
        try:
            document = json.loads(encoded.decode("utf-8"))
            if not isinstance(document, dict):
                return None
            timestamp = document["timestamp"]
            if not isinstance(timestamp, str) or len(timestamp) > 40:
                return None
            component = AuditComponent(document["component"])
            operation = AuditOperation(document["operation"])
            outcome = AuditOutcome(document["outcome"])
            reason = AuditReasonCode(document["reason_code"])
            return AuditLogItem(
                timestamp,
                component.value,
                operation.value,
                outcome.value,
                reason.value,
            )
        except (KeyError, UnicodeError, json.JSONDecodeError, ValueError, TypeError):
            return None
