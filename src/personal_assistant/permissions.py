"""Rules for deciding whether an assistant action is permitted."""

from dataclasses import dataclass
from enum import StrEnum


class ActionKind(StrEnum):
    """Actions the assistant may eventually request."""

    READ_PROJECT_FILE = "read_project_file"
    READ_PERSONAL_DATA = "read_personal_data"
    WRITE_LOCAL_FILE = "write_local_file"
    BROWSER_NAVIGATION = "browser_navigation"
    NETWORK_REQUEST = "network_request"
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


def evaluate_action(action: ActionKind) -> PermissionResult:
    """Return the safety decision for a requested action."""

    if action is ActionKind.READ_PROJECT_FILE:
        return PermissionResult(
            PermissionDecision.ALLOW,
            "Reading project source files is allowed.",
        )

    if action is ActionKind.ACCESS_CREDENTIALS:
        return PermissionResult(
            PermissionDecision.DENY,
            "Credentials must never be accessed automatically.",
        )

    if action in {
        ActionKind.READ_PERSONAL_DATA,
        ActionKind.WRITE_LOCAL_FILE,
        ActionKind.BROWSER_NAVIGATION,
        ActionKind.NETWORK_REQUEST,
    }:
        return PermissionResult(
            PermissionDecision.REQUIRE_APPROVAL,
            "This action requires explicit user approval.",
        )

    return PermissionResult(
        PermissionDecision.DENY,
        "Unknown actions are denied by default.",
    )
