"""Checks for permission enforcement before actions are executed."""

import unittest

from personal_assistant.authorization import (
    ApprovalAuthority,
    ApprovalReceipt,
    MAX_APPROVAL_LIFETIME_SECONDS,
    authorize_action,
)
from personal_assistant.permissions import ActionKind


class AuthorizationTests(unittest.TestCase):
    """Verify that policy and exact receipts become enforceable outcomes."""

    def setUp(self) -> None:
        self.now = 100.0
        self.authority = ApprovalAuthority(clock=lambda: self.now)

    def test_allowed_action_does_not_need_approval(self) -> None:
        result = authorize_action(ActionKind.READ_PROJECT_FILE)

        self.assertTrue(result.allowed)

    def test_sensitive_action_is_blocked_without_receipt(self) -> None:
        result = authorize_action(ActionKind.BROWSER_NAVIGATION)

        self.assertFalse(result.allowed)

    def test_exact_sensitive_action_is_allowed_once(self) -> None:
        arguments = {"url": "https://example.com"}
        receipt = self.authority.issue(ActionKind.BROWSER_NAVIGATION, arguments)

        first_result = authorize_action(
            ActionKind.BROWSER_NAVIGATION,
            arguments=arguments,
            approval_receipt=receipt,
            approval_authority=self.authority,
        )
        second_result = authorize_action(
            ActionKind.BROWSER_NAVIGATION,
            arguments=arguments,
            approval_receipt=receipt,
            approval_authority=self.authority,
        )

        self.assertTrue(first_result.allowed)
        self.assertFalse(second_result.allowed)

    def test_receipt_cannot_approve_a_different_action(self) -> None:
        receipt = self.authority.issue(
            ActionKind.BROWSER_NAVIGATION,
            {"url": "https://example.com"},
        )

        result = authorize_action(
            ActionKind.NETWORK_REQUEST,
            arguments={"url": "https://example.com"},
            approval_receipt=receipt,
            approval_authority=self.authority,
        )

        self.assertFalse(result.allowed)

    def test_receipt_cannot_approve_different_arguments(self) -> None:
        receipt = self.authority.issue(
            ActionKind.BROWSER_NAVIGATION,
            {"url": "https://safe.example"},
        )

        result = authorize_action(
            ActionKind.BROWSER_NAVIGATION,
            arguments={"url": "https://other.example"},
            approval_receipt=receipt,
            approval_authority=self.authority,
        )

        self.assertFalse(result.allowed)

    def test_argument_key_order_does_not_change_the_approved_request(self) -> None:
        receipt = self.authority.issue(
            ActionKind.NETWORK_REQUEST,
            {"method": "POST", "url": "https://example.com"},
        )

        result = authorize_action(
            ActionKind.NETWORK_REQUEST,
            arguments={"url": "https://example.com", "method": "POST"},
            approval_receipt=receipt,
            approval_authority=self.authority,
        )

        self.assertTrue(result.allowed)

    def test_failed_mismatch_attempt_also_consumes_the_receipt(self) -> None:
        approved_arguments = {"url": "https://safe.example"}
        receipt = self.authority.issue(
            ActionKind.BROWSER_NAVIGATION,
            approved_arguments,
        )

        authorize_action(
            ActionKind.BROWSER_NAVIGATION,
            arguments={"url": "https://other.example"},
            approval_receipt=receipt,
            approval_authority=self.authority,
        )
        retry = authorize_action(
            ActionKind.BROWSER_NAVIGATION,
            arguments=approved_arguments,
            approval_receipt=receipt,
            approval_authority=self.authority,
        )

        self.assertFalse(retry.allowed)

    def test_expired_receipt_is_blocked(self) -> None:
        receipt = self.authority.issue(
            ActionKind.WRITE_LOCAL_FILE,
            {"path": "notes.txt"},
            lifetime_seconds=10,
        )
        self.now = 110.0

        result = authorize_action(
            ActionKind.WRITE_LOCAL_FILE,
            arguments={"path": "notes.txt"},
            approval_receipt=receipt,
            approval_authority=self.authority,
        )

        self.assertFalse(result.allowed)

    def test_forged_receipt_is_blocked(self) -> None:
        result = authorize_action(
            ActionKind.BROWSER_NAVIGATION,
            arguments={"url": "https://example.com"},
            approval_receipt=ApprovalReceipt("invented-token"),
            approval_authority=self.authority,
        )

        self.assertFalse(result.allowed)

    def test_denied_action_stays_blocked(self) -> None:
        result = authorize_action(ActionKind.ACCESS_CREDENTIALS)

        self.assertFalse(result.allowed)

    def test_receipt_cannot_be_issued_for_denied_or_allowed_actions(self) -> None:
        for action in (
            ActionKind.ACCESS_CREDENTIALS,
            ActionKind.READ_PROJECT_FILE,
        ):
            with self.subTest(action=action), self.assertRaises(ValueError):
                self.authority.issue(action)

    def test_receipt_lifetime_has_a_short_hard_ceiling(self) -> None:
        with self.assertRaises(ValueError):
            self.authority.issue(
                ActionKind.NETWORK_REQUEST,
                lifetime_seconds=MAX_APPROVAL_LIFETIME_SECONDS + 1,
            )

    def test_non_json_arguments_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.authority.issue(
                ActionKind.NETWORK_REQUEST,
                {"headers": {"unsafe-set"}},
            )

    def test_non_json_execution_arguments_fail_closed_and_consume_receipt(self) -> None:
        receipt = self.authority.issue(
            ActionKind.NETWORK_REQUEST,
            {"headers": ["Accept: application/json"]},
        )

        result = authorize_action(
            ActionKind.NETWORK_REQUEST,
            arguments={"headers": {"unsafe-set"}},
            approval_receipt=receipt,
            approval_authority=self.authority,
        )
        retry = authorize_action(
            ActionKind.NETWORK_REQUEST,
            arguments={"headers": ["Accept: application/json"]},
            approval_receipt=receipt,
            approval_authority=self.authority,
        )

        self.assertFalse(result.allowed)
        self.assertFalse(retry.allowed)


if __name__ == "__main__":
    unittest.main()
