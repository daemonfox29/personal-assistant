"""Forward-only, checksummed migrations for the encrypted memory database."""

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from importlib import resources
import re
from time import monotonic
from typing import Any, Protocol, runtime_checkable
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
from personal_assistant.encrypted_database import EncryptedConnectionProvider


_MIGRATION_FILE = re.compile(r"^(?P<version>[0-9]{3})_(?P<name>[a-z0-9_]+)\.sql$")
_MIGRATION_NAME = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_TRANSACTION_CONTROL = re.compile(
    r"\b(?:BEGIN|COMMIT|END|ROLLBACK|SAVEPOINT|RELEASE)\b",
    re.IGNORECASE,
)
MAX_MIGRATION_BYTES = 1_048_576
MIGRATION_PACKAGE = "personal_assistant.migrations"
SCHEMA_COMPATIBILITY = "personal-assistant-module-1"


class MigrationError(RuntimeError):
    """A safe expected failure while validating or applying migrations."""


class MigrationSourceError(MigrationError):
    """Packaged migrations violate the fixed source contract."""


class MigrationHistoryError(MigrationError):
    """Stored migration history does not match the packaged source."""


class MigrationApplyError(MigrationError):
    """A pending migration could not be applied transactionally."""


@dataclass(frozen=True)
class Migration:
    """One exact SQL statement and the checksum of its packaged bytes."""

    version: int
    name: str
    statement: str
    checksum: str

    def __post_init__(self) -> None:
        if (
            isinstance(self.version, bool)
            or not isinstance(self.version, int)
            or not 1 <= self.version <= 999
        ):
            raise MigrationSourceError("Migration version is invalid.")
        if not isinstance(self.name, str) or not _MIGRATION_NAME.fullmatch(self.name):
            raise MigrationSourceError("Migration name is invalid.")
        if not isinstance(self.statement, str) or not self.statement.strip():
            raise MigrationSourceError("Migration statement is empty.")
        if "\x00" in self.statement:
            raise MigrationSourceError("Migration statement is invalid.")
        if _TRANSACTION_CONTROL.search(self.statement):
            raise MigrationSourceError(
                "Migration statements cannot control transactions."
            )
        if not isinstance(self.checksum, str) or not re.fullmatch(
            r"[0-9a-f]{64}", self.checksum
        ):
            raise MigrationSourceError("Migration checksum is invalid.")
        if sha256(self.statement.encode("utf-8")).hexdigest() != self.checksum:
            raise MigrationSourceError("Migration checksum does not match its content.")

    @classmethod
    def from_bytes(cls, version: int, name: str, content: bytes) -> "Migration":
        """Decode one bounded UTF-8 migration and hash its exact bytes."""

        if not isinstance(content, bytes) or not 0 < len(content) <= MAX_MIGRATION_BYTES:
            raise MigrationSourceError("Migration size is invalid.")
        try:
            statement = content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise MigrationSourceError("Migration encoding is invalid.") from error
        return cls(version, name, statement, sha256(content).hexdigest())


@runtime_checkable
class MigrationSource(Protocol):
    """Replaceable source used to test migration-history failure modes."""

    def load(self) -> tuple[Migration, ...]:
        """Return migrations in the exact order they must be applied."""


class PackageMigrationSource:
    """Load immutable numbered SQL resources from the installed package."""

    def __init__(self, package: str = MIGRATION_PACKAGE) -> None:
        self._package = package

    def load(self) -> tuple[Migration, ...]:
        try:
            directory = resources.files(self._package)
            paths = sorted(
                (
                    path
                    for path in directory.iterdir()
                    if path.name.endswith(".sql")
                ),
                key=lambda path: path.name,
            )
        except (ModuleNotFoundError, OSError) as error:
            raise MigrationSourceError("Migration package is unavailable.") from error

        migrations: list[Migration] = []
        for path in paths:
            match = _MIGRATION_FILE.fullmatch(path.name)
            if match is None:
                raise MigrationSourceError("Migration filename is invalid.")
            try:
                content = path.read_bytes()
            except OSError as error:
                raise MigrationSourceError("Migration file is unavailable.") from error
            migrations.append(
                Migration.from_bytes(
                    int(match.group("version")),
                    match.group("name"),
                    content,
                )
            )
        return tuple(migrations)


@dataclass(frozen=True)
class MigrationResult:
    """The versions committed by one runner invocation."""

    applied_versions: tuple[int, ...]
    current_version: int


