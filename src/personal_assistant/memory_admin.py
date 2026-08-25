"""Trusted local administration for memory setup, recovery, and restore."""

import argparse
from getpass import getpass
from pathlib import Path
from uuid import UUID, uuid4

from personal_assistant.audit import AuditError
from personal_assistant.audit_file import AuditFileSettings, JsonLinesAuditSink
from personal_assistant.backup import BackupError
from personal_assistant.config import MemorySettings, load_settings
from personal_assistant.encrypted_database import EncryptedDatabaseError
from personal_assistant.memory_runtime import MemoryRuntime
from personal_assistant.memory_types import canonical_json, payload_to_data
from personal_assistant.migration import MigrationError
from personal_assistant.permissions import ActionKind
from personal_assistant.portable_security import (
    PortableSecurityError,
    PortableSecurityManager,
    PortableSecuritySettings,
)
from personal_assistant.terminal_output import sanitize_terminal_text


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Trusted local persistent-memory administration."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("setup", help="create portable recovery configuration")
    commands.add_parser("verify-recovery", help="verify recovery and database access")
    commands.add_parser("backup", help="create one verified encrypted backup")
    commands.add_parser("list-backups", help="list managed encrypted snapshots")
    commands.add_parser("candidates", help="show quarantined memory suggestions")
    confirm = commands.add_parser("confirm", help="confirm one candidate")
    confirm.add_argument("record_id")
    reject = commands.add_parser("reject", help="reject one candidate")
    reject.add_argument("record_id")
    restore = commands.add_parser("restore", help="restore one managed snapshot")
    restore.add_argument("snapshot_name")
    return parser


def main(argv: list[str] | None = None) -> None:
    """Run a trusted command without sending secrets or arguments to the model."""

    args = _parser().parse_args(argv)
    try:
        settings = load_settings().memory
        if not settings.enabled:
            raise ValueError("Persistent memory is disabled.")
        if args.command == "setup":
            _setup(settings)
        else:
            identifier = getattr(args, "snapshot_name", None) or getattr(
                args, "record_id", None
            )
            _run_configured(settings, args.command, identifier)
    except (ValueError, PortableSecurityError, EncryptedDatabaseError, MigrationError):
        print("Memory administration failed safely; no requested change was completed.")
    except (AuditError, BackupError):
        print("Memory administration was blocked safely; check configuration and logs.")


def _audit_sink(settings: MemorySettings) -> JsonLinesAuditSink:
    return JsonLinesAuditSink(
        AuditFileSettings(settings.data_directory / "audit.jsonl")
    )


def _setup(settings: MemorySettings) -> None:
    sink = _audit_sink(settings)
    security = PortableSecurityManager(
        PortableSecuritySettings(settings.data_directory / "security.json"),
        audit_sink=sink,
    )
    print(
        "Create a portable recovery passphrase (12+ characters) and a different "
        "high-risk passcode (8+ characters). Neither is stored. Losing the "
        "recovery passphrase makes encrypted memory unrecoverable."
    )
    recovery = getpass("Recovery passphrase: ")
    recovery_confirmation = getpass("Repeat recovery passphrase: ")
    passcode = getpass("High-risk passcode: ")
    passcode_confirmation = getpass("Repeat high-risk passcode: ")
    try:
        security.setup(
            recovery,
            recovery_confirmation,
            passcode,
            passcode_confirmation,
            uuid4(),
        )
        runtime = MemoryRuntime.open(settings, recovery, audit_sink=sink)
        runtime.close()
    finally:
        recovery = recovery_confirmation = passcode = passcode_confirmation = ""
    print("Encrypted memory setup and recovery verification succeeded.")


