"""Checks for permission enforcement before actions are executed."""

import unittest

from personal_assistant.authorization import authorize_action
from personal_assistant.permissions import ActionKind


class AuthorizationTests(unittest.TestCase):
    """Verify that policy decisions become enforceable allow/deny outcomes."""

    def test_allowed_action_does_not_need_approval(self) -> None:
        result = authorize_action(ActionKind.READ_PROJECT_FILE)

        self.assertTrue(result.allowed)

    def test_sensitive_action_is_blocked_without_approval(self) -> None:
        result = authorize_action(ActionKind.BROWSER_NAVIGATION)

        self.assertFalse(result.allowed)

    def test_sensitive_action_is_allowed_after_approval(self) -> None:
        result = authorize_action(
            ActionKind.BROWSER_NAVIGATION,
            user_approved=True,
        )

        self.assertTrue(result.allowed)

    def test_denied_action_stays_blocked_after_approval(self) -> None:
        result = authorize_action(
            ActionKind.ACCESS_CREDENTIALS,
            user_approved=True,
        )

        self.assertFalse(result.allowed)
