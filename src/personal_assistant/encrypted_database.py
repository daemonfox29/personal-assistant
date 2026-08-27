"""Fail-closed SQLCipher connection boundary for canonical local data."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import re
import stat
from typing import Any, ContextManager, Protocol, runtime_checkable
from uuid import UUID

from sqlcipher3 import dbapi2 as sqlcipher

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
from personal_assistant.key_provider import (
    DatabaseKey,
    DatabaseKeyProvider,
    DatabaseKeyUnavailableError,
)


_SAFE_KEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
REQUIRED_SQLCIPHER_MAJOR = "4"
MAX_DATABASE_TIMEOUT_SECONDS = 300.0
MAX_BUSY_TIMEOUT_MS = 60_000


class EncryptedDatabaseError(RuntimeError):
    """A safe expected failure at the encrypted database boundary."""


class EncryptedDatabaseConfigurationError(EncryptedDatabaseError):
    """The database target or settings violate the local safety contract."""


class EncryptedDatabaseOpenError(EncryptedDatabaseError):
    """The encrypted database file could not be opened."""


class EncryptedDatabaseUnlockError(EncryptedDatabaseError):
    """The configured key could not unlock the encrypted database."""


class EncryptionUnavailableError(EncryptedDatabaseError):
    """The active SQLite driver did not prove that encryption is enabled."""


@runtime_checkable
class EncryptedConnectionProvider(Protocol):
    """Replaceable source of verified, short-lived encrypted connections."""

    def connect(self, correlation_id: UUID) -> ContextManager[Any]:
        """Return a context manager for one verified connection."""


@dataclass(frozen=True)
class EncryptedDatabaseSettings:
    """Explicit path, key identifier, and bounded connection settings."""

    path: Path
    key_id: str
    timeout_seconds: float = 5.0
    busy_timeout_ms: int = 5_000
    require_existing: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.path, Path) or not self.path.is_absolute():
            raise ValueError("The database path must be an explicit absolute path.")
        if self.path.name in {"", ".", ".."}:
            raise ValueError("The database path must name a file.")
        if not isinstance(self.key_id, str) or not _SAFE_KEY_ID.fullmatch(
            self.key_id
        ):
            raise ValueError("The database key ID must be a bounded safe label.")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not 0 < self.timeout_seconds <= MAX_DATABASE_TIMEOUT_SECONDS
        ):
            raise ValueError("The database timeout must be within its safe range.")
        if (
            isinstance(self.busy_timeout_ms, bool)
            or not isinstance(self.busy_timeout_ms, int)
            or not 0 < self.busy_timeout_ms <= MAX_BUSY_TIMEOUT_MS
        ):
            raise ValueError(
                "The database busy timeout must be within its safe range."
            )
        if not isinstance(self.require_existing, bool):
            raise ValueError("The database creation policy must be explicit.")


class EncryptedDatabase:
    """Open verified SQLCipher connections without a plaintext fallback."""

    def __init__(
        self,
        settings: EncryptedDatabaseSettings,
        *,
        key_provider: DatabaseKeyProvider,
        audit_sink: AuditSink,
    ) -> None:
        if not isinstance(key_provider, DatabaseKeyProvider):
            raise TypeError("Encrypted database requires a key provider.")
        if not isinstance(audit_sink, AuditSink):
            raise TypeError("Encrypted database requires an audit sink.")
        self._settings = settings
        self._key_provider = key_provider
        self._audit_sink = audit_sink

    @contextmanager
    def connect(self, correlation_id: UUID) -> Iterator[Any]:
        """Yield one verified encrypted connection and always close it."""

        if not isinstance(correlation_id, UUID):
            raise ValueError("Database correlation ID must be a UUID.")
        self._emit(
            correlation_id,
            AuditOutcome.STARTED,
            AuditReasonCode.NORMAL,
        )

        try:
            connection = self._open()
        except EncryptedDatabaseConfigurationError:
            self._emit(
                correlation_id,
                AuditOutcome.FAILED,
                AuditReasonCode.INVALID_CONFIGURATION,
            )
            raise
        except DatabaseKeyUnavailableError:
            self._emit(
                correlation_id,
                AuditOutcome.FAILED,
                AuditReasonCode.KEY_UNAVAILABLE,
            )
            raise
        except EncryptionUnavailableError:
            self._emit(
                correlation_id,
                AuditOutcome.FAILED,
                AuditReasonCode.ENCRYPTION_UNAVAILABLE,
            )
            raise
        except EncryptedDatabaseUnlockError:
            self._emit(
                correlation_id,
                AuditOutcome.FAILED,
                AuditReasonCode.DATABASE_UNLOCK_FAILED,
            )
            raise
        except EncryptedDatabaseOpenError:
            self._emit(
                correlation_id,
                AuditOutcome.FAILED,
                AuditReasonCode.SAFE_INTERNAL_FAILURE,
            )
            raise

        try:
            self._emit(
                correlation_id,
                AuditOutcome.SUCCEEDED,
                AuditReasonCode.NORMAL,
            )
        except Exception:
            connection.close()
            raise

        try:
            yield connection
        finally:
            connection.close()

    def _open(self) -> Any:
        self._validate_target()
        key = self._acquire_key()
        try:
            try:
                connection = sqlcipher.connect(
                    str(self._settings.path),
                    timeout=float(self._settings.timeout_seconds),
                    check_same_thread=True,
                )
            except sqlcipher.Error as error:
                raise EncryptedDatabaseOpenError(
                    "Encrypted database could not be opened."
                ) from error

            try:
                connection.enable_load_extension(False)
                self._configure_key(connection, key)
                self._verify_cipher(connection)
                self._verify_required_features(connection)
                self._verify_key(connection)
                self._configure_connection(connection)
                self._restrict_file_permissions()
                return connection
            except EncryptedDatabaseError:
                connection.close()
                raise
            except (OSError, sqlcipher.Error) as error:
                connection.close()
                raise EncryptedDatabaseOpenError(
                    "Encrypted database could not be configured."
                ) from error
        finally:
            key.clear()

    def _acquire_key(self) -> DatabaseKey:
        try:
            key = self._key_provider.acquire(self._settings.key_id)
        except DatabaseKeyUnavailableError:
            raise
        except Exception as error:
            raise DatabaseKeyUnavailableError(
                "Database key material is unavailable."
            ) from error
        if not isinstance(key, DatabaseKey):
            raise DatabaseKeyUnavailableError(
                "Database key material is unavailable."
            )
        return key

    @staticmethod
    def _configure_key(connection: Any, key: DatabaseKey) -> None:
        key_hex = key._sqlcipher_hex()
        try:
            connection.execute(f'PRAGMA key = "x\'{key_hex}\'"')
        finally:
            key_hex = ""

    @staticmethod
    def _verify_cipher(connection: Any) -> None:
        status_row = connection.execute("PRAGMA cipher_status").fetchone()
        version_row = connection.execute("PRAGMA cipher_version").fetchone()
        status = None if status_row is None else str(status_row[0])
        version = None if version_row is None else str(version_row[0])
        if status != "1" or not version:
            raise EncryptionUnavailableError(
                "The active database driver did not enable encryption."
            )
        if version.split(".", 1)[0] != REQUIRED_SQLCIPHER_MAJOR:
            raise EncryptionUnavailableError(
                "The active SQLCipher major version is not supported."
            )

    @staticmethod
    def _verify_required_features(connection: Any) -> None:
        compile_options = {
            str(row[0])
            for row in connection.execute("PRAGMA compile_options").fetchall()
        }
        if "HAS_CODEC" not in compile_options or "ENABLE_FTS5" not in compile_options:
            raise EncryptionUnavailableError(
                "The encrypted database driver lacks required features."
            )

    @staticmethod
    def _verify_key(connection: Any) -> None:
        try:
            connection.execute("SELECT count(*) FROM sqlite_master").fetchone()
        except sqlcipher.DatabaseError as error:
            raise EncryptedDatabaseUnlockError(
                "Encrypted database could not be unlocked."
            ) from error

    def _configure_connection(self, connection: Any) -> None:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA trusted_schema = OFF")
        connection.execute(f"PRAGMA busy_timeout = {self._settings.busy_timeout_ms}")
        foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()
        trusted_schema = connection.execute("PRAGMA trusted_schema").fetchone()
        if foreign_keys != (1,) or trusted_schema != (0,):
            raise EncryptedDatabaseOpenError(
                "Encrypted database safety settings could not be applied."
            )
        connection.set_authorizer(self._authorize_sql)

    @staticmethod
    def _authorize_sql(
        action: int,
        argument_one: str | None,
        argument_two: str | None,
        database_name: str | None,
        trigger_name: str | None,
    ) -> int:
        """Block unused high-risk SQLite capabilities at the connection edge."""

        del database_name, trigger_name
        if action in {sqlcipher.SQLITE_ATTACH, sqlcipher.SQLITE_DETACH}:
            return sqlcipher.SQLITE_DENY
        function_name = (argument_two or argument_one or "").casefold()
        if action == sqlcipher.SQLITE_FUNCTION and function_name in {
            "rtreenode",
            "rtreedepth",
            "rtreecheck",
        }:
            return sqlcipher.SQLITE_DENY
        return sqlcipher.SQLITE_OK

    def _validate_target(self) -> None:
        parent = self._settings.path.parent
        try:
            parent_status = parent.lstat()
        except OSError as error:
            raise EncryptedDatabaseConfigurationError(
                "The configured database directory is unavailable."
            ) from error
        if stat.S_ISLNK(parent_status.st_mode) or not stat.S_ISDIR(
            parent_status.st_mode
        ):
            raise EncryptedDatabaseConfigurationError(
                "The configured database directory is unsafe."
            )

        try:
            file_status = self._settings.path.lstat()
        except FileNotFoundError:
            if self._settings.require_existing:
                raise EncryptedDatabaseConfigurationError(
                    "The configured database file is unavailable."
                )
            return
        except OSError as error:
            raise EncryptedDatabaseConfigurationError(
                "The configured database file is unavailable."
            ) from error
        if stat.S_ISLNK(file_status.st_mode) or not stat.S_ISREG(
            file_status.st_mode
        ):
            raise EncryptedDatabaseConfigurationError(
                "The configured database file is unsafe."
            )

    def _restrict_file_permissions(self) -> None:
        if os.name == "posix":
            self._settings.path.chmod(0o600)

    def _emit(
        self,
        correlation_id: UUID,
        outcome: AuditOutcome,
        reason_code: AuditReasonCode,
    ) -> None:
        self._audit_sink.write(
            AuditEvent(
                correlation_id=correlation_id,
                component=AuditComponent.DATABASE,
                operation=AuditOperation.DATABASE_OPEN,
                outcome=outcome,
                reason_code=reason_code,
                metadata=(
                    AuditMetadataItem(
                        AuditMetadataKey.TARGET_CLASS,
                        "encrypted_sqlite",
                    ),
                ),
            )
        )
