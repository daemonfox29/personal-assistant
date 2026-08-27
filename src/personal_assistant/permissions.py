"""Rules for deciding whether an assistant action is permitted."""

from dataclasses import dataclass
from enum import StrEnum


class ActionKind(StrEnum):
    """Actions the assistant may eventually request."""

    READ_PROJECT_FILE = "read_project_file"
    READ_SYSTEM_TIME = "read_system_time"
    CALCULATE = "calculate"
    READ_PERSONAL_DATA = "read_personal_data"
    WRITE_LOCAL_FILE = "write_local_file"
    BROWSER_NAVIGATION = "browser_navigation"
    NETWORK_REQUEST = "network_request"
    MEMORY_BACKUP_RESTORE = "memory_backup_restore"
    MEMORY_REVIEW_SENSITIVE = "memory_review_sensitive"
    MEMORY_CONFIRM_SENSITIVE = "memory_confirm_sensitive"
    MEMORY_PURGE = "memory_purge"
    MEMORY_CHANGE_PRIVACY = "memory_change_privacy"
    ACCESS_CREDENTIALS = "access_credentials"


class PermissionDecision(StrEnum):
    """Possible outcomes from the permission layer."""

    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


@dataclass(frozen=True)
class PermissionResult:
    """The decision and the human-readable reason for it."""

    decision: PermissionDecision
    reason: str


POLICY_BY_ACTION: dict[ActionKind, PermissionResult] = {
    ActionKind.READ_PROJECT_FILE: PermissionResult(
        PermissionDecision.ALLOW,
        "Reading project source files is allowed.",
    ),
    ActionKind.READ_SYSTEM_TIME: PermissionResult(
        PermissionDecision.ALLOW,
        "Reading the local system time is allowed.",
    ),
    ActionKind.CALCULATE: PermissionResult(
        PermissionDecision.ALLOW,
        "Bounded deterministic arithmetic is allowed.",
    ),
    ActionKind.READ_PERSONAL_DATA: PermissionResult(
        PermissionDecision.REQUIRE_APPROVAL,
        "This action requires explicit user approval.",
    ),
    ActionKind.WRITE_LOCAL_FILE: PermissionResult(
        PermissionDecision.REQUIRE_APPROVAL,
        "This action requires explicit user approval.",
    ),
    ActionKind.BROWSER_NAVIGATION: PermissionResult(
        PermissionDecision.REQUIRE_APPROVAL,
        "This action requires explicit user approval.",
    ),
    ActionKind.NETWORK_REQUEST: PermissionResult(
        PermissionDecision.REQUIRE_APPROVAL,
        "This action requires explicit user approval.",
    ),
    ActionKind.MEMORY_BACKUP_RESTORE: PermissionResult(
        PermissionDecision.REQUIRE_APPROVAL,
        "Restoring memory requires exact passcode-backed approval.",
    ),
    ActionKind.MEMORY_REVIEW_SENSITIVE: PermissionResult(
        PermissionDecision.REQUIRE_APPROVAL,
        "Viewing sensitive memory requires exact passcode-backed approval.",
    ),
    ActionKind.MEMORY_CONFIRM_SENSITIVE: PermissionResult(
        PermissionDecision.REQUIRE_APPROVAL,
        "Confirming sensitive memory requires exact passcode-backed approval.",
    ),
    ActionKind.MEMORY_PURGE: PermissionResult(
        PermissionDecision.REQUIRE_APPROVAL,
        "Permanent memory deletion requires exact passcode-backed approval.",
    ),
    ActionKind.MEMORY_CHANGE_PRIVACY: PermissionResult(
        PermissionDecision.REQUIRE_APPROVAL,
        "Changing memory privacy controls requires exact passcode-backed approval.",
    ),
    ActionKind.ACCESS_CREDENTIALS: PermissionResult(
        PermissionDecision.DENY,
        "Credentials must never be accessed automatically.",
    ),
}

DEFAULT_DENY = PermissionResult(
    PermissionDecision.DENY,
    "Unknown actions are denied by default.",
)


def evaluate_action(action: ActionKind) -> PermissionResult:
    """Return the safety decision for a requested action."""

    return POLICY_BY_ACTION.get(action, DEFAULT_DENY)
