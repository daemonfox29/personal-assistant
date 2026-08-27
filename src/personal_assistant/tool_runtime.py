"""Deny-by-default registry and executor for narrow model-requested tools."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, DivisionByZero, InvalidOperation, localcontext
from enum import StrEnum
import json
import time
from uuid import UUID

from personal_assistant.audit import (
    AuditComponent,
    AuditError,
    AuditEvent,
    AuditMetadataItem,
    AuditMetadataKey,
    AuditOperation,
    AuditOutcome,
    AuditReasonCode,
    AuditSink,
)
from personal_assistant.authorization import (
    ApprovalAuthority,
    ApprovalReceipt,
    authorize_action,
)
from personal_assistant.model import ModelToolCall, ModelToolDefinition
from personal_assistant.permissions import ActionKind
from personal_assistant.web_search import (
    WebSearchProvider,
    query_is_derived_from_user_text,
    validate_search_query,
)


MAX_TOOL_RESULT_BYTES = 2_048
MAX_DECIMAL_DIGITS = 24
MAX_DECIMAL_MAGNITUDE = Decimal("1000000000000")
WEEKDAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


class ToolRuntimeError(RuntimeError):
    """A tool request failed inside the deterministic runtime boundary."""


class ToolInputError(ToolRuntimeError):
    """A model supplied arguments outside a registered tool's schema."""


class ToolExecutionStatus(StrEnum):
    SUCCEEDED = "succeeded"
    DENIED = "denied"
    FAILED = "failed"


@dataclass(frozen=True)
class ToolExecutionResult:
    """One bounded tool-role payload safe to return as untrusted model data."""

    tool_name: str
    status: ToolExecutionStatus
    content: str


@dataclass(frozen=True)
class ToolExecutionContext:
    """Request-scoped data used only by deterministic contextual validators."""

    user_text: str

    def __post_init__(self) -> None:
        if not isinstance(self.user_text, str):
            raise TypeError("Tool execution context requires current user text.")


ToolValidator = Callable[[Mapping[str, object]], dict[str, object]]
ToolHandler = Callable[[Mapping[str, object]], Mapping[str, object]]
ToolContextValidator = Callable[
    [Mapping[str, object], ToolExecutionContext],
    None,
]


@dataclass(frozen=True)
class RegisteredTool:
    """One trusted binding from model schema to policy and implementation."""

    definition: ModelToolDefinition
    action: ActionKind
    validator: ToolValidator
    handler: ToolHandler
    context_validator: ToolContextValidator | None = None
    repeat_allowed: bool = True
    failure_message: str = "The tool could not complete safely."

    def __post_init__(self) -> None:
        if not isinstance(self.definition, ModelToolDefinition):
            raise TypeError("A registered tool requires a model definition.")
        if not isinstance(self.action, ActionKind):
            raise TypeError("A registered tool requires an explicit action kind.")
        if not callable(self.validator) or not callable(self.handler):
            raise TypeError("A registered tool requires validator and handler callables.")
        if self.context_validator is not None and not callable(
            self.context_validator
        ):
            raise TypeError("A registered tool context validator must be callable.")
        if not isinstance(self.repeat_allowed, bool):
            raise TypeError("A registered tool repeat policy must be a boolean.")
        if (
            not isinstance(self.failure_message, str)
            or not self.failure_message
            or len(self.failure_message) > 200
        ):
            raise TypeError("A registered tool failure message must be bounded text.")


class ToolRegistry:
    """Expose immutable definitions while keeping implementations private."""

    def __init__(self, tools: tuple[RegisteredTool, ...]) -> None:
        if not isinstance(tools, tuple) or not all(
            isinstance(tool, RegisteredTool) for tool in tools
        ):
            raise TypeError("A tool registry requires registered tools.")
        names = [tool.definition.name for tool in tools]
        if len(names) != len(set(names)):
            raise ValueError("Tool names must be unique.")
        self._tools = {tool.definition.name: tool for tool in tools}

    @property
    def definitions(self) -> tuple[ModelToolDefinition, ...]:
        return tuple(tool.definition for tool in self._tools.values())

    def resolve(self, name: str) -> RegisteredTool | None:
        if not isinstance(name, str):
            return None
        return self._tools.get(name)

    def repeat_allowed(self, name: str) -> bool:
        tool = self.resolve(name)
        return bool(tool is not None and tool.repeat_allowed)


