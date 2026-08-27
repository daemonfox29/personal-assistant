"""Consistent encrypted memory backups and fail-closed guided restore."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import stat
from time import monotonic
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
from personal_assistant.authorization import (
    ApprovalAuthority,
    ApprovalReceipt,
    authorize_action,
)
from personal_assistant.encrypted_database import EncryptedConnectionProvider
from personal_assistant.migration import MigrationRunner, MigrationSource
from personal_assistant.permissions import ActionKind


GIB = 1024**3
DEFAULT_MAX_SNAPSHOT_BYTES = 2 * GIB
DEFAULT_MAX_TOTAL_BYTES = 10 * GIB
_SNAPSHOT_NAME = re.compile(
    r"^memory-(?P<stamp>[0-9]{8}T[0-9]{6}Z)-(?P<id>[0-9a-f]{32})\.db$"
)
_CIPHERTEXT_DIGEST = re.compile(r"^[0-9a-f]{64}$")
BACKUP_METADATA_VERSION = 1


class BackupError(RuntimeError):
    """A content-free expected backup or restore failure."""


class BackupUnavailableError(BackupError):
    """The configured destination cannot safely accept a backup."""


class BackupIntegrityError(BackupError):
    """A backup failed database or migration verification."""


class RestoreAuthorizationError(BackupError):
    """Restore did not carry exact, one-use high-risk approval."""


class RestoreError(BackupError):
    """Restore failed while preserving or recovering the live database."""


@dataclass(frozen=True)
class BackupSettings:
    """Bounded storage policy for encrypted snapshots."""

    live_path: Path
    destination: Path
    retain_count: int = 7
    max_snapshot_bytes: int = DEFAULT_MAX_SNAPSHOT_BYTES
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES

    def __post_init__(self) -> None:
        for path in (self.live_path, self.destination):
            if not isinstance(path, Path) or not path.is_absolute():
                raise ValueError("Backup paths must be explicit absolute paths.")
        if self.live_path.name in {"", ".", ".."}:
            raise ValueError("The live database path must name a file.")
        if isinstance(self.retain_count, bool) or not 1 <= self.retain_count <= 365:
            raise ValueError("Backup retention count is outside its safe range.")
        if (
            isinstance(self.max_snapshot_bytes, bool)
            or not 1 <= self.max_snapshot_bytes <= DEFAULT_MAX_SNAPSHOT_BYTES
        ):
            raise ValueError("Snapshot size limit is outside its safe range.")
        if (
            isinstance(self.max_total_bytes, bool)
            or not self.max_snapshot_bytes
            <= self.max_total_bytes
            <= DEFAULT_MAX_TOTAL_BYTES
        ):
            raise ValueError("Total backup size limit is outside its safe range.")


@dataclass(frozen=True)
class BackupSnapshot:
    path: Path
    byte_count: int
    ciphertext_sha256: str


@dataclass(frozen=True)
class RestorePlan:
    """Content-free impact details to display before passcode entry."""

    snapshot: BackupSnapshot
    creates_pre_restore_snapshot: bool = True
    reapplies_deletion_ledger: bool = True
    replaces_live_database: bool = True

    @property
    def approval_arguments(self) -> Mapping[str, object]:
        """Reconstruct immutable plan data as exact authorization arguments."""

        return {
            "snapshot_name": self.snapshot.path.name,
            "byte_count": self.snapshot.byte_count,
            "ciphertext_sha256": self.snapshot.ciphertext_sha256,
            "live_target": "encrypted_memory_database",
        }


DatabaseFactory = Callable[[Path], EncryptedConnectionProvider]


class EncryptedBackupManager:
    """Own encrypted snapshots without exposing keys or database handles."""

    def __init__(
        self,
        settings: BackupSettings,
        *,
        live_database: EncryptedConnectionProvider,
        database_factory: DatabaseFactory,
        migration_source: MigrationSource,
        audit_sink: AuditSink,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(live_database, EncryptedConnectionProvider):
            raise TypeError("Backup manager requires an encrypted live database.")
        if not isinstance(migration_source, MigrationSource):
            raise TypeError("Backup manager requires a migration source.")
        if not isinstance(audit_sink, AuditSink):
            raise TypeError("Backup manager requires an audit sink.")
        self._settings = settings
        self._live_database = live_database
        self._database_factory = database_factory
        self._migration_source = migration_source
        self._audit_sink = audit_sink
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def create_daily(self, correlation_id: UUID) -> BackupSnapshot | None:
        """Create at most one verified snapshot per UTC day."""

        self._require_uuid(correlation_id)
        now = self._now()
        prefix = f"memory-{now:%Y%m%d}T"
        for path in reversed(self._safe_snapshots()):
            if path.name.startswith(prefix):
                try:
                    self._snapshot_descriptor(path)
                    self._verify_database(
                        self._database_factory(path), correlation_id, migrate=False
                    )
                except BackupIntegrityError:
                    continue
                self._emit(
                    correlation_id,
                    AuditOperation.BACKUP_CREATE,
                    AuditOutcome.SKIPPED,
                    AuditReasonCode.NORMAL,
                )
                return None
        return self.create_snapshot(correlation_id)

    def validate_destination(self) -> None:
        """Verify that the configured destination is a present real directory."""

        self._validate_destination()

    def list_snapshots(self) -> tuple[Path, ...]:
        """Return managed snapshot paths without opening or exposing content."""

        verified: list[Path] = []
        for path in self._safe_snapshots():
            try:
                self._snapshot_descriptor(path)
            except BackupError:
                continue
            verified.append(path)
        return tuple(verified)

    def list_snapshot_descriptors(self) -> tuple[BackupSnapshot, ...]:
        """Return bounded metadata-verified managed snapshots, newest first."""

        descriptors: list[BackupSnapshot] = []
        for path in reversed(self._safe_snapshots()):
            try:
                descriptors.append(self._snapshot_descriptor(path))
            except BackupError:
                continue
            if len(descriptors) >= self._settings.retain_count:
                break
        return tuple(descriptors)

    def create_snapshot(self, correlation_id: UUID) -> BackupSnapshot:
        """Create, verify, atomically publish, then enforce retention."""

        self._require_uuid(correlation_id)
        started = monotonic()
        self._emit(correlation_id, AuditOperation.BACKUP_CREATE, AuditOutcome.STARTED,
                   AuditReasonCode.NORMAL)
        partial: Path | None = None
        metadata_partial: Path | None = None
        metadata_final: Path | None = None
        try:
            self._validate_destination()
            if not self._settings.live_path.is_file():
                raise BackupUnavailableError("The live database is unavailable.")
            free = shutil.disk_usage(self._settings.destination).free
            estimated = self._settings.live_path.stat().st_size
            if estimated > self._settings.max_snapshot_bytes or free < estimated:
                raise BackupUnavailableError("Backup storage limits would be exceeded.")

            now = self._now()
            identifier = uuid4().hex
            final = self._settings.destination / (
                f"memory-{now:%Y%m%dT%H%M%SZ}-{identifier}.db"
            )
            partial = self._settings.destination / f".memory-{identifier}.partial"
            target_database = self._database_factory(partial)
            with self._live_database.connect(correlation_id) as source:
                with target_database.connect(correlation_id) as target:
                    source.backup(target)
                    target.commit()

            self._verify_database(target_database, correlation_id, migrate=False)
            size = partial.stat().st_size
            if size > self._settings.max_snapshot_bytes:
                raise BackupUnavailableError(
                    "The encrypted snapshot exceeds its size limit."
                )
            digest = self._file_digest(partial)
            snapshot = BackupSnapshot(final, size, digest)
            metadata_final = self._metadata_path(final)
            metadata_partial = self._settings.destination / (
                f".memory-{identifier}.metadata.partial"
            )
            self._write_metadata(snapshot, metadata_partial, now)
            self._emit(
                correlation_id,
                AuditOperation.BACKUP_CREATE,
                AuditOutcome.SUCCEEDED,
                AuditReasonCode.NORMAL,
                size,
                started,
            )
            self._durable_replace(metadata_partial, metadata_final)
            metadata_partial = None
            try:
                self._durable_replace(partial, final)
            except Exception:
                self._unlink_managed(metadata_final)
                raise
            partial = None
            if os.name == "posix":
                final.chmod(0o600)
            self._enforce_retention(final)
            return snapshot
        except BackupIntegrityError:
            self._emit(
                correlation_id,
                AuditOperation.BACKUP_CREATE,
                AuditOutcome.FAILED,
                AuditReasonCode.INTEGRITY_FAILED,
                duration_started=started,
            )
            raise
        except BackupUnavailableError:
            self._emit(
                correlation_id,
                AuditOperation.BACKUP_CREATE,
                AuditOutcome.FAILED,
                AuditReasonCode.RESOURCE_LIMIT,
                duration_started=started,
            )
            raise
        except Exception as error:
            self._emit(
                correlation_id,
                AuditOperation.BACKUP_CREATE,
                AuditOutcome.FAILED,
                AuditReasonCode.SAFE_INTERNAL_FAILURE,
                duration_started=started,
            )
            raise BackupError("Encrypted backup failed safely.") from error
        finally:
            self._unlink_managed(partial)
            self._unlink_managed(metadata_partial)

    def plan_restore(self, snapshot_path: Path, correlation_id: UUID) -> RestorePlan:
        """Verify a managed snapshot and return exact approval details."""

        self._require_uuid(correlation_id)
        if not isinstance(snapshot_path, Path) or not snapshot_path.is_absolute():
            raise BackupUnavailableError(
                "Restore snapshot must be an explicit absolute path."
            )
        snapshot = self._snapshot_descriptor(snapshot_path)
        self._verify_database(
            self._database_factory(snapshot.path),
            correlation_id,
            migrate=False,
            require_current=False,
        )
        return RestorePlan(snapshot)

    def restore(
        self,
        plan: RestorePlan,
        correlation_id: UUID,
        *,
        approval_receipt: ApprovalReceipt,
        approval_authority: ApprovalAuthority,
    ) -> None:
        """Restore only after exact trusted approval; roll back on every failure."""

        self._require_uuid(correlation_id)
        started = monotonic()
        self._emit(correlation_id, AuditOperation.BACKUP_RESTORE, AuditOutcome.STARTED,
                   AuditReasonCode.NORMAL)
        if not isinstance(plan, RestorePlan):
            raise RestoreAuthorizationError("A verified restore plan is required.")
        try:
            current_snapshot = self._snapshot_descriptor(plan.snapshot.path)
        except BackupError as error:
            self._emit(
                correlation_id,
                AuditOperation.BACKUP_RESTORE,
                AuditOutcome.DENIED,
                AuditReasonCode.INTEGRITY_FAILED,
                duration_started=started,
            )
            raise RestoreAuthorizationError(
                "The approved snapshot has changed."
            ) from error
        if current_snapshot != plan.snapshot:
            self._emit(
                correlation_id,
                AuditOperation.BACKUP_RESTORE,
                AuditOutcome.DENIED,
                AuditReasonCode.INTEGRITY_FAILED,
                duration_started=started,
            )
            raise RestoreAuthorizationError("The approved snapshot has changed.")
        authorization = authorize_action(
            ActionKind.MEMORY_BACKUP_RESTORE,
            arguments=plan.approval_arguments,
            approval_receipt=approval_receipt,
            approval_authority=approval_authority,
        )
        if not authorization.allowed:
            self._emit(
                correlation_id,
                AuditOperation.BACKUP_RESTORE,
                AuditOutcome.DENIED,
                AuditReasonCode.APPROVAL_INVALID,
                duration_started=started,
            )
            raise RestoreAuthorizationError("Exact high-risk approval is required.")

        candidate = self._settings.live_path.parent / f".restore-{uuid4().hex}.db"
        rollback = self._settings.live_path.parent / f".rollback-{uuid4().hex}.db"
        displaced: Path | None = None
        try:
            current_ledger = self._load_deletion_ledger(
                self._live_database, correlation_id
            )

            snapshot_database = self._database_factory(plan.snapshot.path)
            candidate_database = self._database_factory(candidate)
            with snapshot_database.connect(correlation_id) as source:
                with candidate_database.connect(correlation_id) as target:
                    source.backup(target)
                    target.commit()
            self._verify_database(candidate_database, correlation_id, migrate=True)

            # Preserve the current state before replacement. The restore source
            # has already been copied, so retention may now safely prune it.
            self.create_snapshot(correlation_id)
            self._apply_deletion_ledger(
                candidate_database, current_ledger, correlation_id
            )
            self._verify_database(candidate_database, correlation_id, migrate=False)

            self._emit(
                correlation_id,
                AuditOperation.BACKUP_RESTORE,
                AuditOutcome.SUCCEEDED,
                AuditReasonCode.NORMAL,
                plan.snapshot.byte_count,
                started,
            )
            os.replace(self._settings.live_path, rollback)
            self._durable_replace(candidate, self._settings.live_path)
            try:
                self._verify_database(
                    self._live_database, correlation_id, migrate=False
                )
            except Exception:
                displaced = self._settings.live_path.parent / (
                    f".failed-{uuid4().hex}.db"
                )
                os.replace(self._settings.live_path, displaced)
                os.replace(rollback, self._settings.live_path)
                raise
            rollback.unlink()
        except RestoreAuthorizationError:
            raise
        except Exception as error:
            if rollback.exists() and not self._settings.live_path.exists():
                os.replace(rollback, self._settings.live_path)
            self._emit(
                correlation_id,
                AuditOperation.BACKUP_RESTORE,
                AuditOutcome.FAILED,
                AuditReasonCode.INTEGRITY_FAILED,
                duration_started=started,
            )
            raise RestoreError("Encrypted restore failed safely.") from error
        finally:
            self._unlink_managed(candidate)
            self._unlink_managed(rollback)
            self._unlink_managed(displaced)

    def _verify_database(
        self,
        provider: EncryptedConnectionProvider,
        correlation_id: UUID,
        *,
        migrate: bool,
        require_current: bool = True,
    ) -> None:
        try:
            runner = MigrationRunner(
                connection_provider=provider,
                migration_source=self._migration_source,
                audit_sink=self._audit_sink,
            )
            if migrate:
                runner.migrate(correlation_id)
            else:
                runner.validate_history(
                    correlation_id, require_current=require_current
                )
            with provider.connect(correlation_id) as connection:
                integrity = connection.execute("PRAGMA integrity_check").fetchall()
                foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
            if integrity != [("ok",)] or foreign_keys:
                raise BackupIntegrityError(
                    "Encrypted backup integrity verification failed."
                )
        except BackupIntegrityError:
            raise
        except Exception as error:
            raise BackupIntegrityError(
                "Encrypted backup integrity verification failed."
            ) from error

    @staticmethod
    def _load_deletion_ledger(
        provider: EncryptedConnectionProvider, correlation_id: UUID
    ) -> tuple[tuple[str, str, str], ...]:
        with provider.connect(correlation_id) as connection:
            return tuple(connection.execute(
                "SELECT purged_id, purged_at, reason_code FROM deletion_ledger"
            ).fetchall())

    @staticmethod
    def _apply_deletion_ledger(
        provider: EncryptedConnectionProvider,
        ledger: tuple[tuple[str, str, str], ...],
        correlation_id: UUID,
    ) -> None:
        with provider.connect(correlation_id) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                for purged_id, purged_at, reason_code in ledger:
                    connection.execute(
                        "DELETE FROM record_search WHERE record_id = ?", (purged_id,)
                    )
                    connection.execute(
                        "DELETE FROM records WHERE record_id = ?", (purged_id,)
                    )
                    connection.execute(
                        "INSERT INTO deletion_ledger "
                        "(purged_id, purged_at, reason_code) "
                        "VALUES (?, ?, ?) ON CONFLICT(purged_id) DO NOTHING",
                        (purged_id, purged_at, reason_code),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def _snapshot_descriptor(self, path: Path) -> BackupSnapshot:
        self._validate_destination()
        resolved_parent = path.parent.resolve(strict=True)
        if resolved_parent != self._settings.destination.resolve(strict=True):
            raise BackupUnavailableError(
                "Restore snapshot is outside the managed destination."
            )
        if not _SNAPSHOT_NAME.fullmatch(path.name):
            raise BackupUnavailableError("Restore snapshot name is not managed.")
        status = path.lstat()
        if stat.S_ISLNK(status.st_mode) or not stat.S_ISREG(status.st_mode):
            raise BackupUnavailableError("Restore snapshot is unsafe.")
        if status.st_size > self._settings.max_snapshot_bytes:
            raise BackupUnavailableError("Restore snapshot exceeds its size limit.")
        metadata = self._read_metadata(path)
        digest = self._file_digest(path)
        if metadata[0] != status.st_size or metadata[1] != digest:
            raise BackupIntegrityError("Backup integrity metadata does not match.")
        return BackupSnapshot(path, status.st_size, digest)

    def _validate_destination(self) -> None:
        try:
            status = self._settings.destination.lstat()
        except OSError as error:
            raise BackupUnavailableError(
                "The configured backup destination is unavailable."
            ) from error
        if stat.S_ISLNK(status.st_mode) or not stat.S_ISDIR(status.st_mode):
            raise BackupUnavailableError("The configured backup destination is unsafe.")

    def _safe_snapshots(self) -> tuple[Path, ...]:
        self._validate_destination()
        snapshots: list[Path] = []
        for path in self._settings.destination.iterdir():
            if not _SNAPSHOT_NAME.fullmatch(path.name):
                continue
            status = path.lstat()
            if stat.S_ISREG(status.st_mode) and not stat.S_ISLNK(status.st_mode):
                snapshots.append(path)
        return tuple(sorted(snapshots, key=lambda item: item.name))

    def _enforce_retention(self, newest: Path) -> None:
        snapshots = list(self._safe_snapshots())
        total = sum(path.stat().st_size for path in snapshots)
        while (
            len(snapshots) > self._settings.retain_count
            or total > self._settings.max_total_bytes
        ):
            oldest = snapshots[0]
            if oldest == newest and len(snapshots) == 1:
                raise BackupUnavailableError(
                    "Verified backup cannot fit retained storage limits."
                )
            snapshots.pop(0)
            size = oldest.stat().st_size
            oldest.unlink()
            self._metadata_path(oldest).unlink(missing_ok=True)
            total -= size

    def _write_metadata(
        self,
        snapshot: BackupSnapshot,
        path: Path,
        created_at: datetime,
    ) -> None:
        document = {
            "byte_count": snapshot.byte_count,
            "ciphertext_sha256": snapshot.ciphertext_sha256,
            "created_at": created_at.isoformat(),
            "snapshot_name": snapshot.path.name,
            "version": BACKUP_METADATA_VERSION,
        }
        encoded = json.dumps(
            document,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb", closefd=False) as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            os.close(descriptor)

    def _read_metadata(self, snapshot_path: Path) -> tuple[int, str]:
        path = self._metadata_path(snapshot_path)
        try:
            status = path.lstat()
            if stat.S_ISLNK(status.st_mode) or not stat.S_ISREG(status.st_mode):
                raise BackupIntegrityError("Backup integrity metadata is unsafe.")
            if status.st_size > 4_096:
                raise BackupIntegrityError("Backup integrity metadata is invalid.")
            document = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(document, dict) or set(document) != {
                "byte_count",
                "ciphertext_sha256",
                "created_at",
                "snapshot_name",
                "version",
            }:
                raise BackupIntegrityError("Backup integrity metadata is invalid.")
            if (
                document["version"] != BACKUP_METADATA_VERSION
                or document["snapshot_name"] != snapshot_path.name
                or isinstance(document["byte_count"], bool)
                or not isinstance(document["byte_count"], int)
                or not isinstance(document["ciphertext_sha256"], str)
                or not _CIPHERTEXT_DIGEST.fullmatch(document["ciphertext_sha256"])
                or not isinstance(document["created_at"], str)
            ):
                raise BackupIntegrityError("Backup integrity metadata is invalid.")
            created_at = datetime.fromisoformat(document["created_at"])
            if created_at.tzinfo is None or created_at.utcoffset() is None:
                raise BackupIntegrityError("Backup integrity metadata is invalid.")
            return document["byte_count"], document["ciphertext_sha256"]
        except BackupIntegrityError:
            raise
        except Exception as error:
            raise BackupIntegrityError(
                "Backup integrity metadata is invalid."
            ) from error

    @staticmethod
    def _metadata_path(snapshot_path: Path) -> Path:
        return snapshot_path.with_name(f"{snapshot_path.name}.meta.json")

    @staticmethod
    def _file_digest(path: Path) -> str:
        digest = sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def _durable_replace(source: Path, destination: Path) -> None:
        """Flush a completed file before atomically publishing its name."""

        descriptor = os.open(source, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(source, destination)
        if os.name == "posix":
            try:
                directory = os.open(destination.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            except OSError:
                # Some removable filesystems do not support directory fsync.
                # The completed file itself was still flushed before replace.
                pass

    @staticmethod
    def _unlink_managed(path: Path | None) -> None:
        if path is not None:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise BackupError("Backup clock must return an aware datetime.")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _require_uuid(value: UUID) -> None:
        if not isinstance(value, UUID):
            raise ValueError("Backup correlation ID must be a UUID.")

    def _emit(
        self,
        correlation_id: UUID,
        operation: AuditOperation,
        outcome: AuditOutcome,
        reason: AuditReasonCode,
        byte_count: int | None = None,
        duration_started: float | None = None,
    ) -> None:
        metadata = () if byte_count is None else (
            AuditMetadataItem(AuditMetadataKey.BYTE_COUNT, byte_count),
        )
        duration = None if duration_started is None else max(
            0, int((monotonic() - duration_started) * 1000)
        )
        self._audit_sink.write(AuditEvent(
            correlation_id=correlation_id,
            component=AuditComponent.BACKUP,
            operation=operation,
            outcome=outcome,
            reason_code=reason,
            metadata=metadata,
            duration_ms=duration,
        ))
