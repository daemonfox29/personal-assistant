"""Operating-system credential storage for optional automatic memory unlock."""

from dataclasses import dataclass
from hashlib import sha256
import hmac
from pathlib import Path
import sys
from threading import Event
from typing import Protocol, runtime_checkable

import keyring
from keyring.backend import KeyringBackend
from keyring.errors import KeyringError, PasswordDeleteError


_ALLOWED_BACKEND_MODULES = frozenset(
    {
        "keyring.backends.macOS",
        "keyring.backends.Windows",
        "keyring.backends.SecretService",
        "keyring.backends.libsecret",
        "keyring.backends.kwallet",
        "keyring.backends.KWallet",
    }
)
_MAX_RECOVERY_SECRET_CHARS = 1_024
_MACOS_UNLOCK_PROMPT = "Unlock encrypted Personal Assistant memory"
_MACOS_AUTHENTICATION_TIMEOUT_SECONDS = 120.0


class CredentialStoreError(RuntimeError):
    """The protected operating-system credential store was unavailable."""


@runtime_checkable
class RecoveryCredentialStore(Protocol):
    """Narrow storage contract for one recovery secret."""

    def read_recovery(self) -> str | None:
        ...

    def write_recovery(self, recovery_passphrase: str) -> None:
        ...

    def delete_recovery(self) -> None:
        ...


@runtime_checkable
class MacOSUserAuthenticator(Protocol):
    """Confirm local device-owner presence through a native macOS prompt."""

    def authenticate(self, prompt: str) -> None:
        ...


@dataclass(frozen=True)
class SystemRecoveryCredentialStore:
    """Store automatic-unlock material only in an approved native backend."""

    data_directory: Path
    account: str = "primary-memory-key"
    backend: KeyringBackend | None = None

    def __post_init__(self) -> None:
        if not isinstance(
            self.data_directory,
            Path,
        ) or not self.data_directory.is_absolute():
            raise ValueError("Credential storage requires an explicit data directory.")
        if not isinstance(self.account, str) or not self.account:
            raise ValueError("Credential storage requires a stable account label.")

    @property
    def service_name(self) -> str:
        return _service_name(self.data_directory)

    def read_recovery(self) -> str | None:
        backend = self._approved_backend()
        try:
            secret = backend.get_password(self.service_name, self.account)
        except KeyringError as error:
            raise CredentialStoreError(
                "The operating-system credential store is unavailable."
            ) from error
        if secret is None:
            return None
        if not isinstance(secret, str) or not 1 <= len(
            secret
        ) <= _MAX_RECOVERY_SECRET_CHARS:
            raise CredentialStoreError(
                "The automatic-unlock credential is invalid."
            )
        return secret

    def write_recovery(self, recovery_passphrase: str) -> None:
        if not isinstance(recovery_passphrase, str) or not 1 <= len(
            recovery_passphrase
        ) <= _MAX_RECOVERY_SECRET_CHARS:
            raise CredentialStoreError("The automatic-unlock credential is invalid.")
        backend = self._approved_backend()
        try:
            backend.set_password(
                self.service_name,
                self.account,
                recovery_passphrase,
            )
            stored = backend.get_password(self.service_name, self.account)
        except KeyringError as error:
            raise CredentialStoreError(
                "The operating-system credential store is unavailable."
            ) from error
        if not isinstance(stored, str) or not hmac.compare_digest(
            stored,
            recovery_passphrase,
        ):
            try:
                backend.delete_password(self.service_name, self.account)
            except KeyringError:
                pass
            raise CredentialStoreError(
                "The automatic-unlock credential could not be verified."
            )

    def delete_recovery(self) -> None:
        backend = self._approved_backend()
        try:
            backend.delete_password(self.service_name, self.account)
        except PasswordDeleteError:
            return
        except KeyringError as error:
            raise CredentialStoreError(
                "The operating-system credential store is unavailable."
            ) from error

    def _approved_backend(self) -> KeyringBackend:
        backend = self.backend if self.backend is not None else keyring.get_keyring()
        if type(backend).__module__ not in _ALLOWED_BACKEND_MODULES:
            raise CredentialStoreError(
                "A protected operating-system credential backend is unavailable."
            )
        return backend


@dataclass(frozen=True)
class MacOSUserPresenceRecoveryCredentialStore:
    """Authenticate locally before this app reads its Keychain credential."""

    data_directory: Path
    account: str = "primary-memory-key"
    backend: KeyringBackend | None = None
    authenticator: MacOSUserAuthenticator | None = None

    def __post_init__(self) -> None:
        _validate_store_identity(self.data_directory, self.account)
        if self.authenticator is not None and not isinstance(
            self.authenticator,
            MacOSUserAuthenticator,
        ):
            raise TypeError("macOS credential storage requires an authenticator.")

    @property
    def service_name(self) -> str:
        return _service_name(self.data_directory)

    def read_recovery(self) -> str | None:
        self._authenticator().authenticate(_MACOS_UNLOCK_PROMPT)
        return self._store().read_recovery()

    def write_recovery(self, recovery_passphrase: str) -> None:
        self._store().write_recovery(recovery_passphrase)

    def delete_recovery(self) -> None:
        self._store().delete_recovery()

    def _store(self) -> SystemRecoveryCredentialStore:
        return SystemRecoveryCredentialStore(
            self.data_directory,
            account=self.account,
            backend=self.backend,
        )

    def _authenticator(self) -> MacOSUserAuthenticator:
        return (
            self.authenticator
            if self.authenticator is not None
            else _PyObjCMacOSUserAuthenticator()
        )


class _PyObjCMacOSUserAuthenticator:
    """Use Touch ID or the Mac login password through Local Authentication."""

    def authenticate(self, prompt: str) -> None:
        try:
            import LocalAuthentication  # type: ignore[import-not-found]
        except ImportError as error:
            raise CredentialStoreError(
                "macOS local authentication is unavailable."
            ) from error
        context = LocalAuthentication.LAContext.alloc().init()
        policy = LocalAuthentication.LAPolicyDeviceOwnerAuthentication
        available, _ = context.canEvaluatePolicy_error_(policy, None)
        if not available:
            raise CredentialStoreError(
                "Touch ID or Mac login authentication is unavailable."
            )
        completed = Event()
        approved = False

        def reply(success: bool, error: object) -> None:
            nonlocal approved
            approved = bool(success)
            completed.set()

        context.evaluatePolicy_localizedReason_reply_(policy, prompt, reply)
        if not completed.wait(_MACOS_AUTHENTICATION_TIMEOUT_SECONDS):
            context.invalidate()
            raise CredentialStoreError("macOS authentication timed out.")
        if not approved:
            raise CredentialStoreError("macOS authentication was not approved.")


def default_recovery_credential_store(
    data_directory: Path,
) -> RecoveryCredentialStore:
    """Choose the approved protected credential backend for this platform."""

    if sys.platform == "darwin":
        return MacOSUserPresenceRecoveryCredentialStore(data_directory)
    return SystemRecoveryCredentialStore(data_directory)


def _validate_store_identity(data_directory: Path, account: str) -> None:
    if not isinstance(data_directory, Path) or not data_directory.is_absolute():
        raise ValueError("Credential storage requires an explicit data directory.")
    if not isinstance(account, str) or not account:
        raise ValueError("Credential storage requires a stable account label.")


def _service_name(data_directory: Path) -> str:
    location = str(data_directory.resolve(strict=False)).encode("utf-8")
    location_id = sha256(location).hexdigest()[:24]
    return f"personal-assistant.memory-autounlock.{location_id}"
