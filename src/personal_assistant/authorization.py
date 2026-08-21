"""Enforce permission decisions before an action can be executed."""

from dataclasses import dataclass

from personal_assistant.permissions import (
    ActionKind,
    PermissionDecision,
    evaluate_action,
)


@dataclass(frozen=True)
class AuthorizationResult:
    """Whether an action may proceed and the reason for that outcome."""

    allowed: bool
    reason: str


def authorize_action(
    action: ActionKind,
    *,
    user_approved: bool = False,
) -> AuthorizationResult:
    """Allow an action only when policy and user approval permit it."""

    permission = evaluate_action(action)

    if permission.decision is PermissionDecision.ALLOW:
        return AuthorizationResult(True, permission.reason)

    if permission.decision is PermissionDecision.REQUIRE_APPROVAL:
        if user_approved:
            return AuthorizationResult(True, "User approved this action.")

        return AuthorizationResult(False, permission.reason)

    return AuthorizationResult(False, permission.reason)