class ToolExecutor:
    """Validate, authorize, audit, and invoke registered callables only."""

    def __init__(self, registry: ToolRegistry, audit_sink: AuditSink) -> None:
        if not isinstance(registry, ToolRegistry):
            raise TypeError("A tool executor requires a registry.")
        if not isinstance(audit_sink, AuditSink):
            raise TypeError("A tool executor requires an audit sink.")
        self._registry = registry
        self._audit_sink = audit_sink

    @property
    def definitions(self) -> tuple[ModelToolDefinition, ...]:
        return self._registry.definitions

    def repeat_allowed(self, name: str) -> bool:
        return self._registry.repeat_allowed(name)

    def execute(
        self,
        call: ModelToolCall,
        correlation_id: UUID,
        *,
        execution_context: ToolExecutionContext | None = None,
        approval_receipt: ApprovalReceipt | None = None,
        approval_authority: ApprovalAuthority | None = None,
    ) -> ToolExecutionResult:
        if not isinstance(call, ModelToolCall) or not isinstance(
            correlation_id, UUID
        ):
            raise TypeError("Tool execution requires a typed call and correlation ID.")
        started = time.monotonic()
        tool = self._registry.resolve(call.name)
        if tool is None:
            self._audit(
                correlation_id,
                AuditOutcome.DENIED,
                AuditReasonCode.POLICY_DENIED,
                (),
                started,
            )
            return self._fixed_result(
                call.name,
                ToolExecutionStatus.DENIED,
                "The requested tool is not registered.",
            )
        metadata = (
            AuditMetadataItem(AuditMetadataKey.ACTION_KIND, tool.action.value),
            AuditMetadataItem(AuditMetadataKey.TARGET_CLASS, tool.definition.name),
        )
        try:
            arguments = tool.validator(call.arguments())
            if tool.context_validator is not None:
                if execution_context is None:
                    raise ToolInputError("Request context is required.")
                tool.context_validator(arguments, execution_context)
        except (ToolInputError, TypeError, ValueError):
            self._audit(
                correlation_id,
                AuditOutcome.DENIED,
                AuditReasonCode.INVALID_DATA,
                metadata,
                started,
            )
            return self._fixed_result(
                tool.definition.name,
                ToolExecutionStatus.DENIED,
                "The tool arguments were invalid.",
            )
        authorization = authorize_action(
            tool.action,
            arguments=arguments,
            approval_receipt=approval_receipt,
            approval_authority=approval_authority,
        )
        if not authorization.allowed:
            self._audit(
                correlation_id,
                AuditOutcome.DENIED,
                AuditReasonCode.APPROVAL_REQUIRED,
                metadata,
                started,
            )
            return self._fixed_result(
                tool.definition.name,
                ToolExecutionStatus.DENIED,
                "This tool is not authorized.",
            )
        self._write_audit_event(
            AuditEvent(
                correlation_id=correlation_id,
                component=AuditComponent.TOOL,
                operation=AuditOperation.TOOL_EXECUTE,
                outcome=AuditOutcome.STARTED,
                reason_code=AuditReasonCode.POLICY_ALLOWED,
                metadata=metadata,
            )
        )
        try:
            result = tool.handler(arguments)
            content = self._result_content(True, result)
        except Exception:
            self._audit(
                correlation_id,
                AuditOutcome.FAILED,
                AuditReasonCode.SAFE_INTERNAL_FAILURE,
                metadata,
                started,
            )
            return self._fixed_result(
                tool.definition.name,
                ToolExecutionStatus.FAILED,
                tool.failure_message,
            )
        self._audit(
            correlation_id,
            AuditOutcome.SUCCEEDED,
            AuditReasonCode.NORMAL,
            metadata,
            started,
        )
        return ToolExecutionResult(
            tool.definition.name,
            ToolExecutionStatus.SUCCEEDED,
            content,
        )

    def _audit(
        self,
        correlation_id: UUID,
        outcome: AuditOutcome,
        reason: AuditReasonCode,
        metadata: tuple[AuditMetadataItem, ...],
        started: float,
    ) -> None:
        self._write_audit_event(
            AuditEvent(
                correlation_id=correlation_id,
                component=AuditComponent.TOOL,
                operation=AuditOperation.TOOL_EXECUTE,
                outcome=outcome,
                reason_code=reason,
                metadata=metadata,
                duration_ms=max(0, int((time.monotonic() - started) * 1_000)),
            )
        )

    def _write_audit_event(self, event: AuditEvent) -> None:
        try:
            self._audit_sink.write(event)
        except AuditError:
            raise
        except Exception as error:
            raise AuditError("The tool audit trail is unavailable.") from error

    @staticmethod
    def _fixed_result(
        tool_name: str,
        status: ToolExecutionStatus,
        message: str,
    ) -> ToolExecutionResult:
        return ToolExecutionResult(
            tool_name,
            status,
            ToolExecutor._result_content(False, {"message": message}),
        )

    @staticmethod
    def _result_content(ok: bool, data: Mapping[str, object]) -> str:
        document = {
            "data": dict(data),
            "ok": ok,
            "trust": "untrusted_tool_data",
        }
        try:
            content = json.dumps(
                document,
                ensure_ascii=True,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        except (TypeError, ValueError) as error:
            raise ToolRuntimeError("Tool result data is invalid.") from error
        if len(content.encode("utf-8")) > MAX_TOOL_RESULT_BYTES:
            raise ToolRuntimeError("Tool result data exceeds its size limit.")
        return content


def default_tool_registry(
    *,
    clock: Callable[[], datetime] = lambda: datetime.now().astimezone(),
    web_search: WebSearchProvider | None = None,
) -> ToolRegistry:
    """Build the reviewed registry from code-owned narrow capabilities."""

    if web_search is not None and not isinstance(web_search, WebSearchProvider):
        raise TypeError("The tool registry requires a web search provider.")

    def validate_time(arguments: Mapping[str, object]) -> dict[str, object]:
        if dict(arguments):
            raise ToolInputError("The time tool accepts no arguments.")
        return {}

    def current_time(_arguments: Mapping[str, object]) -> Mapping[str, object]:
        value = clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ToolRuntimeError("The system clock did not provide an aware time.")
        offset = value.utcoffset()
        if offset is None:
            raise ToolRuntimeError("The system clock did not provide a UTC offset.")
        zone = str(value.tzname() or "local")
        if not zone or len(zone) > 64:
            zone = "local"
        return {
            "calendar_date": value.date().isoformat(),
            "datetime": value.isoformat(timespec="seconds"),
            "iso_weekday": value.isoweekday(),
            "local_time": value.time().isoformat(timespec="seconds"),
            "timezone": zone,
            "utc_offset_seconds": int(offset.total_seconds()),
            "weekday": WEEKDAYS[value.weekday()],
        }

    def validate_calculation(arguments: Mapping[str, object]) -> dict[str, object]:
        if set(arguments) != {"operator", "left", "right"}:
            raise ToolInputError("Calculation fields are invalid.")
        operator = arguments["operator"]
        if operator not in {"add", "subtract", "multiply", "divide"}:
            raise ToolInputError("Calculation operator is invalid.")
        left = _bounded_decimal(arguments["left"])
        right = _bounded_decimal(arguments["right"])
        if operator == "divide" and right == 0:
            raise ToolInputError("Division by zero is invalid.")
        return {"operator": operator, "left": str(left), "right": str(right)}

    def calculate(arguments: Mapping[str, object]) -> Mapping[str, object]:
        operator = arguments["operator"]
        left = Decimal(str(arguments["left"]))
        right = Decimal(str(arguments["right"]))
        try:
            with localcontext() as context:
                context.prec = MAX_DECIMAL_DIGITS
                if operator == "add":
                    result = left + right
                elif operator == "subtract":
                    result = left - right
                elif operator == "multiply":
                    result = left * right
                else:
                    result = left / right
        except (DivisionByZero, InvalidOperation) as error:
            raise ToolInputError("The calculation is invalid.") from error
        if not result.is_finite() or abs(result) > MAX_DECIMAL_MAGNITUDE:
            raise ToolInputError("The calculation result is outside its limit.")
        rendered = format(result.normalize(), "f")
        if rendered == "-0":
            rendered = "0"
        if len(rendered) > 64:
            raise ToolInputError("The calculation result is outside its limit.")
        return {"result": rendered}

    def validate_web_search(arguments: Mapping[str, object]) -> dict[str, object]:
        if set(arguments) != {"query"}:
            raise ToolInputError("Search fields are invalid.")
        try:
            query = validate_search_query(arguments["query"])
        except ValueError as error:
            raise ToolInputError("The search query is invalid.") from error
        return {"query": query}

    def validate_web_search_context(
        arguments: Mapping[str, object],
        context: ToolExecutionContext,
    ) -> None:
        if not query_is_derived_from_user_text(
            str(arguments["query"]),
            context.user_text,
        ):
            raise ToolInputError("The search query was not supplied by the user.")

    def search_web(arguments: Mapping[str, object]) -> Mapping[str, object]:
        if web_search is None:
            raise ToolRuntimeError("Web search is unavailable.")
        return web_search.search(str(arguments["query"]))

    tools = [
        RegisteredTool(
            ModelToolDefinition.create(
                "get_current_datetime",
                "Get the authoritative current local date, time, weekday, "
                "timezone, and UTC offset.",
                {
                    "additionalProperties": False,
                    "properties": {},
                    "type": "object",
                },
            ),
            ActionKind.READ_SYSTEM_TIME,
            validate_time,
            current_time,
        ),
        RegisteredTool(
            ModelToolDefinition.create(
                "calculate",
                "Perform one bounded decimal arithmetic operation.",
                {
                    "additionalProperties": False,
                    "properties": {
                        "left": {"type": "number"},
                        "operator": {
                            "enum": [
                                "add",
                                "subtract",
                                "multiply",
                                "divide",
                            ],
                            "type": "string",
                        },
                        "right": {"type": "number"},
                    },
                    "required": ["operator", "left", "right"],
                    "type": "object",
                },
            ),
            ActionKind.CALCULATE,
            validate_calculation,
            calculate,
        ),
    ]
    if web_search is not None:
        tools.append(
            RegisteredTool(
                ModelToolDefinition.create(
                    "search_public_web",
                    "Search current public web results using words from the "
                    "user's current message.",
                    {
                        "additionalProperties": False,
                        "properties": {
                            "query": {
                                "maxLength": 256,
                                "minLength": 2,
                                "type": "string",
                            }
                        },
                        "required": ["query"],
                        "type": "object",
                    },
                ),
                ActionKind.WEB_SEARCH,
                validate_web_search,
                search_web,
                context_validator=validate_web_search_context,
                repeat_allowed=False,
                failure_message=(
                    "The local web-search service is unavailable or returned an "
                    "invalid response."
                ),
            )
        )
    return ToolRegistry(tuple(tools))


def _bounded_decimal(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ToolInputError("Calculation values must be JSON numbers.")
    try:
        decimal = Decimal(str(value))
    except InvalidOperation as error:
        raise ToolInputError("Calculation value is invalid.") from error
    if not decimal.is_finite() or abs(decimal) > MAX_DECIMAL_MAGNITUDE:
        raise ToolInputError("Calculation value is outside its limit.")
    if len(decimal.as_tuple().digits) > MAX_DECIMAL_DIGITS:
        raise ToolInputError("Calculation value has too much precision.")
    return decimal
