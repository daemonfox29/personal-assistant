"""Synthetic checks for protected automatic-unlock credential storage."""

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError

from personal_assistant.credential_store import (
    CredentialStoreError,
    MacOSUserPresenceRecoveryCredentialStore,
    SystemRecoveryCredentialStore,
    _PyObjCMacOSUserAuthenticator,
    default_recovery_credential_store,
)


class SyntheticBackend(KeyringBackend):
    priority = 1

    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}
        self.reads = 0

    def get_password(self, service: str, username: str) -> str | None:
        self.reads += 1
        return self.values.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.values[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        try:
            del self.values[(service, username)]
        except KeyError as error:
            raise PasswordDeleteError("not found") from error


class SyntheticMacOSAuthenticator:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def authenticate(self, prompt: str) -> None:
        self.prompts.append(prompt)


class DenyingMacOSAuthenticator:
    def authenticate(self, prompt: str) -> None:
        raise CredentialStoreError("synthetic authentication denial")


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

    def test_macos_store_authenticates_before_reading_keychain(self) -> None:
        backend = SyntheticBackend()
        authenticator = SyntheticMacOSAuthenticator()
        store = MacOSUserPresenceRecoveryCredentialStore(
            Path("/synthetic"),
            backend=backend,
            authenticator=authenticator,
        )
        with patch(
            "personal_assistant.credential_store._ALLOWED_BACKEND_MODULES",
            frozenset({type(backend).__module__}),
        ):
            store.write_recovery("synthetic recovery passphrase")
            recovered = store.read_recovery()

        self.assertEqual(recovered, "synthetic recovery passphrase")
        self.assertEqual(len(authenticator.prompts), 1)
        self.assertIn("Unlock encrypted", authenticator.prompts[0])

    def test_platform_factory_selects_user_presence_store_on_macos(self) -> None:
        with patch("personal_assistant.credential_store.sys.platform", "darwin"):
            store = default_recovery_credential_store(Path("/synthetic"))

        self.assertIsInstance(store, MacOSUserPresenceRecoveryCredentialStore)

    def test_macos_authentication_denial_prevents_keychain_read(self) -> None:
        backend = SyntheticBackend()
        store = MacOSUserPresenceRecoveryCredentialStore(
            Path("/synthetic"),
            backend=backend,
            authenticator=DenyingMacOSAuthenticator(),
        )

        with self.assertRaises(CredentialStoreError):
            store.read_recovery()

        self.assertEqual(backend.reads, 0)

    def test_pyobjc_authenticator_requests_device_owner_authentication(self) -> None:
        captured: dict[str, object] = {}

        class Context:
            @classmethod
            def alloc(cls) -> "Context":
                return cls()

            def init(self) -> "Context":
                return self

            def canEvaluatePolicy_error_(
                self,
                policy: int,
                error: object,
            ) -> tuple[bool, None]:
                captured["availability_policy"] = policy
                return True, None

            def evaluatePolicy_localizedReason_reply_(
                self,
                policy: int,
                prompt: str,
                reply: object,
            ) -> None:
                captured["evaluation"] = (policy, prompt)
                reply(True, None)

            def invalidate(self) -> None:
                captured["invalidated"] = True

        module = SimpleNamespace(
            LAContext=Context,
            LAPolicyDeviceOwnerAuthentication=2,
        )
        authenticator = _PyObjCMacOSUserAuthenticator()

        with patch.dict(sys.modules, {"LocalAuthentication": module}):
            authenticator.authenticate("synthetic prompt")

        self.assertEqual(captured["availability_policy"], 2)
        self.assertEqual(captured["evaluation"], (2, "synthetic prompt"))


if __name__ == "__main__":
    unittest.main()
