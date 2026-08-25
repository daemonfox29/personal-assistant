"""Portable passphrase-derived database keys and trusted approval entry."""

from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
from threading import Lock
import time
from typing import Any, Iterator
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
from personal_assistant.authorization import ApprovalAuthority, ApprovalReceipt
from personal_assistant.key_provider import (
    DatabaseKey,
    DatabaseKeyUnavailableError,
)
from personal_assistant.permissions import (
    ActionKind,
    PermissionDecision,
    evaluate_action,
)


SECURITY_MANIFEST_VERSION = 1
MIN_RECOVERY_PASSPHRASE_CHARS = 12
MIN_HIGH_RISK_PASSCODE_CHARS = 8
MAX_SECRET_CHARS = 1_024
DEFAULT_MAX_FAILED_ATTEMPTS = 5
DEFAULT_LOCKOUT_SECONDS = 60.0
_SAFE_KEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class PortableSecurityError(RuntimeError):
    """A safe expected portable-security failure."""


class SecuritySetupError(PortableSecurityError):
    """Portable recovery setup is missing, unsafe, or already exists."""


class RecoveryUnlockError(PortableSecurityError):
    """Recovery material did not unlock the configured database key."""


class PasscodeVerificationError(PortableSecurityError):
    """High-risk passcode verification failed or is rate-limited."""


@dataclass(frozen=True)
class ScryptParameters:
    """Persisted, validated cross-platform password KDF settings."""

    n: int = 32_768
    r: int = 8
    p: int = 1
    length: int = 32

    def __post_init__(self) -> None:
        if (
            isinstance(self.n, bool)
            or not isinstance(self.n, int)
            or self.n < 16_384
            or self.n > 262_144
            or self.n & (self.n - 1)
        ):
            raise ValueError("Scrypt work factor is outside its safe range.")
        if self.r != 8 or self.p != 1 or self.length != 32:
            raise ValueError("Scrypt parameters do not match the supported profile.")


@dataclass(frozen=True)
class PortableSecuritySettings:
    """Explicit manifest location and stable database-key label."""

    manifest_path: Path
    key_id: str = "primary-memory-key"

    def __post_init__(self) -> None:
        if not isinstance(
            self.manifest_path, Path
        ) or not self.manifest_path.is_absolute():
            raise ValueError("Security manifest path must be explicit and absolute.")
        if self.manifest_path.name in {"", ".", ".."}:
            raise ValueError("Security manifest path must name a file.")
        if not isinstance(self.key_id, str) or not _SAFE_KEY_ID.fullmatch(self.key_id):
            raise ValueError("Database key ID must be a bounded safe label.")


@dataclass(frozen=True)
class _SecurityManifest:
    version: int
    key_id: str
    database_salt: bytes
    database_check: bytes
    passcode_salt: bytes
    passcode_check: bytes
    scrypt: ScryptParameters


