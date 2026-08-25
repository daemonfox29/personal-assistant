"""Synthetic checks for portable recovery and trusted passcode approval."""

import json
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from personal_assistant.audit import AuditOutcome, InMemoryAuditSink
from personal_assistant.authorization import authorize_action
from personal_assistant.key_provider import DatabaseKeyUnavailableError
from personal_assistant.permissions import ActionKind
from personal_assistant.portable_security import (
    PasscodeApprovalGate,
    PasscodeVerificationError,
    PortableSecurityManager,
    PortableSecuritySettings,
    RecoveryUnlockError,
    SecuritySetupError,
)


RECOVERY = "synthetic recovery phrase 2026"
PASSCODE = "synthetic-approval-2468"


class PortableSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.manifest = self.root / "private" / "security.json"
        self.audit = InMemoryAuditSink()
        self.manager = PortableSecurityManager(
            PortableSecuritySettings(self.manifest),
            audit_sink=self.audit,
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _setup(self) -> None:
        self.manager.setup(
            RECOVERY,
            RECOVERY,
            PASSCODE,
            PASSCODE,
            uuid4(),
        )

    def test_setup_writes_only_salted_checks_with_restrictive_permissions(self) -> None:
        self._setup()

        document = json.loads(self.manifest.read_text(encoding="utf-8"))
        serialized = json.dumps(document)
        self.assertNotIn(RECOVERY, serialized)
        self.assertNotIn(PASSCODE, serialized)
        self.assertEqual(document["version"], 1)
        self.assertEqual(document["key_id"], "primary-memory-key")
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(self.manifest.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(self.manifest.parent.stat().st_mode), 0o700)

    def test_recovery_unlock_is_stable_and_wrong_phrase_fails(self) -> None:
        self._setup()
        first = self.manager.unlock(RECOVERY, uuid4())
        second = self.manager.unlock(RECOVERY, uuid4())

        first_key = first.acquire("primary-memory-key")
        second_key = second.acquire("primary-memory-key")
        self.assertEqual(first_key._sqlcipher_hex(), second_key._sqlcipher_hex())
        first_key.clear()
        second_key.clear()
        first.close()
        with self.assertRaises(DatabaseKeyUnavailableError):
            first.acquire("primary-memory-key")
        second.close()
        with self.assertRaises(RecoveryUnlockError):
            self.manager.unlock("incorrect synthetic phrase", uuid4())

    def test_setup_requires_confirmations_and_never_overwrites(self) -> None:
        with self.assertRaises(SecuritySetupError):
            self.manager.setup(
                RECOVERY,
                "different recovery confirmation",
                PASSCODE,
                PASSCODE,
                uuid4(),
            )
        self.assertFalse(self.manifest.exists())

        self._setup()
        original = self.manifest.read_bytes()
        with self.assertRaises(SecuritySetupError):
            self._setup()
        self.assertEqual(self.manifest.read_bytes(), original)

    @unittest.skipUnless(hasattr(os, "symlink"), "symbolic links unavailable")
    def test_manifest_symbolic_link_is_rejected(self) -> None:
        target = self.root / "target.json"
        target.write_text("{}", encoding="utf-8")
        self.manifest.parent.mkdir()
        self.manifest.symlink_to(target)

        with self.assertRaises(SecuritySetupError):
            _ = self.manager.is_configured
        with self.assertRaises(SecuritySetupError):
            self.manager.unlock(RECOVERY, uuid4())

    def test_passcode_mints_exact_one_use_receipt_and_audits_no_secret(self) -> None:
        self._setup()
        gate = PasscodeApprovalGate(self.manager, audit_sink=self.audit)
        arguments = {"snapshot_name": "synthetic.db"}
        grant = gate.approve(
            ActionKind.MEMORY_BACKUP_RESTORE,
            arguments,
            PASSCODE,
            uuid4(),
        )

        first = authorize_action(
            ActionKind.MEMORY_BACKUP_RESTORE,
            arguments=arguments,
            approval_receipt=grant.receipt,
            approval_authority=grant.authority,
        )
        replay = authorize_action(
            ActionKind.MEMORY_BACKUP_RESTORE,
            arguments=arguments,
            approval_receipt=grant.receipt,
            approval_authority=grant.authority,
        )
        self.assertTrue(first.allowed)
        self.assertFalse(replay.allowed)
        self.assertNotIn(PASSCODE, repr(self.audit.events))
        self.assertEqual(self.audit.events[-1].outcome, AuditOutcome.SUCCEEDED)

    def test_receipt_expiry_uses_monotonic_clock_not_wall_clock(self) -> None:
        self._setup()
        wall = [100.0]
        monotonic = [10.0]
        gate = PasscodeApprovalGate(
            self.manager,
            audit_sink=self.audit,
            clock=lambda: wall[0],
            receipt_clock=lambda: monotonic[0],
        )
        arguments = {"snapshot_name": "synthetic.db"}
        grant = gate.approve(
            ActionKind.MEMORY_BACKUP_RESTORE,
            arguments,
            PASSCODE,
            uuid4(),
        )
        wall[0] = -10_000.0
        monotonic[0] = 11.0

        self.assertTrue(
            authorize_action(
                ActionKind.MEMORY_BACKUP_RESTORE,
                arguments=arguments,
                approval_receipt=grant.receipt,
                approval_authority=grant.authority,
            ).allowed
        )

    def test_existing_process_lock_blocks_parallel_passcode_check(self) -> None:
        self._setup()
        state_path = self.manifest.parent / "approval-rate-limit.json"
        lock_path = state_path.with_name(f".{state_path.name}.lock")
        lock_path.write_text("locked\n", encoding="utf-8")
        gate = PasscodeApprovalGate(
            self.manager,
            audit_sink=self.audit,
            state_path=state_path,
        )

        with self.assertRaisesRegex(PasscodeVerificationError, "already in progress"):
            gate.approve(
                ActionKind.MEMORY_BACKUP_RESTORE,
                {"snapshot_name": "synthetic.db"},
                PASSCODE,
                uuid4(),
            )

    def test_passcode_failures_are_rate_limited(self) -> None:
        self._setup()
        now = 100.0
        gate = PasscodeApprovalGate(
            self.manager,
            audit_sink=self.audit,
            clock=lambda: now,
            max_failed_attempts=2,
            lockout_seconds=60,
        )
        arguments = {"snapshot_name": "synthetic.db"}
        for _ in range(2):
            with self.assertRaises(PasscodeVerificationError):
                gate.approve(
                    ActionKind.MEMORY_BACKUP_RESTORE,
                    arguments,
                    "incorrect-passcode",
                    uuid4(),
                )

        with self.assertRaisesRegex(PasscodeVerificationError, "temporarily locked"):
            gate.approve(
                ActionKind.MEMORY_BACKUP_RESTORE,
                arguments,
                PASSCODE,
                uuid4(),
            )

    def test_passcode_lockout_survives_gate_restart(self) -> None:
        self._setup()
        state_path = self.manifest.parent / "approval-rate-limit.json"
        now = [100.0]
        arguments = {"snapshot_name": "synthetic.db"}
        first_gate = PasscodeApprovalGate(
            self.manager,
            audit_sink=self.audit,
            clock=lambda: now[0],
            max_failed_attempts=2,
            lockout_seconds=60,
            state_path=state_path,
        )
        for _ in range(2):
            with self.assertRaises(PasscodeVerificationError):
                first_gate.approve(
                    ActionKind.MEMORY_BACKUP_RESTORE,
                    arguments,
                    "incorrect-passcode",
                    uuid4(),
                )

        restarted_gate = PasscodeApprovalGate(
            self.manager,
            audit_sink=self.audit,
            clock=lambda: now[0],
            max_failed_attempts=2,
            lockout_seconds=60,
            state_path=state_path,
        )
        with self.assertRaisesRegex(PasscodeVerificationError, "temporarily locked"):
            restarted_gate.approve(
                ActionKind.MEMORY_BACKUP_RESTORE,
                arguments,
                PASSCODE,
                uuid4(),
            )

        now[0] = 161.0
        grant = restarted_gate.approve(
            ActionKind.MEMORY_BACKUP_RESTORE,
            arguments,
            PASSCODE,
            uuid4(),
        )
        self.assertIsNotNone(grant.receipt)
        document = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(document["failed_attempts"], 0)
        self.assertEqual(document["locked_until"], 0.0)
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(state_path.stat().st_mode), 0o600)

    @unittest.skipUnless(hasattr(os, "symlink"), "symbolic links unavailable")
    def test_unsafe_rate_limit_state_blocks_approval_and_is_audited(self) -> None:
        self._setup()
        state_path = self.manifest.parent / "approval-rate-limit.json"
        gate = PasscodeApprovalGate(
            self.manager,
            audit_sink=self.audit,
            state_path=state_path,
        )
        target = self.root / "untrusted-state.json"
        target.write_text("{}", encoding="utf-8")
        state_path.symlink_to(target)

        with self.assertRaisesRegex(
            PasscodeVerificationError,
            "state is unavailable",
        ):
            gate.approve(
                ActionKind.MEMORY_BACKUP_RESTORE,
                {"snapshot_name": "synthetic.db"},
                PASSCODE,
                uuid4(),
            )

        self.assertEqual(self.audit.events[-1].outcome, AuditOutcome.FAILED)
        self.assertEqual(target.read_text(encoding="utf-8"), "{}")

    def test_passcode_cannot_override_permanent_denial(self) -> None:
        self._setup()
        gate = PasscodeApprovalGate(self.manager, audit_sink=self.audit)

        with self.assertRaises(PasscodeVerificationError):
            gate.approve(ActionKind.ACCESS_CREDENTIALS, {}, PASSCODE, uuid4())


if __name__ == "__main__":
    unittest.main()
