"""Synthetic checks for protected automatic-unlock credential storage."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError

from personal_assistant.credential_store import (
    CredentialStoreError,
    SystemRecoveryCredentialStore,
)


class SyntheticBackend(KeyringBackend):
    priority = 1

    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.values.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.values[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        try:
            del self.values[(service, username)]
        except KeyError as error:
            raise PasswordDeleteError("not found") from error


class CredentialStoreTests(unittest.TestCase):
    def test_secret_round_trip_uses_location_specific_service(self) -> None:
        backend = SyntheticBackend()
        with TemporaryDirectory() as temporary_directory, patch(
            "personal_assistant.credential_store._ALLOWED_BACKEND_MODULES",
            frozenset({type(backend).__module__}),
        ):
            first = SystemRecoveryCredentialStore(
                Path(temporary_directory) / "first",
                backend=backend,
            )
            second = SystemRecoveryCredentialStore(
                Path(temporary_directory) / "second",
                backend=backend,
            )

            first.write_recovery("synthetic recovery passphrase")

            self.assertEqual(
                first.read_recovery(),
                "synthetic recovery passphrase",
            )
            self.assertIsNone(second.read_recovery())
            self.assertNotEqual(first.service_name, second.service_name)
            first.delete_recovery()
            self.assertIsNone(first.read_recovery())

    def test_unapproved_or_unverifiable_backend_fails_closed(self) -> None:
        backend = SyntheticBackend()
        store = SystemRecoveryCredentialStore(Path("/synthetic"), backend=backend)

        with self.assertRaises(CredentialStoreError):
            store.read_recovery()

        with patch(
            "personal_assistant.credential_store._ALLOWED_BACKEND_MODULES",
            frozenset({type(backend).__module__}),
        ), patch.object(backend, "get_password", return_value="different"):
            with self.assertRaises(CredentialStoreError):
                store.write_recovery("synthetic recovery passphrase")


if __name__ == "__main__":
    unittest.main()
