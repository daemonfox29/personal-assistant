"""Checks for short-lived, redacted database key material."""

import unittest

from personal_assistant.key_provider import (
    DATABASE_KEY_BYTES,
    DatabaseKey,
    DatabaseKeyUnavailableError,
)


class DatabaseKeyTests(unittest.TestCase):
    def test_key_requires_exactly_256_bits(self) -> None:
        for invalid in (
            b"short",
            b"\x00" * DATABASE_KEY_BYTES,
            b"x" * (DATABASE_KEY_BYTES + 1),
            "not bytes",
        ):
            with self.subTest(invalid=type(invalid).__name__):
                with self.assertRaises(DatabaseKeyUnavailableError):
                    DatabaseKey(invalid)  # type: ignore[arg-type]

    def test_display_is_redacted_and_mutable_copy_can_be_cleared(self) -> None:
        raw_key = bytes(range(DATABASE_KEY_BYTES))
        key = DatabaseKey(raw_key)

        self.assertNotIn(raw_key.hex(), repr(key))
        self.assertFalse(key.is_cleared)

        key.clear()

        self.assertTrue(key.is_cleared)
        with self.assertRaises(DatabaseKeyUnavailableError):
            key._sqlcipher_hex()
