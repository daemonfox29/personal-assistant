"""Operating-system credential storage for optional automatic memory unlock."""

from dataclasses import dataclass
from hashlib import sha256
import hmac
from pathlib import Path
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
        location = str(self.data_directory.resolve(strict=False)).encode("utf-8")
        location_id = sha256(location).hexdigest()[:24]
        return f"personal-assistant.memory-autounlock.{location_id}"

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