class SessionDatabaseKeyProvider:
    """Hold only a derived session key and return short-lived copies."""

    def __init__(self, key_id: str, key_material: bytes | bytearray) -> None:
        if not _SAFE_KEY_ID.fullmatch(key_id):
            raise DatabaseKeyUnavailableError("Database key material is unavailable.")
        if len(key_material) != 32:
            raise DatabaseKeyUnavailableError("Database key material is unavailable.")
        self._key_id = key_id
        self._key = bytearray(key_material)
        self._closed = False
        self._lock = Lock()

    def acquire(self, key_id: str) -> DatabaseKey:
        with self._lock:
            if key_id != self._key_id or self._closed:
                raise DatabaseKeyUnavailableError(
                    "Database key material is unavailable."
                )
            return DatabaseKey(self._key)

    def close(self) -> None:
        """Best-effort overwrite of the application-owned derived key copy."""

        with self._lock:
            for index in range(len(self._key)):
                self._key[index] = 0
            self._closed = True

    def __enter__(self) -> "SessionDatabaseKeyProvider":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class PortableSecurityManager:
    """Create and unlock one portable, versioned recovery manifest."""

    def __init__(
        self,
        settings: PortableSecuritySettings,
        *,
        audit_sink: AuditSink,
        random_bytes: Callable[[int], bytes] = os.urandom,
    ) -> None:
        if not isinstance(audit_sink, AuditSink):
            raise TypeError("Portable security requires an audit sink.")
        if not callable(random_bytes):
            raise TypeError("Portable security requires a random source.")
        self._settings = settings
        self._audit_sink = audit_sink
        self._random_bytes = random_bytes

    @property
    def is_configured(self) -> bool:
        self._validate_parent(require_exists=False)
        try:
            status = self._settings.manifest_path.lstat()
        except FileNotFoundError:
            return False
        if stat.S_ISLNK(status.st_mode) or not stat.S_ISREG(status.st_mode):
            raise SecuritySetupError("Portable security manifest is unsafe.")
        return True

    def setup(
        self,
        recovery_passphrase: str,
        recovery_confirmation: str,
        high_risk_passcode: str,
        passcode_confirmation: str,
        correlation_id: UUID,
    ) -> None:
        """Create recovery metadata only after both secrets verify twice."""

        self._require_uuid(correlation_id)
        self._emit(correlation_id, AuditOutcome.STARTED, AuditReasonCode.NORMAL)
        if (
            self._settings.manifest_path.exists()
            or self._settings.manifest_path.is_symlink()
        ):
            self._emit(
                correlation_id,
                AuditOutcome.FAILED,
                AuditReasonCode.INVALID_CONFIGURATION,
            )
            raise SecuritySetupError("Portable security is already configured.")
        try:
            recovery = self._validated_secret(
                recovery_passphrase,
                recovery_confirmation,
                MIN_RECOVERY_PASSPHRASE_CHARS,
                "Recovery passphrase",
            )
        except SecuritySetupError:
            self._emit(
                correlation_id,
                AuditOutcome.FAILED,
                AuditReasonCode.INVALID_DATA,
            )
            raise
        try:
            passcode = self._validated_secret(
                high_risk_passcode,
                passcode_confirmation,
                MIN_HIGH_RISK_PASSCODE_CHARS,
                "High-risk passcode",
            )
        except SecuritySetupError:
            self._clear(recovery)
            self._emit(
                correlation_id,
                AuditOutcome.FAILED,
                AuditReasonCode.INVALID_DATA,
            )
            raise
        if hmac.compare_digest(bytes(recovery), bytes(passcode)):
            self._clear(recovery)
            self._clear(passcode)
            self._emit(
                correlation_id,
                AuditOutcome.FAILED,
                AuditReasonCode.INVALID_DATA,
            )
            raise SecuritySetupError(
                "Recovery passphrase and high-risk passcode must be different."
            )

        parameters = ScryptParameters()
        database_salt = self._random_bytes(16)
        passcode_salt = self._random_bytes(16)
        if len(database_salt) != 16 or len(passcode_salt) != 16:
            self._clear(recovery)
            self._clear(passcode)
            self._emit(
                correlation_id,
                AuditOutcome.FAILED,
                AuditReasonCode.SAFE_INTERNAL_FAILURE,
            )
            raise SecuritySetupError("Portable security setup failed safely.")
        database_key = bytearray()
        passcode_key = bytearray()
        try:
            database_key = self._derive(
                recovery, database_salt, b"database", parameters
            )
            verification_key = self._derive(
                recovery, database_salt, b"database", parameters
            )
            if not hmac.compare_digest(database_key, verification_key):
                raise SecuritySetupError("Recovery verification failed safely.")
            self._clear(verification_key)
            passcode_key = self._derive(
                passcode, passcode_salt, b"approval", parameters
            )
            manifest = _SecurityManifest(
                SECURITY_MANIFEST_VERSION,
                self._settings.key_id,
                database_salt,
                self._check(database_key, b"database-key-check"),
                passcode_salt,
                self._check(passcode_key, b"approval-passcode-check"),
                parameters,
            )
            self._write_manifest(manifest)
        except PortableSecurityError:
            self._emit(
                correlation_id,
                AuditOutcome.FAILED,
                AuditReasonCode.INVALID_CONFIGURATION,
            )
            raise
        except Exception as error:
            self._emit(
                correlation_id,
                AuditOutcome.FAILED,
                AuditReasonCode.SAFE_INTERNAL_FAILURE,
            )
            raise SecuritySetupError(
                "Portable security setup failed safely."
            ) from error
        finally:
            self._clear(recovery)
            self._clear(passcode)
            self._clear(database_key)
            self._clear(passcode_key)
        try:
            self._emit(correlation_id, AuditOutcome.SUCCEEDED, AuditReasonCode.NORMAL)
        except Exception:
            try:
                self._settings.manifest_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def unlock(
        self,
        recovery_passphrase: str,
        correlation_id: UUID,
    ) -> SessionDatabaseKeyProvider:
        """Derive and verify the database key without persisting it."""

        self._require_uuid(correlation_id)
        self._emit(correlation_id, AuditOutcome.STARTED, AuditReasonCode.NORMAL)
        try:
            manifest = self._load_manifest()
            secret = self._secret_bytes(
                recovery_passphrase,
                MIN_RECOVERY_PASSPHRASE_CHARS,
                "Recovery passphrase",
            )
        except PortableSecurityError:
            self._emit(
                correlation_id,
                AuditOutcome.FAILED,
                AuditReasonCode.INVALID_CONFIGURATION,
            )
            raise
        derived = bytearray()
        try:
            derived = self._derive(
                secret,
                manifest.database_salt,
                b"database",
                manifest.scrypt,
            )
            supplied_check = self._check(derived, b"database-key-check")
            if not hmac.compare_digest(supplied_check, manifest.database_check):
                raise RecoveryUnlockError("Recovery passphrase is incorrect.")
            provider = SessionDatabaseKeyProvider(manifest.key_id, derived)
        except RecoveryUnlockError:
            self._emit(
                correlation_id,
                AuditOutcome.DENIED,
                AuditReasonCode.APPROVAL_INVALID,
            )
            raise
        except Exception as error:
            self._emit(
                correlation_id,
                AuditOutcome.FAILED,
                AuditReasonCode.SAFE_INTERNAL_FAILURE,
            )
            raise RecoveryUnlockError("Recovery unlock failed safely.") from error
        finally:
            self._clear(secret)
            self._clear(derived)
        try:
            self._emit(correlation_id, AuditOutcome.SUCCEEDED, AuditReasonCode.NORMAL)
        except Exception:
            provider.close()
            raise
        return provider

    def verify_passcode(self, passcode: str) -> bool:
        """Return only whether the high-risk passcode matches."""

        manifest = self._load_manifest()
        try:
            secret = self._secret_bytes(
                passcode,
                MIN_HIGH_RISK_PASSCODE_CHARS,
                "High-risk passcode",
            )
        except PortableSecurityError:
            return False
        derived = bytearray()
        try:
            derived = self._derive(
                secret,
                manifest.passcode_salt,
                b"approval",
                manifest.scrypt,
            )
            supplied_check = self._check(derived, b"approval-passcode-check")
            return hmac.compare_digest(supplied_check, manifest.passcode_check)
        except Exception:
            return False
        finally:
            self._clear(secret)
            self._clear(derived)

    def _load_manifest(self) -> _SecurityManifest:
        path = self._settings.manifest_path
        try:
            self._validate_parent(require_exists=True)
            status = path.lstat()
            if stat.S_ISLNK(status.st_mode) or not stat.S_ISREG(status.st_mode):
                raise SecuritySetupError("Portable security manifest is unsafe.")
            if status.st_size > 16_384:
                raise SecuritySetupError("Portable security manifest is invalid.")
            document = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(document, dict) or set(document) != {
                "version",
                "key_id",
                "database_salt",
                "database_check",
                "passcode_salt",
                "passcode_check",
                "scrypt",
            }:
                raise SecuritySetupError("Portable security manifest is invalid.")
            kdf = document["scrypt"]
            if not isinstance(kdf, dict) or set(kdf) != {"n", "r", "p", "length"}:
                raise SecuritySetupError("Portable security manifest is invalid.")
            manifest = _SecurityManifest(
                int(document["version"]),
                str(document["key_id"]),
                self._decode(document["database_salt"], 16),
                self._decode(document["database_check"], 32),
                self._decode(document["passcode_salt"], 16),
                self._decode(document["passcode_check"], 32),
                ScryptParameters(
                    int(kdf["n"]),
                    int(kdf["r"]),
                    int(kdf["p"]),
                    int(kdf["length"]),
                ),
            )
        except PortableSecurityError:
            raise
        except Exception as error:
            raise SecuritySetupError(
                "Portable security manifest is invalid."
            ) from error
        if (
            manifest.version != SECURITY_MANIFEST_VERSION
            or manifest.key_id != self._settings.key_id
        ):
            raise SecuritySetupError("Portable security manifest is incompatible.")
        return manifest

    def _write_manifest(self, manifest: _SecurityManifest) -> None:
        path = self._settings.manifest_path
        parent = path.parent
        try:
            if parent.exists():
                status = parent.lstat()
                if stat.S_ISLNK(status.st_mode) or not stat.S_ISDIR(status.st_mode):
                    raise SecuritySetupError("Portable security directory is unsafe.")
            else:
                parent.mkdir(parents=True, mode=0o700)
            if os.name == "posix":
                parent.chmod(0o700)
            document = {
                "version": manifest.version,
                "key_id": manifest.key_id,
                "database_salt": self._encode(manifest.database_salt),
                "database_check": self._encode(manifest.database_check),
                "passcode_salt": self._encode(manifest.passcode_salt),
                "passcode_check": self._encode(manifest.passcode_check),
                "scrypt": {
                    "n": manifest.scrypt.n,
                    "r": manifest.scrypt.r,
                    "p": manifest.scrypt.p,
                    "length": manifest.scrypt.length,
                },
            }
            encoded = json.dumps(
                document,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            partial = parent / f".{path.name}.{uuid4().hex}.partial"
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            flags |= getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(partial, flags, 0o600)
            try:
                with os.fdopen(descriptor, "wb", closefd=False) as stream:
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
            finally:
                os.close(descriptor)
            os.replace(partial, path)
            if os.name == "posix":
                path.chmod(0o600)
        except PortableSecurityError:
            raise
        except Exception as error:
            try:
                partial.unlink(missing_ok=True)
            except (OSError, UnboundLocalError):
                pass
            raise SecuritySetupError(
                "Portable security setup failed safely."
            ) from error

    def _validate_parent(self, *, require_exists: bool) -> None:
        parent = self._settings.manifest_path.parent
        try:
            status = parent.lstat()
        except FileNotFoundError:
            if require_exists:
                raise SecuritySetupError(
                    "Portable security directory is unavailable."
                )
            return
        if stat.S_ISLNK(status.st_mode) or not stat.S_ISDIR(status.st_mode):
            raise SecuritySetupError("Portable security directory is unsafe.")

    @staticmethod
    def _derive(
        secret: bytearray,
        salt: bytes,
        domain: bytes,
        parameters: ScryptParameters,
    ) -> bytearray:
        return bytearray(
            hashlib.scrypt(
                bytes(secret),
                salt=domain + b"\x00" + salt,
                n=parameters.n,
                r=parameters.r,
                p=parameters.p,
                maxmem=128 * 1024 * 1024,
                dklen=parameters.length,
            )
        )

    @staticmethod
    def _check(key: bytes | bytearray, label: bytes) -> bytes:
        return hmac.new(bytes(key), label, sha256).digest()

    @staticmethod
    def _encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("ascii")

    @staticmethod
    def _decode(value: Any, length: int) -> bytes:
        if not isinstance(value, str) or len(value) > 256:
            raise SecuritySetupError("Portable security manifest is invalid.")
        decoded = base64.b64decode(value, altchars=b"-_", validate=True)
        if len(decoded) != length:
            raise SecuritySetupError("Portable security manifest is invalid.")
        return decoded

    @staticmethod
    def _validated_secret(
        value: str,
        confirmation: str,
        minimum: int,
        label: str,
    ) -> bytearray:
        if not isinstance(confirmation, str) or value != confirmation:
            raise SecuritySetupError(f"{label} confirmation does not match.")
        return PortableSecurityManager._secret_bytes(value, minimum, label)

    @staticmethod
    def _secret_bytes(value: str, minimum: int, label: str) -> bytearray:
        if (
            not isinstance(value, str)
            or len(value) < minimum
            or len(value) > MAX_SECRET_CHARS
            or "\x00" in value
        ):
            raise SecuritySetupError(f"{label} length is invalid.")
        return bytearray(value.encode("utf-8"))

    @staticmethod
    def _clear(value: bytearray) -> None:
        for index in range(len(value)):
            value[index] = 0

    @staticmethod
    def _require_uuid(value: UUID) -> None:
        if not isinstance(value, UUID):
            raise ValueError("Security correlation ID must be a UUID.")

    def _emit(
        self,
        correlation_id: UUID,
        outcome: AuditOutcome,
        reason: AuditReasonCode,
    ) -> None:
        self._audit_sink.write(
            AuditEvent(
                correlation_id=correlation_id,
                component=AuditComponent.AUTHORIZATION,
                operation=AuditOperation.CONFIGURATION_VALIDATE,
                outcome=outcome,
                reason_code=reason,
                metadata=(
                    AuditMetadataItem(
                        AuditMetadataKey.TARGET_CLASS,
                        "portable_security",
                    ),
                ),
            )
        )


@dataclass(frozen=True)
class ApprovalGrant:
    receipt: ApprovalReceipt
    authority: ApprovalAuthority


class PasscodeApprovalGate:
    """Rate-limit passcode checks and mint exact receipts after success."""

    def __init__(
        self,
        security: PortableSecurityManager,
        *,
        audit_sink: AuditSink,
        authority: ApprovalAuthority | None = None,
        clock: Callable[[], float] = time.time,
        receipt_clock: Callable[[], float] = time.monotonic,
        max_failed_attempts: int = DEFAULT_MAX_FAILED_ATTEMPTS,
        lockout_seconds: float = DEFAULT_LOCKOUT_SECONDS,
        state_path: Path | None = None,
    ) -> None:
        if not isinstance(security, PortableSecurityManager):
            raise TypeError("Passcode gate requires portable security.")
        if not isinstance(audit_sink, AuditSink):
            raise TypeError("Passcode gate requires an audit sink.")
        if not 1 <= max_failed_attempts <= 10 or not 1 <= lockout_seconds <= 900:
            raise ValueError("Passcode rate limit is outside its safe range.")
        self._security = security
        self._audit_sink = audit_sink
        self._authority = authority or ApprovalAuthority(clock=receipt_clock)
        self._clock = clock
        self._max_failed_attempts = max_failed_attempts
        self._lockout_seconds = float(lockout_seconds)
        if state_path is not None and (
            not isinstance(state_path, Path) or not state_path.is_absolute()
        ):
            raise ValueError("Passcode rate-limit state path must be absolute.")
        self._state_path = state_path
        self._failed_attempts = 0
        self._locked_until = 0.0
        self._lock = Lock()
        self._load_state()

    def approve(
        self,
        action: ActionKind,
        arguments: Mapping[str, object],
        passcode: str,
        correlation_id: UUID,
    ) -> ApprovalGrant:
        """Verify locally, then issue one receipt for the displayed request."""

        if evaluate_action(action).decision is not PermissionDecision.REQUIRE_APPROVAL:
            raise PasscodeVerificationError(
                "Passcodes apply only to approval-required actions."
            )
        with self._approval_lock():
            try:
                self._load_state()
            except PasscodeVerificationError:
                self._emit(
                    correlation_id,
                    action,
                    AuditOutcome.FAILED,
                    AuditReasonCode.SAFE_INTERNAL_FAILURE,
                )
                raise
            now = self._clock()
            if now < self._locked_until:
                self._emit(
                    correlation_id,
                    action,
                    AuditOutcome.DENIED,
                    AuditReasonCode.RESOURCE_LIMIT,
                )
                raise PasscodeVerificationError(
                    "High-risk authentication is temporarily locked."
                )

            verified = self._security.verify_passcode(passcode)
            if not verified:
                self._failed_attempts += 1
                if self._failed_attempts >= self._max_failed_attempts:
                    self._locked_until = now + self._lockout_seconds
                    self._failed_attempts = 0
                try:
                    self._save_state()
                except PasscodeVerificationError:
                    self._emit(
                        correlation_id,
                        action,
                        AuditOutcome.FAILED,
                        AuditReasonCode.SAFE_INTERNAL_FAILURE,
                    )
                    raise
                self._emit(
                    correlation_id,
                    action,
                    AuditOutcome.DENIED,
                    AuditReasonCode.APPROVAL_INVALID,
                )
                raise PasscodeVerificationError("High-risk passcode is incorrect.")
            self._failed_attempts = 0
            self._locked_until = 0.0
            try:
                self._save_state()
            except PasscodeVerificationError:
                self._emit(
                    correlation_id,
                    action,
                    AuditOutcome.FAILED,
                    AuditReasonCode.SAFE_INTERNAL_FAILURE,
                )
                raise

            receipt = self._authority.issue(action, arguments)
        self._emit(
            correlation_id,
            action,
            AuditOutcome.SUCCEEDED,
            AuditReasonCode.NORMAL,
        )
        return ApprovalGrant(receipt, self._authority)

    @contextmanager
    def _approval_lock(self) -> Iterator[None]:
        """Serialize expensive checks across threads and local processes."""

        process_lock: Path | None = None
        descriptor: int | None = None
        with self._lock:
            if self._state_path is not None:
                process_lock = self._state_path.with_name(
                    f".{self._state_path.name}.lock"
                )
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                flags |= getattr(os, "O_NOFOLLOW", 0)
                try:
                    descriptor = os.open(process_lock, flags, 0o600)
                    os.write(descriptor, b"locked\n")
                    os.fsync(descriptor)
                except FileExistsError as error:
                    raise PasscodeVerificationError(
                        "High-risk authentication is already in progress."
                    ) from error
                except OSError as error:
                    if descriptor is not None:
                        os.close(descriptor)
                    if process_lock is not None:
                        try:
                            status = process_lock.lstat()
                            if stat.S_ISREG(status.st_mode):
                                process_lock.unlink()
                        except OSError:
                            pass
                    raise PasscodeVerificationError(
                        "High-risk authentication state is unavailable."
                    ) from error
            try:
                yield
            finally:
                if descriptor is not None:
                    os.close(descriptor)
                if process_lock is not None:
                    try:
                        status = process_lock.lstat()
                        if stat.S_ISREG(status.st_mode):
                            process_lock.unlink()
                    except OSError:
                        pass

    def _load_state(self) -> None:
        if self._state_path is None:
            return
        try:
            status = self._state_path.lstat()
        except FileNotFoundError:
            return
        try:
            if stat.S_ISLNK(status.st_mode) or not stat.S_ISREG(status.st_mode):
                raise ValueError
            if status.st_size > 1_024:
                raise ValueError
            document = json.loads(self._state_path.read_text(encoding="utf-8"))
            if not isinstance(document, dict) or set(document) != {
                "failed_attempts",
                "locked_until",
                "version",
            }:
                raise ValueError
            failures = document["failed_attempts"]
            locked_until = document["locked_until"]
            if (
                document["version"] != 1
                or isinstance(failures, bool)
                or not isinstance(failures, int)
                or not 0 <= failures < self._max_failed_attempts
                or isinstance(locked_until, bool)
                or not isinstance(locked_until, (int, float))
                or locked_until < 0
            ):
                raise ValueError
            self._failed_attempts = failures
            self._locked_until = float(locked_until)
        except Exception as error:
            self._failed_attempts = 0
            self._locked_until = self._clock() + self._lockout_seconds
            raise PasscodeVerificationError(
                "High-risk authentication state is unavailable."
            ) from error

    def _save_state(self) -> None:
        if self._state_path is None:
            return
        path = self._state_path
        partial = path.parent / f".{path.name}.{uuid4().hex}.partial"
        try:
            parent_status = path.parent.lstat()
            if stat.S_ISLNK(parent_status.st_mode) or not stat.S_ISDIR(
                parent_status.st_mode
            ):
                raise OSError
            if path.exists() or path.is_symlink():
                status = path.lstat()
                if stat.S_ISLNK(status.st_mode) or not stat.S_ISREG(status.st_mode):
                    raise OSError
            encoded = json.dumps(
                {
                    "failed_attempts": self._failed_attempts,
                    "locked_until": self._locked_until,
                    "version": 1,
                },
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            flags |= getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(partial, flags, 0o600)
            try:
                with os.fdopen(descriptor, "wb", closefd=False) as stream:
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
            finally:
                os.close(descriptor)
            os.replace(partial, path)
            if os.name == "posix":
                path.chmod(0o600)
        except Exception as error:
            try:
                partial.unlink(missing_ok=True)
            except OSError:
                pass
            raise PasscodeVerificationError(
                "High-risk authentication state is unavailable."
            ) from error

    def _emit(
        self,
        correlation_id: UUID,
        action: ActionKind,
        outcome: AuditOutcome,
        reason: AuditReasonCode,
    ) -> None:
        self._audit_sink.write(
            AuditEvent(
                correlation_id=correlation_id,
                component=AuditComponent.AUTHORIZATION,
                operation=AuditOperation.APPROVAL_VERIFY,
                outcome=outcome,
                reason_code=reason,
                metadata=(
                    AuditMetadataItem(AuditMetadataKey.ACTION_KIND, action.value),
                    AuditMetadataItem(
                        AuditMetadataKey.APPROVAL_STATE,
                        "verified" if outcome is AuditOutcome.SUCCEEDED else "denied",
                    ),
                ),
            )
        )