def _run_configured(
    settings: MemorySettings,
    command: str,
    identifier: str | None,
) -> None:
    recovery = getpass("Recovery passphrase: ")
    try:
        runtime = MemoryRuntime.open(
            settings,
            recovery,
            audit_sink=_audit_sink(settings),
        )
    finally:
        recovery = ""
    try:
        if command == "verify-recovery":
            print("Recovery verification and encrypted database integrity succeeded.")
            return
        if command == "candidates":
            _show_candidates(runtime)
            return
        if command in {"confirm", "reject"}:
            _review_candidate(runtime, command, identifier)
            return
        if runtime.backup_manager is None:
            raise ValueError("A backup destination is not configured.")
        if command == "backup":
            snapshot = runtime.backup_manager.create_snapshot(uuid4())
            print(f"Verified encrypted backup created: {snapshot.path.name}")
            return
        if command == "list-backups":
            snapshots = runtime.backup_manager.list_snapshots()
            if not snapshots:
                print("No managed encrypted backups found.")
            for snapshot in snapshots:
                print(snapshot.name)
            return
        if command == "restore":
            _restore(runtime, identifier)
            return
        raise ValueError("Unknown memory administration command.")
    finally:
        runtime.close()


def _restore(runtime: MemoryRuntime, snapshot_name: str | None) -> None:
    if snapshot_name is None or Path(snapshot_name).name != snapshot_name:
        raise ValueError("Restore requires one managed snapshot filename.")
    assert runtime.settings.backup_directory is not None
    assert runtime.backup_manager is not None
    path = runtime.settings.backup_directory / snapshot_name
    correlation_id = uuid4()
    plan = runtime.backup_manager.plan_restore(path, correlation_id)
    print("High-risk restore impact:")
    print(f"- snapshot: {plan.snapshot.path.name}")
    print(f"- encrypted bytes: {plan.snapshot.byte_count}")
    print(f"- ciphertext SHA-256: {plan.snapshot.ciphertext_sha256}")
    print("- creates a pre-restore snapshot")
    print("- reapplies the permanent deletion ledger")
    print("- atomically replaces the live memory database")
    confirmation = input("Type RESTORE to continue: ")
    if confirmation != "RESTORE":
        print("Restore cancelled; no database was replaced.")
        return
    passcode = getpass("High-risk passcode: ")
    try:
        grant = runtime.approval_gate.approve(
            ActionKind.MEMORY_BACKUP_RESTORE,
            plan.approval_arguments,
            passcode,
            correlation_id,
        )
    finally:
        passcode = ""
    runtime.backup_manager.restore(
        plan,
        correlation_id,
        approval_receipt=grant.receipt,
        approval_authority=grant.authority,
    )
    print("Encrypted memory restore completed and verified.")


def _show_candidates(runtime: MemoryRuntime) -> None:
    candidates = runtime.repository.list_candidates(uuid4())
    if not candidates:
        print("No quarantined memory suggestions await review.")
        return
    for record in candidates:
        payload = canonical_json(payload_to_data(record.revision.payload))
        print(
            sanitize_terminal_text(
                f"{record.record_id} [{record.sensitivity.value}; "
                f"{record.mention_policy.value}] {payload}"
            )
        )


def _review_candidate(
    runtime: MemoryRuntime,
    command: str,
    record_id_text: str | None,
) -> None:
    if record_id_text is None:
        raise ValueError("Candidate record ID is required.")
    record_id = UUID(record_id_text)
    record = runtime.repository.inspect_record(record_id, uuid4())
    payload = canonical_json(payload_to_data(record.revision.payload))
    print(sanitize_terminal_text(f"Candidate: {payload}"))
    expected = command.upper()
    if input(f"Type {expected} to continue: ") != expected:
        print("Candidate review cancelled; no memory was changed.")
        return
    correlation_id = uuid4()
    if command == "reject":
        runtime.reject_candidate(record_id, correlation_id)
        print("Candidate rejected and retained only in revision history.")
        return
    passcode = None
    if record.sensitivity.value in {"sensitive", "restricted"}:
        passcode = getpass("High-risk passcode: ")
    try:
        runtime.confirm_candidate(
            record_id,
            correlation_id,
            high_risk_passcode=passcode,
        )
    finally:
        passcode = ""
    print("Candidate confirmed as persistent memory.")


if __name__ == "__main__":
    main()
