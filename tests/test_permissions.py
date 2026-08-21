"""Checks for the assistant's permission policy."""

import unittest

from personal_assistant.permissions import (
    ActionKind,
    PermissionDecision,
    evaluate_action,
)


class PermissionPolicyTests(unittest.TestCase):
    """Verify that sensitive actions remain protected."""

    def test_project_file_reading_is_allowed(self) -> None:
        result = evaluate_action(ActionKind.READ_PROJECT_FILE)

        self.assertIs(result.decision, PermissionDecision.ALLOW)

    def test_credential_access_is_denied(self) -> None:
        result = evaluate_action(ActionKind.ACCESS_CREDENTIALS)

        self.assertIs(result.decision, PermissionDecision.DENY)

    def test_sensitive_actions_require_approval(self) -> None:
        sensitive_actions = {
            ActionKind.READ_PERSONAL_DATA,
            ActionKind.WRITE_LOCAL_FILE,
            ActionKind.BROWSER_NAVIGATION,
            ActionKind.NETWORK_REQUEST,
        }

        for action in sensitive_actions:
            with self.subTest(action=action):
                result = evaluate_action(action)

                self.assertIs(
                    result.decision,
                    PermissionDecision.REQUIRE_APPROVAL,
                )
