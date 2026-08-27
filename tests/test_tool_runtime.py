"""Security and behavior tests for the deterministic Module 2 tool runtime."""

from datetime import datetime, timedelta, timezone
import json
import unittest
from uuid import uuid4

from personal_assistant.audit import AuditWriteError, InMemoryAuditSink
from personal_assistant.model import ModelToolCall, ModelToolDefinition
from personal_assistant.permissions import ActionKind
from personal_assistant.tool_runtime import (
    RegisteredTool,
    ToolExecutionContext,
    ToolExecutionStatus,
    ToolExecutor,
    ToolInputError,
    ToolRegistry,
    default_tool_registry,
)


class ToolRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.audit = InMemoryAuditSink()
        fixed = datetime(
            2026,
            8,
            27,
            9,
            15,
            30,
            tzinfo=timezone(timedelta(hours=-6), "MDT"),
        )
        self.executor = ToolExecutor(
            default_tool_registry(clock=lambda: fixed),
            self.audit,
        )

    def test_time_tool_accepts_no_arguments_and_uses_aware_clock(self) -> None:
        result = self.executor.execute(
            ModelToolCall.create("get_current_datetime", {}),
            uuid4(),
        )

        self.assertIs(result.status, ToolExecutionStatus.SUCCEEDED)
        document = json.loads(result.content)
        self.assertTrue(document["ok"])
        self.assertEqual(document["trust"], "untrusted_tool_data")
        self.assertEqual(document["data"]["calendar_date"], "2026-08-27")
        self.assertEqual(document["data"]["datetime"], "2026-08-27T09:15:30-06:00")
        self.assertEqual(document["data"]["iso_weekday"], 4)
        self.assertEqual(document["data"]["local_time"], "09:15:30")
        self.assertEqual(document["data"]["timezone"], "MDT")
        self.assertEqual(document["data"]["utc_offset_seconds"], -21_600)
        self.assertEqual(document["data"]["weekday"], "Thursday")

        refused = self.executor.execute(
            ModelToolCall.create("get_current_datetime", {"timezone": "UTC"}),
            uuid4(),
        )
        self.assertIs(refused.status, ToolExecutionStatus.DENIED)

    def test_calculator_performs_bounded_decimal_operations_without_eval(self) -> None:
        call = ModelToolCall.create(
            "calculate",
            {"operator": "multiply", "left": 12.5, "right": 4},
        )

        result = self.executor.execute(call, uuid4())

        self.assertIs(result.status, ToolExecutionStatus.SUCCEEDED)
        self.assertEqual(json.loads(result.content)["data"]["result"], "50")

    def test_calculator_rejects_extra_fields_non_numbers_and_division_by_zero(self) -> None:
        invalid_arguments = (
            {"operator": "add", "left": 1, "right": 2, "expression": "1+2"},
            {"operator": "add", "left": True, "right": 2},
            {"operator": "add", "left": "__import__('os')", "right": 2},
            {"operator": "divide", "left": 1, "right": 0},
            {"operator": "power", "left": 2, "right": 1000},
            {"operator": "multiply", "left": 1_000_000_000_000, "right": 2},
        )

        for arguments in invalid_arguments:
            with self.subTest(arguments=arguments):
                result = self.executor.execute(
                    ModelToolCall.create("calculate", arguments),
                    uuid4(),
                )
                self.assertIsNot(result.status, ToolExecutionStatus.SUCCEEDED)

    def test_unknown_and_duplicate_tools_fail_closed(self) -> None:
        unknown = self.executor.execute(
            ModelToolCall.create("invented_tool", {}),
            uuid4(),
        )
        self.assertIs(unknown.status, ToolExecutionStatus.DENIED)

        tool = RegisteredTool(
            ModelToolDefinition.create(
                "synthetic_tool",
                "Synthetic tool.",
                {"type": "object", "properties": {}},
            ),
            ActionKind.READ_SYSTEM_TIME,
            lambda arguments: dict(arguments),
            lambda _arguments: {},
        )
        with self.assertRaisesRegex(ValueError, "unique"):
            ToolRegistry((tool, tool))

    def test_approval_required_tool_cannot_execute_without_authority(self) -> None:
        calls: list[bool] = []

        def validate(arguments):
            if arguments:
                raise ToolInputError("No arguments accepted.")
            return {}

        tool = RegisteredTool(
            ModelToolDefinition.create(
                "synthetic_network",
                "Synthetic approval-required tool.",
                {"type": "object", "properties": {}},
            ),
            ActionKind.NETWORK_REQUEST,
            validate,
            lambda _arguments: calls.append(True) or {},
        )
        executor = ToolExecutor(ToolRegistry((tool,)), self.audit)

        result = executor.execute(
            ModelToolCall.create("synthetic_network", {}),
            uuid4(),
        )

        self.assertIs(result.status, ToolExecutionStatus.DENIED)
        self.assertEqual(calls, [])

    def test_web_search_ignores_model_query_and_uses_current_user_message(self) -> None:
        class SearchProvider:
            def __init__(self) -> None:
                self.queries: list[str] = []

            def search(self, query: str):
                self.queries.append(query)
                return {
                    "provider": "searxng",
                    "results": [],
                    "trust": "untrusted_web_search_results",
                }

        provider = SearchProvider()
        executor = ToolExecutor(default_tool_registry(web_search=provider), self.audit)
        call = ModelToolCall.create(
            "search_public_web",
            {"query": "latest SearXNG release"},
        )

        allowed = executor.execute(
            call,
            uuid4(),
            execution_context=ToolExecutionContext(
                "Please search for the latest SearXNG release."
            ),
        )
        model_injection_ignored = executor.execute(
            ModelToolCall.create(
                "search_public_web",
                {"query": {"private": "model memory value"}},
            ),
            uuid4(),
            execution_context=ToolExecutionContext(
                "Please search for the latest SearXNG release."
            ),
        )

        self.assertIs(allowed.status, ToolExecutionStatus.SUCCEEDED)
        self.assertIs(model_injection_ignored.status, ToolExecutionStatus.SUCCEEDED)
        self.assertEqual(
            provider.queries,
            [
                "Please search for the latest SearXNG release.",
                "Please search for the latest SearXNG release.",
            ],
        )
        self.assertFalse(executor.repeat_allowed("search_public_web"))
        self.assertTrue(executor.repeat_allowed("calculate"))

    def test_web_search_rejects_unbounded_current_user_message(self) -> None:
        class SearchProvider:
            def search(self, query: str):
                raise AssertionError(f"Search must not run for {query}")

        executor = ToolExecutor(
            default_tool_registry(web_search=SearchProvider()),
            self.audit,
        )

        result = executor.execute(
            ModelToolCall.create("search_public_web", {}),
            uuid4(),
            execution_context=ToolExecutionContext("x" * 257),
        )

        self.assertIs(result.status, ToolExecutionStatus.DENIED)
        self.assertIn("bounded public query", result.content)

    def test_web_search_query_is_not_written_to_audit(self) -> None:
        class SearchProvider:
            def search(self, query: str):
                return {
                    "provider": "searxng",
                    "results": [],
                    "trust": "untrusted_web_search_results",
                }

        secret_query = "synthetic-personal-search-phrase"
        executor = ToolExecutor(
            default_tool_registry(web_search=SearchProvider()),
            self.audit,
        )
        executor.execute(
            ModelToolCall.create("search_public_web", {}),
            uuid4(),
            execution_context=ToolExecutionContext(secret_query),
        )

        self.assertNotIn(secret_query, repr(self.audit.events))

    def test_web_search_does_not_start_when_initial_audit_fails(self) -> None:
        calls: list[str] = []

        class SearchProvider:
            def search(self, query: str):
                calls.append(query)
                return {"results": []}

        class FailingAuditSink:
            def write(self, _event) -> None:
                raise AuditWriteError("synthetic audit failure")

        executor = ToolExecutor(
            default_tool_registry(web_search=SearchProvider()),
            FailingAuditSink(),
        )

        with self.assertRaises(AuditWriteError):
            executor.execute(
                ModelToolCall.create(
                    "search_public_web",
                    {"query": "current public result"},
                ),
                uuid4(),
                execution_context=ToolExecutionContext("current public result"),
            )

        self.assertEqual(calls, [])

    def test_web_search_failure_names_local_service_without_leaking_error(self) -> None:
        class FailingSearchProvider:
            def search(self, query: str):
                raise RuntimeError(f"private failure for {query}")

        executor = ToolExecutor(
            default_tool_registry(web_search=FailingSearchProvider()),
            self.audit,
        )
        result = executor.execute(
            ModelToolCall.create("search_public_web", {"query": "current weather"}),
            uuid4(),
            execution_context=ToolExecutionContext("What is the current weather?"),
        )

        self.assertIs(result.status, ToolExecutionStatus.FAILED)
        document = json.loads(result.content)
        self.assertEqual(
            document["data"]["message"],
            "The local web-search service is unavailable or returned an invalid "
            "response.",
        )
        self.assertNotIn("private failure", result.content)

    def test_audit_events_exclude_arguments_results_and_exception_text(self) -> None:
        secret_number = 987_654_321
        self.executor.execute(
            ModelToolCall.create(
                "calculate",
                {"operator": "add", "left": secret_number, "right": 1},
            ),
            uuid4(),
        )

        serialized = repr(self.audit.events)
        self.assertNotIn(str(secret_number), serialized)
        self.assertNotIn("987654322", serialized)
        self.assertNotIn("left", serialized)
        self.assertTrue(self.audit.events)

    def test_failed_start_audit_prevents_handler_execution(self) -> None:
        calls: list[bool] = []

        class FailingAuditSink:
            def write(self, _event) -> None:
                raise AuditWriteError("synthetic audit failure")

        tool = RegisteredTool(
            ModelToolDefinition.create(
                "synthetic_safe_tool",
                "Synthetic safe tool.",
                {"additionalProperties": False, "properties": {}, "type": "object"},
            ),
            ActionKind.READ_SYSTEM_TIME,
            lambda arguments: dict(arguments),
            lambda _arguments: calls.append(True) or {},
        )
        executor = ToolExecutor(ToolRegistry((tool,)), FailingAuditSink())

        with self.assertRaises(AuditWriteError):
            executor.execute(
                ModelToolCall.create("synthetic_safe_tool", {}),
                uuid4(),
            )

        self.assertEqual(calls, [])

    def test_close_releases_app_owned_resources_exactly_once(self) -> None:
        close_calls: list[bool] = []
        executor = ToolExecutor(
            default_tool_registry(),
            self.audit,
            resource_closers=(lambda: close_calls.append(True),),
        )

        executor.close()
        executor.close()

        self.assertEqual(close_calls, [True])


if __name__ == "__main__":
    unittest.main()
