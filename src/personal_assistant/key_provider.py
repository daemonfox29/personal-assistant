"""Replaceable key-material boundary for encrypted local databases."""

from typing import Protocol, runtime_checkable


DATABASE_KEY_BYTES = 32


class DatabaseKeyError(RuntimeError):
    """A safe expected failure while acquiring database key material."""


class DatabaseKeyUnavailableError(DatabaseKeyError):
    """The configured provider could not supply a valid database key."""


class DatabaseKey:
    """Short-lived mutable key material with redacted display behavior."""

    __slots__ = ("_value",)

    def __init__(self, value: bytes | bytearray) -> None:
        if not isinstance(value, (bytes, bytearray)):
            raise DatabaseKeyUnavailableError("Database key material is invalid.")
        if len(value) != DATABASE_KEY_BYTES:
            raise DatabaseKeyUnavailableError("Database key material is invalid.")
        if not any(value):
            raise DatabaseKeyUnavailableError("Database key material is invalid.")
        self._value = bytearray(value)

    def _sqlcipher_hex(self) -> str:
        if self.is_cleared:
            raise DatabaseKeyUnavailableError("Database key material is unavailable.")
        return self._value.hex()

    def clear(self) -> None:
        """Best-effort overwrite of this mutable application-owned copy."""

        for index in range(len(self._value)):
            self._value[index] = 0

    @property
    def is_cleared(self) -> bool:
        return not any(self._value)

    def __repr__(self) -> str:
        return "DatabaseKey(<redacted>)"

    __str__ = __repr__


@runtime_checkable
class DatabaseKeyProvider(Protocol):
    """Provide a fresh short-lived key object for one configured key ID."""

    def acquire(self, key_id: str) -> DatabaseKey:
        """Return fresh key material or raise a safe key-provider error."""
