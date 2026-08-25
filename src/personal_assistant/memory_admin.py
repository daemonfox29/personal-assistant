"""Trusted local administration for memory setup, recovery, and restore."""

import argparse
import json
from getpass import getpass
from pathlib import Path
from uuid import UUID, uuid4

from personal_assistant.audit import AuditError
from personal_assistant.audit_file import AuditFileSettings, JsonLinesAuditSink
from personal_assistant.authorization import authorize_action
from personal_assistant.backup import BackupError
from personal_assistant.config import MemorySettings, load_settings
from personal_assistant.encrypted_database import EncryptedDatabaseError
from personal_assistant.memory_runtime import MemoryRuntime
from personal_assistant.memory_types import (
    ActorType,
    MentionPolicy,
    Provenance,
    PurgeReason,
    Sensitivity,
    SourceType,
    canonical_json,
    payload_from_data,
    payload_to_data,
)
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
    commands.add_parser("memories", help="list memory metadata without content")
    profile = commands.add_parser("profile", help="show records for an exact entity alias")
    profile.add_argument("alias")
    for name, help_text in (
        ("inspect", "show one memory"),
        ("history", "show one memory's revision history"),
        ("correct", "replace one memory payload from JSON"),
        ("archive", "archive one confirmed memory"),
        ("restore-record", "restore one archived or deleted memory"),
        ("delete", "soft-delete one memory"),
        ("purge", "permanently purge one memory"),
        ("controls", "change sensitivity and mention policy"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("record_id")
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
            if args.command == "profile":
                identifier = args.alias
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
    manifest_path = settings.data_directory / "security.json"
    database_path = settings.data_directory / "memory.db"
    manifest_preexisted = manifest_path.exists() or manifest_path.is_symlink()
    database_preexisted = database_path.exists() or database_path.is_symlink()
    database_sidecars = tuple(
        Path(f"{database_path}{suffix}") for suffix in ("-journal", "-wal", "-shm")
    )
    sidecars_preexisted = {
        path: path.exists() or path.is_symlink() for path in database_sidecars
    }
    setup_completed = False
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
        setup_completed = True
    finally:
        recovery = recovery_confirmation = passcode = passcode_confirmation = ""
        if not setup_completed:
            if not manifest_preexisted:
                _unlink_new_setup_file(manifest_path)
            if not database_preexisted:
                _unlink_new_setup_file(database_path)
            for path in database_sidecars:
                if not sidecars_preexisted[path]:
                    _unlink_new_setup_file(path)
    print("Encrypted memory setup and recovery verification succeeded.")


def _unlink_new_setup_file(path: Path) -> None:
    """Remove only a regular file created by this failed fresh setup."""

    try:
        if path.is_file() and not path.is_symlink():
            path.unlink()
    except OSError:
        pass


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
        if command == "memories":
            _show_memories(runtime)
            return
        if command == "profile":
            _show_profile(runtime, identifier)
            return
        if command in {"confirm", "reject"}:
            _review_candidate(runtime, command, identifier)
            return
        if command in {
            "inspect",
            "history",
            "correct",
            "archive",
            "restore-record",
            "delete",
            "purge",
            "controls",
        }:
            _manage_record(runtime, command, identifier)
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
        print(
            sanitize_terminal_text(
                f"{record.record_id} [{record.sensitivity.value}; "
                f"{record.mention_policy.value}; {record.kind.value}]"
            )
        )


def _show_memories(runtime: MemoryRuntime) -> None:
    records = runtime.repository.list_records(uuid4())
    if not records:
        print("No persistent memories found.")
        return
    for record in records:
        print(
            f"{record.record_id} [{record.status.value}; {record.kind.value}; "
            f"{record.sensitivity.value}; {record.mention_policy.value}]"
        )


def _show_profile(runtime: MemoryRuntime, alias: str | None) -> None:
    if alias is None:
        raise ValueError("Profile requires an exact entity alias.")
    correlation_id = uuid4()
    entities = runtime.repository.find_entities_by_alias(alias, correlation_id)
    arguments = {
        "alias": alias,
        "entity_ids": [str(entity.entity_id) for entity in entities],
    }
    _approve_exact(runtime, ActionKind.READ_PERSONAL_DATA, arguments, correlation_id)
    if not entities:
        print("No exact entity profile found.")
        return
    entity_ids = {entity.entity_id for entity in entities}
    records = tuple(
        record
        for record in runtime.repository.list_records(correlation_id)
        if record.primary_entity_id in entity_ids
    )
    if not records:
        print("The entity exists but has no linked memory records.")
        return
    for record in records:
        print(
            sanitize_terminal_text(
                f"{record.record_id} [{record.status.value}; "
                f"{record.sensitivity.value}] "
                f"{canonical_json(payload_to_data(record.revision.payload))}"
            )
        )


def _trusted_provenance(command: str) -> Provenance:
    return Provenance(SourceType.TRUSTED_INTERFACE, command, ActorType.USER)


def _approve_exact(
    runtime: MemoryRuntime,
    action: ActionKind,
    arguments: dict[str, object],
    correlation_id: UUID,
) -> None:
    passcode = getpass("High-risk passcode: ")
    try:
        grant = runtime.approval_gate.approve(
            action, arguments, passcode, correlation_id
        )
    finally:
        passcode = ""
    if not authorize_action(
        action,
        arguments=arguments,
        approval_receipt=grant.receipt,
        approval_authority=grant.authority,
    ).allowed:
        raise ValueError("High-risk memory action was not authorized.")


def _manage_record(
    runtime: MemoryRuntime,
    command: str,
    record_id_text: str | None,
) -> None:
    if record_id_text is None:
        raise ValueError("Memory record ID is required.")
    correlation_id = uuid4()
    record = runtime.repository.inspect_record(UUID(record_id_text), correlation_id)
    revealing = command in {"inspect", "history", "correct"}
    if command == "history" or (
        revealing
        and record.sensitivity in {Sensitivity.SENSITIVE, Sensitivity.RESTRICTED}
    ):
        _approve_exact(
            runtime,
            ActionKind.MEMORY_REVIEW_SENSITIVE,
            {
                "command": command,
                "record_id": str(record.record_id),
                "row_version": record.row_version,
                "sensitivity": record.sensitivity.value,
            },
            correlation_id,
        )
    if command == "inspect":
        print(sanitize_terminal_text(canonical_json(payload_to_data(record.revision.payload))))
        return
    if command == "history":
        for revision in runtime.repository.get_record_history(record.record_id, correlation_id):
            print(
                sanitize_terminal_text(
                    f"revision {revision.revision} [{revision.status.value}; "
                    f"{revision.reason.value}] {canonical_json(payload_to_data(revision.payload))}"
                )
            )
        return
    if command == "correct":
        raw_payload = input("Replacement payload as one JSON object: ")
        payload = payload_from_data(json.loads(raw_payload))
        if input("Type CORRECT to continue: ") != "CORRECT":
            print("Correction cancelled; no memory was changed.")
            return
        runtime.repository.revise_record(
            record.record_id,
            record.row_version,
            payload,
            _trusted_provenance("record-correct"),
            correlation_id,
        )
        print("Memory corrected; prior content remains in revision history.")
        return
    if command == "controls":
        sensitivity = Sensitivity(input("Sensitivity: ").strip())
        mention_policy = MentionPolicy(input("Mention policy: ").strip())
        arguments = {
            "record_id": str(record.record_id),
            "row_version": record.row_version,
            "sensitivity": sensitivity.value,
            "mention_policy": mention_policy.value,
        }
        _approve_exact(
            runtime,
            ActionKind.MEMORY_CHANGE_PRIVACY,
            arguments,
            correlation_id,
        )
        runtime.repository.update_record_controls(
            record.record_id,
            record.row_version,
            sensitivity=sensitivity,
            mention_policy=mention_policy,
            scope=record.scope,
            provenance=_trusted_provenance("record-controls"),
            correlation_id=correlation_id,
        )
        print("Memory privacy controls updated and revisioned.")
        return
    expected = command.upper()
    if input(f"Type {expected} to continue: ") != expected:
        print("Memory change cancelled; no memory was changed.")
        return
    if command == "purge":
        arguments = {
            "record_id": str(record.record_id),
            "row_version": record.row_version,
        }
        _approve_exact(runtime, ActionKind.MEMORY_PURGE, arguments, correlation_id)
        runtime.repository.purge_record(
            record.record_id,
            record.row_version,
            PurgeReason.USER_REQUESTED,
            correlation_id,
        )
        print("Memory permanently purged; its suppression ledger entry remains.")
        return
    operation = {
        "archive": runtime.repository.archive_record,
        "restore-record": runtime.repository.restore_record,
        "delete": runtime.repository.delete_record,
    }[command]
    operation(
        record.record_id,
        record.row_version,
        _trusted_provenance(f"record-{command}"),
        correlation_id,
    )
    print("Memory lifecycle updated and revisioned.")


def _review_candidate(
    runtime: MemoryRuntime,
    command: str,
    record_id_text: str | None,
) -> None:
    if record_id_text is None:
        raise ValueError("Candidate record ID is required.")
    record_id = UUID(record_id_text)
    passcode = None
    correlation_id = uuid4()
    record = runtime.repository.inspect_record(record_id, correlation_id)
    if record.sensitivity.value in {"sensitive", "restricted"}:
        passcode = getpass("High-risk passcode: ")
    try:
        if passcode is not None:
            arguments = {
                "decision": command,
                "record_id": str(record.record_id),
                "row_version": record.row_version,
                "sensitivity": record.sensitivity.value,
            }
            grant = runtime.approval_gate.approve(
                ActionKind.MEMORY_REVIEW_SENSITIVE,
                arguments,
                passcode,
                correlation_id,
            )
            if not authorize_action(
                ActionKind.MEMORY_REVIEW_SENSITIVE,
                arguments=arguments,
                approval_receipt=grant.receipt,
                approval_authority=grant.authority,
            ).allowed:
                raise ValueError("Sensitive candidate review was not authorized.")
        payload = canonical_json(payload_to_data(record.revision.payload))
        print(sanitize_terminal_text(f"Candidate: {payload}"))
        expected = command.upper()
        if input(f"Type {expected} to continue: ") != expected:
            print("Candidate review cancelled; no memory was changed.")
            return
        if command == "reject":
            runtime.reject_candidate(record_id, correlation_id)
            print("Candidate rejected and retained only in revision history.")
            return
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