class MigrationRunner:
    """Validate exact history and atomically apply the complete pending batch."""

    def __init__(
        self,
        *,
        connection_provider: EncryptedConnectionProvider,
        migration_source: MigrationSource,
        audit_sink: AuditSink,
    ) -> None:
        if not isinstance(connection_provider, EncryptedConnectionProvider):
            raise TypeError("Migration runner requires a connection provider.")
        if not isinstance(migration_source, MigrationSource):
            raise TypeError("Migration runner requires a migration source.")
        if not isinstance(audit_sink, AuditSink):
            raise TypeError("Migration runner requires an audit sink.")
        self._connection_provider = connection_provider
        self._migration_source = migration_source
        self._audit_sink = audit_sink

    def migrate(self, correlation_id: UUID) -> MigrationResult:
        """Apply all pending migrations or preserve the prior schema unchanged."""

        if not isinstance(correlation_id, UUID):
            raise ValueError("Migration correlation ID must be a UUID.")
        started_at = monotonic()
        try:
            migrations = self._validated_source()
        except MigrationError:
            self._emit(
                correlation_id,
                AuditOutcome.FAILED,
                AuditReasonCode.MIGRATION_FAILED,
                0,
                started_at,
            )
            raise

        self._emit(
            correlation_id,
            AuditOutcome.STARTED,
            AuditReasonCode.NORMAL,
            len(migrations),
            started_at,
        )

        try:
            with self._connection_provider.connect(correlation_id) as connection:
                applied = self._load_and_validate_history(connection, migrations)
                pending = migrations[len(applied) :]
                self._apply_pending(connection, pending)
        except MigrationError:
            self._emit(
                correlation_id,
                AuditOutcome.FAILED,
                AuditReasonCode.MIGRATION_FAILED,
                0,
                started_at,
            )
            raise
        except Exception as error:
            self._emit(
                correlation_id,
                AuditOutcome.FAILED,
                AuditReasonCode.MIGRATION_FAILED,
                0,
                started_at,
            )
            raise MigrationApplyError("Database migration failed safely.") from error

        current_version = migrations[-1].version if migrations else 0
        result = MigrationResult(
            tuple(migration.version for migration in pending),
            current_version,
        )
        self._emit(
            correlation_id,
            AuditOutcome.SUCCEEDED,
            AuditReasonCode.NORMAL,
            len(result.applied_versions),
            started_at,
        )
        return result

    def _validated_source(self) -> tuple[Migration, ...]:
        try:
            migrations = self._migration_source.load()
        except MigrationError:
            raise
        except Exception as error:
            raise MigrationSourceError("Migration source is unavailable.") from error
        if not isinstance(migrations, tuple) or not migrations:
            raise MigrationSourceError("Migration source must not be empty.")

        for expected_version, migration in enumerate(migrations, start=1):
            if not isinstance(migration, Migration):
                raise MigrationSourceError("Migration source contains invalid data.")
            if migration.version != expected_version:
                raise MigrationSourceError(
                    "Migrations must be complete and in fixed numeric order."
                )
        names = {migration.name for migration in migrations}
        if len(names) != len(migrations):
            raise MigrationSourceError("Migration names must be unique.")
        return migrations

    @staticmethod
    def _load_and_validate_history(
        connection: Any,
        migrations: tuple[Migration, ...],
    ) -> tuple[tuple[int, str, str, str], ...]:
        try:
            has_history = connection.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type = 'table' AND name = 'schema_migrations'"
            ).fetchone()
            if has_history is None:
                user_tables = connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
                if user_tables:
                    raise MigrationHistoryError(
                        "Database has schema objects without migration history."
                    )
                return ()
            rows = tuple(
                connection.execute(
                    "SELECT version, name, checksum, compatibility "
                    "FROM schema_migrations ORDER BY version"
                ).fetchall()
            )
        except MigrationHistoryError:
            raise
        except Exception as error:
            raise MigrationHistoryError(
                "Migration history could not be validated."
            ) from error

        if len(rows) > len(migrations):
            raise MigrationHistoryError(
                "Database migration history is newer than this application."
            )
        for index, row in enumerate(rows):
            expected = migrations[index]
            if (
                not isinstance(row, tuple)
                or len(row) != 4
                or row[0] != expected.version
                or row[1] != expected.name
                or row[2] != expected.checksum
                or row[3] != SCHEMA_COMPATIBILITY
            ):
                raise MigrationHistoryError(
                    "Database migration history does not match this application."
                )
        return rows

    @staticmethod
    def _apply_pending(connection: Any, pending: tuple[Migration, ...]) -> None:
        if not pending:
            return
        try:
            connection.execute("BEGIN IMMEDIATE")
            for migration in pending:
                connection.execute(migration.statement)
                connection.execute(
                    "INSERT INTO schema_migrations "
                    "(version, name, checksum, applied_at, compatibility) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        migration.version,
                        migration.name,
                        migration.checksum,
                        datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        SCHEMA_COMPATIBILITY,
                    ),
                )
            connection.commit()
        except Exception as error:
            try:
                connection.rollback()
            except Exception:
                pass
            raise MigrationApplyError("Database migration failed safely.") from error

    def _emit(
        self,
        correlation_id: UUID,
        outcome: AuditOutcome,
        reason_code: AuditReasonCode,
        item_count: int,
        started_at: float,
    ) -> None:
        duration_ms = max(0, int((monotonic() - started_at) * 1_000))
        self._audit_sink.write(
            AuditEvent(
                correlation_id=correlation_id,
                component=AuditComponent.DATABASE,
                operation=AuditOperation.DATABASE_MIGRATE,
                outcome=outcome,
                reason_code=reason_code,
                metadata=(
                    AuditMetadataItem(
                        AuditMetadataKey.TARGET_CLASS,
                        "encrypted_sqlite_schema",
                    ),
                    AuditMetadataItem(AuditMetadataKey.ITEM_COUNT, item_count),
                ),
                duration_ms=duration_ms,
            )
        )
