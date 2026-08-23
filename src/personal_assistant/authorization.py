"""Enforce permission decisions before an action can be executed."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import hashlib
import json
import math
import secrets
from threading import Lock
import time

from personal_assistant.permissions import (
    ActionKind,
    PermissionDecision,
    evaluate_action,
)


DEFAULT_APPROVAL_LIFETIME_SECONDS = 60.0
MAX_APPROVAL_LIFETIME_SECONDS = 300.0


@dataclass(frozen=True)
class AuthorizationResult:
    """Whether an action may proceed and the reason for that outcome."""

    allowed: bool
    reason: str


@dataclass(frozen=True)
class ApprovalReceipt:
    """An opaque reference to one approval held by a trusted authority."""

    token: str = field(repr=False)


@dataclass(frozen=True)
class _ApprovalRecord:
    action: ActionKind
    arguments_digest: str
    expires_at: float


def _normalized_json_value(value: object) -> object:
    """Return strictly JSON-compatible data without ambiguous key coercion."""

    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Action arguments cannot contain NaN or infinity.")
        return value
    if isinstance(value, list):
        return [_normalized_json_value(item) for item in value]
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("Action argument names must be strings.")
            normalized[key] = _normalized_json_value(item)
        return normalized
    raise ValueError("Action arguments must contain only JSON-compatible values.")


def _arguments_digest(arguments: Mapping[str, object] | None) -> str:
    normalized = _normalized_json_value({} if arguments is None else arguments)
    canonical = json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ApprovalAuthority:
    """Issue and consume short-lived approvals from one trusted process."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._records: dict[str, _ApprovalRecord] = {}
        self._lock = Lock()

    def issue(
        self,
        action: ActionKind,
        arguments: Mapping[str, object] | None = None,
        *,
        lifetime_seconds: float = DEFAULT_APPROVAL_LIFETIME_SECONDS,
    ) -> ApprovalReceipt:
        """Create one receipt after a trusted interface confirms approval."""

        permission = evaluate_action(action)
        if permission.decision is not PermissionDecision.REQUIRE_APPROVAL:
            raise ValueError("Receipts are only issued for approval-required actions.")
        if not 0 < lifetime_seconds <= MAX_APPROVAL_LIFETIME_SECONDS:
            raise ValueError(
                "Approval lifetime must be greater than zero and no more than "
                f"{MAX_APPROVAL_LIFETIME_SECONDS:g} seconds."
            )

        now = self._clock()
        record = _ApprovalRecord(
            action=action,
            arguments_digest=_arguments_digest(arguments),
            expires_at=now + lifetime_seconds,
        )
        with self._lock:
            self._remove_expired_records(now)
            token = secrets.token_urlsafe(32)
            while token in self._records:
                token = secrets.token_urlsafe(32)
            self._records[token] = record
        return ApprovalReceipt(token)

    def consume(
        self,
        receipt: ApprovalReceipt,
        action: ActionKind,
        arguments: Mapping[str, object] | None = None,
    ) -> AuthorizationResult:
        """Consume a receipt once, then verify its lifetime and exact request."""

        now = self._clock()
        with self._lock:
            record = self._records.pop(receipt.token, None)
            self._remove_expired_records(now)

        if record is None:
            return AuthorizationResult(
                False,
                "Approval receipt is invalid or has already been used.",
            )
        if now >= record.expires_at:
            return AuthorizationResult(False, "Approval receipt has expired.")
        if record.action is not action:
            return AuthorizationResult(
                False,
                "Approval receipt does not match the requested action.",
            )
        try:
            supplied_arguments_digest = _arguments_digest(arguments)
        except ValueError:
            return AuthorizationResult(
                False,
                "Requested action arguments are not valid approval data.",
            )
        if record.arguments_digest != supplied_arguments_digest:
            return AuthorizationResult(
                False,
                "Approval receipt does not match the requested arguments.",
            )
        return AuthorizationResult(True, "User approved this exact action.")

    def _remove_expired_records(self, now: float) -> None:
        expired_tokens = [
            token
            for token, record in self._records.items()
            if now >= record.expires_at
        ]
        for token in expired_tokens:
            del self._records[token]


def authorize_action(
    action: ActionKind,
    *,
    arguments: Mapping[str, object] | None = None,
    approval_receipt: ApprovalReceipt | None = None,
    approval_authority: ApprovalAuthority | None = None,
) -> AuthorizationResult:
    """Allow an action only when policy and an exact approval permit it."""

    permission = evaluate_action(action)

    if permission.decision is PermissionDecision.ALLOW:
        return AuthorizationResult(True, permission.reason)

    if permission.decision is PermissionDecision.REQUIRE_APPROVAL:
        if approval_receipt is None or approval_authority is None:
            return AuthorizationResult(False, permission.reason)
        return approval_authority.consume(approval_receipt, action, arguments)

    return AuthorizationResult(False, permission.reason)
