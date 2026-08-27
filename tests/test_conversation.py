"""UI-neutral conversation-service boundary tests."""

from threading import Event, Thread
import unittest
from unittest.mock import Mock
from uuid import UUID

from personal_assistant.assistant_preferences import CommunicationStyle
from personal_assistant.audit import InMemoryAuditSink
from personal_assistant.conversation import (
    ConversationEventKind,
    ConversationService,
    _is_broad_current_events_request,
)
from personal_assistant.model import (
    LanguageModel,
    MessageRole,
    ModelRequest,
    ModelResponse,
    ModelStreamChunk,
    ModelToolCall,
    ModelUnavailableError,
)
from personal_assistant.tool_runtime import ToolExecutor, default_tool_registry
from personal_assistant.web_reader import PublicWebPageReader
from personal_assistant.web_search import WebSearchError, WebSearchFailureCode


class SyntheticStreamingModel:
    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    def generate(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse("synthetic full response")

    def stream_generate(self, request: ModelRequest):  # type: ignore[no-untyped-def]
        self.requests.append(request)
        yield ModelStreamChunk("synthetic ")
        yield ModelStreamChunk("response\u202e", "length")


class UnavailableModel:
    def generate(self, request: ModelRequest) -> ModelResponse:
        raise ModelUnavailableError("raw unavailable details")


class BlockingModel:
    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.started.set()
        self.release.wait(timeout=2)
        return ModelResponse("finished")


class ToolCallingStreamingModel:
    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    def generate(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse("synthetic full response")

    def stream_generate(self, request: ModelRequest):  # type: ignore[no-untyped-def]
        self.requests.append(request)
        if request.messages[-1].role is MessageRole.TOOL:
            yield ModelStreamChunk("The calculated result is 5.")
            return
        yield ModelStreamChunk(
            "",
            tool_calls=(
                ModelToolCall.create(
                    "calculate",
                    {"operator": "add", "left": 2, "right": 3},
                ),
            ),
        )


class RepeatingToolModel:
    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return ModelResponse(
            "",
            (ModelToolCall.create("get_current_datetime", {}),),
        )


class SearchProvider:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, query: str):
        self.queries.append(query)
        return {
            "provider": "searxng",
            "results": [
                {
                    "title": "Example",
                    "snippet": "Current public information.",
                    "url": "https://example.test/current",
                }
            ],
            "trust": "untrusted_web_search_results",
        }


class RecordingMemoryHandler:
    def __init__(self) -> None:
        self.calls: list[tuple[str, UUID]] = []

    def remember(self, content: str, correlation_id: UUID) -> str:
        self.calls.append((content, correlation_id))
        return "Synthetic memory saved."


class RecordingContextProvider:
    def __init__(self) -> None:
        self.calls = 0

    def context_for(self, user_text: str, correlation_id: UUID) -> str:
        self.calls += 1
        return "\nPersistent context that private chat must not receive."


class RecordingPostResponseWorker:
    def __init__(self) -> None:
        self.calls = 0
        self.wait_calls = 0
        self.capture_calls: list[str] = []
        self.capture_result: tuple[str, ...] | None = None

    def capture_before_response(self, user_text: str) -> tuple[str, ...] | None:
        self.capture_calls.append(user_text)
        return self.capture_result

    def submit(self, user_text: str, assistant_text: str) -> bool:
        self.calls += 1
        return True

    def wait_until_idle(self, timeout_seconds: float = 15.0) -> bool:
        self.wait_calls += 1
        return True

    def close(self) -> None:
        pass


class BlockingHandoffMemoryWorker(RecordingPostResponseWorker):
    def __init__(self) -> None:
        super().__init__()
        self.wait_started = Event()
        self.release = Event()
        self.closed = False

    def wait_until_idle(self, timeout_seconds: float = 15.0) -> bool:
        self.wait_calls += 1
        self.wait_started.set()
        return self.release.wait(timeout=timeout_seconds)

    def close(self) -> None:
        self.closed = True


class ConversationServiceTests(unittest.TestCase):
    def test_registered_tool_result_returns_through_tool_role_before_final_text(
        self,
    ) -> None:
        model = ToolCallingStreamingModel()
        executor = ToolExecutor(default_tool_registry(), InMemoryAuditSink())
        service = ConversationService(model, tool_executor=executor)

        events = tuple(service.events_for("What is two plus three?"))

        self.assertEqual(len(model.requests), 2)
        self.assertEqual(len(model.requests[0].tools), 2)
        self.assertIn("Tool calls are proposals only", model.requests[0].messages[0].content)
        tool_message = model.requests[1].messages[-1]
        self.assertIs(tool_message.role, MessageRole.TOOL)
        self.assertEqual(tool_message.tool_name, "calculate")
        self.assertIn('"result":"5"', tool_message.content)
        self.assertEqual(
            "".join(
                event.text
                for event in events
                if event.kind is ConversationEventKind.ASSISTANT_CHUNK
            ),
            "The calculated result is 5.",
        )

    def test_parallel_tool_calls_are_refused_without_execution(self) -> None:
        class ParallelModel:
            def generate(self, request: ModelRequest) -> ModelResponse:
                return ModelResponse(
                    "",
                    (
                        ModelToolCall.create("get_current_datetime", {}, index=0),
                        ModelToolCall.create(
                            "calculate",
                            {"operator": "add", "left": 1, "right": 2},
                            index=1,
                        ),
                    ),
                )

        audit = InMemoryAuditSink()
        service = ConversationService(
            ParallelModel(),
            tool_executor=ToolExecutor(default_tool_registry(), audit),
        )

        events = tuple(service.events_for("Use two tools"))

        self.assertTrue(
            any("Parallel tool requests" in event.text for event in events)
        )
        self.assertEqual(audit.events, ())

    def test_conflicting_nonstream_tool_indexes_are_rejected(self) -> None:
        class ConflictingModel:
            def generate(self, request: ModelRequest) -> ModelResponse:
                return ModelResponse(
                    "",
                    (
                        ModelToolCall.create("get_current_datetime", {}, index=0),
                        ModelToolCall.create(
                            "calculate",
                            {"operator": "add", "left": 1, "right": 2},
                            index=0,
                        ),
                    ),
                )

        audit = InMemoryAuditSink()
        service = ConversationService(
            ConflictingModel(),
            tool_executor=ToolExecutor(default_tool_registry(), audit),
        )

        events = tuple(service.events_for("Use a tool"))

        self.assertTrue(any("unreadable response" in event.text for event in events))
        self.assertEqual(audit.events, ())

    def test_tool_loop_stops_after_three_executions(self) -> None:
        model = RepeatingToolModel()
        audit = InMemoryAuditSink()
        service = ConversationService(
            model,
            tool_executor=ToolExecutor(default_tool_registry(), audit),
        )

        events = tuple(service.events_for("Keep checking the time"))

        self.assertEqual(len(model.requests), 4)
        self.assertEqual(
            sum(event.outcome.value == "succeeded" for event in audit.events),
            3,
        )
        self.assertTrue(any("tool-step limit" in event.text for event in events))

    def test_tool_messages_are_not_persisted_into_the_next_user_turn(self) -> None:
        class FirstToolThenTextModel:
            def __init__(self) -> None:
                self.requests: list[ModelRequest] = []

            def generate(self, request: ModelRequest) -> ModelResponse:
                self.requests.append(request)
                if len(self.requests) == 1:
                    return ModelResponse(
                        "",
                        (ModelToolCall.create("get_current_datetime", {}),),
                    )
                return ModelResponse("done")

        model = FirstToolThenTextModel()
        service = ConversationService(
            model,
            tool_executor=ToolExecutor(default_tool_registry(), InMemoryAuditSink()),
        )

        tuple(service.events_for("What time is it?"))
        tuple(service.events_for("Thanks"))

        next_turn_messages = model.requests[-1].messages
        self.assertFalse(
            any(message.role is MessageRole.TOOL for message in next_turn_messages)
        )

    def test_web_search_uses_current_user_query_and_returns_citation_data(self) -> None:
        class SearchModel:
            def __init__(self) -> None:
                self.requests: list[ModelRequest] = []

            def generate(self, request: ModelRequest) -> ModelResponse:
                self.requests.append(request)
                if request.messages[-1].role is MessageRole.TOOL:
                    return ModelResponse(
                        "Example reports current information "
                        "(https://example.test/current)."
                    )
                return ModelResponse(
                    "",
                    (
                        ModelToolCall.create(
                            "search_public_web",
                            {"query": "latest SearXNG release"},
                        ),
                    ),
                )

        provider = SearchProvider()
        model = SearchModel()
        service = ConversationService(
            model,
            tool_executor=ToolExecutor(
                default_tool_registry(web_search=provider),
                InMemoryAuditSink(),
            ),
        )

        events = tuple(service.events_for("What is the latest SearXNG release?"))

        self.assertEqual(
            provider.queries,
            ["What is the latest SearXNG release?"],
        )
        self.assertIn(
            "Automatically use public web search",
            model.requests[0].messages[0].content,
        )
        self.assertIn(
            "without asking permission",
            model.requests[0].messages[0].content,
        )
        self.assertIn(
            "empty argument object",
            model.requests[0].messages[0].content,
        )
        self.assertIn(
            "untrusted_web_search_results",
            model.requests[1].messages[-1].content,
        )
        self.assertIn(
            "https://example.test/current",
            "".join(event.text for event in events),
        )

    def test_model_search_query_is_not_used_as_outbound_data(self) -> None:
        class InjectingSearchModel:
            def __init__(self) -> None:
                self.requests: list[ModelRequest] = []

            def generate(self, request: ModelRequest) -> ModelResponse:
                self.requests.append(request)
                if len(self.requests) == 1:
                    return ModelResponse(
                        "",
                        (
                            ModelToolCall.create(
                                "search_public_web",
                                {"query": "private model memory value"},
                            ),
                        ),
                    )
                return ModelResponse("Python result.")

        provider = SearchProvider()
        model = InjectingSearchModel()
        service = ConversationService(
            model,
            tool_executor=ToolExecutor(
                default_tool_registry(web_search=provider),
                InMemoryAuditSink(),
            ),
        )

        events = tuple(
            service.events_for("What is the current Python release today?")
        )

        self.assertEqual(
            provider.queries,
            ["What is the current Python release today?"],
        )
        self.assertNotIn("private model memory value", repr(provider.queries))
        self.assertEqual(len(model.requests), 2)
        self.assertIn("Python result.", "".join(event.text for event in events))

    def test_recent_news_search_auto_reads_before_synthesized_answer(self) -> None:
        class ReadingModel:
            def __init__(self) -> None:
                self.requests: list[ModelRequest] = []

            def generate(self, request: ModelRequest) -> ModelResponse:
                self.requests.append(request)
                last = request.messages[-1]
                if last.role is MessageRole.USER:
                    return ModelResponse(
                        "I cannot access current information. Check these links."
                    )
                return ModelResponse(
                    "The current update is synthesized from the report "
                    "(https://example.test/current)."
                )

        provider = SearchProvider()
        reader = PublicWebPageReader(
            fetcher=lambda _url, _timeout: (
                "text/plain",
                "utf-8",
                b"Detailed current public report for synthesis.",
            )
        )
        model = ReadingModel()
        service = ConversationService(
            model,
            communication_style=CommunicationStyle("a" * 2_000),
            context_window_tokens=8_192,
            default_response_tokens=2_000,
            tool_executor=ToolExecutor(
                default_tool_registry(
                    web_search=provider,
                    web_page_reader=reader,
                ),
                InMemoryAuditSink(),
            ),
        )

        events = tuple(service.events_for("Tell me some recent news about Iran."))

        self.assertEqual(provider.queries, ["Tell me some recent news about Iran."])
        self.assertEqual(len(model.requests), 1)
        self.assertIn(
            "untrusted_public_page_text",
            model.requests[0].messages[-1].content,
        )
        self.assertEqual(model.requests[0].tools, ())
        answer = "".join(event.text for event in events)
        self.assertIn("synthesized", answer)
        self.assertIn("https://example.test/current", answer)
        self.assertIn(
            "Earlier conversation and saved context were omitted from this "
            "request to leave room for tool results.",
            tuple(event.text for event in events),
        )

    def test_explicit_provider_command_searches_without_model_tool_choice(self) -> None:
        class AnsweringModel:
            def __init__(self) -> None:
                self.requests: list[ModelRequest] = []

            def generate(self, request: ModelRequest) -> ModelResponse:
                self.requests.append(request)
                return ModelResponse("A source-backed answer.")

        provider = SearchProvider()
        model = AnsweringModel()
        service = ConversationService(
            model,
            tool_executor=ToolExecutor(
                default_tool_registry(web_search=provider),
                InMemoryAuditSink(),
            ),
        )

        tuple(service.events_for("Only search Google Scholar for sleep research."))

        self.assertEqual(
            provider.queries,
            ["Only search Google Scholar for sleep research."],
        )
        self.assertEqual(model.requests[0].messages[-1].role, MessageRole.TOOL)


    def test_broad_news_phrases_trigger_automatic_page_reading(self) -> None:
        for prompt in (
            "Update me on current events today.",
            "Tell me some recent news about Iran.",
            "What are the latest updates on this story?",
        ):
            with self.subTest(prompt=prompt):
                self.assertTrue(_is_broad_current_events_request(prompt))

    def test_tool_reserve_scales_down_with_an_8k_context_window(self) -> None:
        model = SyntheticStreamingModel()
        service = ConversationService(
            model,
            context_window_tokens=8_192,
            default_response_tokens=400,
            tool_executor=ToolExecutor(
                default_tool_registry(
                    web_search=SearchProvider(),
                    web_page_reader=PublicWebPageReader(
                        fetcher=lambda _url, _timeout: (
                            "text/plain",
                            "utf-8",
                            b"Current public report.",
                        )
                    ),
                ),
                InMemoryAuditSink(),
            ),
        )

        events = tuple(service.events_for("Hello."))

        self.assertEqual(len(model.requests), 1)
        self.assertNotIn(
            "Earlier conversation and saved context were omitted from this "
            "request to leave room for tool results.",
            tuple(event.text for event in events),
        )

    def test_page_read_is_a_coordinator_enforced_terminal_tool_step(self) -> None:
        class ExtraToolModel:
            def __init__(self) -> None:
                self.requests: list[ModelRequest] = []

            def generate(self, request: ModelRequest) -> ModelResponse:
                self.requests.append(request)
                if request.messages[-1].role is MessageRole.USER:
                    return ModelResponse(
                        "",
                        (ModelToolCall.create("search_public_web", {}),),
                    )
                return ModelResponse(
                    "",
                    (
                        ModelToolCall.create(
                            "calculate",
                            {"operator": "add", "left": 1, "right": 1},
                        ),
                    ),
                )

        provider = SearchProvider()
        model = ExtraToolModel()
        service = ConversationService(
            model,
            tool_executor=ToolExecutor(
                default_tool_registry(
                    web_search=provider,
                    web_page_reader=PublicWebPageReader(
                        fetcher=lambda _url, _timeout: (
                            "text/plain",
                            "utf-8",
                            b"Current public report.",
                        )
                    ),
                ),
                InMemoryAuditSink(),
            ),
        )

        events = tuple(service.events_for("Update me on current events today."))

        self.assertEqual(len(model.requests), 1)
        self.assertEqual(model.requests[0].tools, ())
        self.assertIn(
            "No further tool requests are allowed after public page reading.",
            tuple(event.text for event in events),
        )

    def test_duplicate_web_search_is_stopped_after_first_attempt(self) -> None:
        class DuplicateSearchModel:
            def __init__(self) -> None:
                self.requests = 0

            def generate(self, request: ModelRequest) -> ModelResponse:
                self.requests += 1
                return ModelResponse(
                    "",
                    (
                        ModelToolCall.create(
                            "search_public_web",
                            {"query": "current public result"},
                        ),
                    ),
                )

        provider = SearchProvider()
        model = DuplicateSearchModel()
        service = ConversationService(
            model,
            tool_executor=ToolExecutor(
                default_tool_registry(web_search=provider),
                InMemoryAuditSink(),
            ),
        )

        events = tuple(service.events_for("Find the current public result."))

        self.assertEqual(provider.queries, ["Find the current public result."])
        self.assertEqual(model.requests, 2)
        self.assertTrue(any("already attempted" in event.text for event in events))
    def test_pre_response_memory_notice_precedes_model_and_skips_duplicate_queue(self) -> None:
        model = SyntheticStreamingModel()
        worker = RecordingPostResponseWorker()
        worker.capture_result = ("Memory updated: pet.",)
        service = ConversationService(model, post_response_worker=worker)

        events = tuple(service.events_for("Synthetic Scooby is my dog."))

        self.assertEqual(events[0].kind, ConversationEventKind.NOTICE)
        self.assertEqual(events[0].text, "Memory updated: pet.")
        self.assertEqual(events[1].kind, ConversationEventKind.ASSISTANT_CHUNK)
        self.assertEqual(worker.capture_calls, ["Synthetic Scooby is my dog."])
        self.assertEqual(worker.calls, 0)

    def test_private_request_uses_no_persistent_memory_or_suggestions(self) -> None:
        model = SyntheticStreamingModel()
        memory = RecordingMemoryHandler()
        context = RecordingContextProvider()
        worker = RecordingPostResponseWorker()
        service = ConversationService(
            model,
            memory_context_provider=context,
            explicit_memory_handler=memory,
            post_response_worker=worker,
        )

        tuple(
            service.events_for(
                "remember that this private statement is temporary",
                allow_persistent_memory=False,
            )
        )

        self.assertEqual(context.calls, 0)
        self.assertEqual(memory.calls, [])
        self.assertEqual(worker.calls, 0)
        self.assertEqual(len(model.requests), 1)

    def test_stream_is_sanitized_structured_and_limit_bounded(self) -> None:
        model = SyntheticStreamingModel()
        service = ConversationService(model)

        events = tuple(service.events_for("synthetic question", max_response_tokens=400))

        self.assertEqual(
            [event.kind for event in events],
            [
                ConversationEventKind.ASSISTANT_CHUNK,
                ConversationEventKind.ASSISTANT_CHUNK,
                ConversationEventKind.COMPLETED,
            ],
        )
        self.assertEqual(events[1].text, r"response\u202e")
        self.assertTrue(events[-1].limit_reached)
        self.assertEqual(model.requests[0].max_response_tokens, 400)
        self.assertEqual(model.requests[0].messages[-1].role, MessageRole.USER)

    def test_explicit_memory_never_reaches_model(self) -> None:
        model = SyntheticStreamingModel()
        memory = RecordingMemoryHandler()
        service = ConversationService(model, explicit_memory_handler=memory)

        events = tuple(service.events_for("remember that Luna likes blue toys"))

        self.assertEqual(events[0].text, "Synthetic memory saved.")
        self.assertEqual(memory.calls[0][0], "Luna likes blue toys")
        self.assertEqual(model.requests, [])

    def test_model_error_is_fixed_and_does_not_leak_raw_details(self) -> None:
        service = ConversationService(UnavailableModel())

        events = tuple(service.events_for("synthetic question"))

        self.assertEqual(len(events), 1)
        self.assertIn("Ollama is unavailable", events[0].text)
        self.assertNotIn("raw unavailable details", events[0].text)

    def test_parallel_request_is_refused_without_waiting(self) -> None:
        model = BlockingModel()
        service = ConversationService(model)
        first_events: list[object] = []
        first = Thread(
            target=lambda: first_events.extend(service.events_for("first")),
            daemon=True,
        )
        first.start()
        self.assertTrue(model.started.wait(timeout=1))

        second = tuple(service.events_for("second"))

        self.assertEqual(second[0].text, "A response is already being generated.")
        model.release.set()
        first.join(timeout=1)
        self.assertFalse(first.is_alive())
        self.assertTrue(first_events)

    def test_owner_cancellation_keeps_partial_text_out_of_memory_promotion(self) -> None:
        model = SyntheticStreamingModel()
        worker = RecordingPostResponseWorker()
        service = ConversationService(model, post_response_worker=worker)
        events = service.events_for("first private detail")

        first = next(events)
        service.cancel_active_response()
        remaining = tuple(events)

        self.assertEqual(first.kind, ConversationEventKind.ASSISTANT_CHUNK)
        self.assertEqual(remaining[-1].kind, ConversationEventKind.CANCELLED)
        self.assertEqual(worker.calls, 0)

        tuple(service.events_for("second question"))
        request_text = " ".join(
            message.content for message in model.requests[-1].messages
        )
        self.assertNotIn("first private detail", request_text)

    def test_failed_search_retries_once_and_emits_safe_code(self) -> None:
        class FailingSearch:
            def __init__(self) -> None:
                self.calls = 0

            def search(self, _query: str):
                self.calls += 1
                raise WebSearchError(
                    "private failure details",
                    WebSearchFailureCode.CONNECT,
                )

        provider = FailingSearch()
        service = ConversationService(
            SyntheticStreamingModel(),
            tool_executor=ToolExecutor(
                default_tool_registry(web_search=provider),
                InMemoryAuditSink(),
            ),
        )

        events = tuple(service.events_for("Update me on current events today."))

        self.assertEqual(provider.calls, 2)
        notices = [
            event.text
            for event in events
            if event.kind is ConversationEventKind.NOTICE
        ]
        self.assertTrue(any("Retrying once" in text for text in notices))
        self.assertTrue(any("WEB-CONNECT-01" in text for text in notices))
        self.assertFalse(any("private failure details" in text for text in notices))

    def test_disabled_explicit_provider_is_not_retried_or_called_connection_error(self) -> None:
        class DisabledSearch:
            def __init__(self) -> None:
                self.calls = 0

            def search(self, _query: str):
                self.calls += 1
                raise WebSearchError(
                    "private provider details",
                    WebSearchFailureCode.PROVIDER,
                )

        provider = DisabledSearch()
        service = ConversationService(
            SyntheticStreamingModel(),
            tool_executor=ToolExecutor(
                default_tool_registry(web_search=provider),
                InMemoryAuditSink(),
            ),
        )

        events = tuple(service.events_for("Only search Google Scholar for sleep."))

        self.assertEqual(provider.calls, 1)
        notices = [
            event.text
            for event in events
            if event.kind is ConversationEventKind.NOTICE
        ]
        self.assertTrue(any("disabled or unavailable" in text for text in notices))
        self.assertFalse(any("connecting" in text for text in notices))

    def test_replaced_chat_waits_for_prior_memory_before_model_request(self) -> None:
        model = SyntheticStreamingModel()
        worker = BlockingHandoffMemoryWorker()
        service = ConversationService(model, post_response_worker=worker)
        service.replace_history((), wait_for_memory=True)
        events: list[object] = []

        request = Thread(
            target=lambda: events.extend(service.events_for("new chat question")),
            daemon=True,
        )
        request.start()

        self.assertTrue(worker.wait_started.wait(timeout=1))
        self.assertEqual(model.requests, [])
        worker.release.set()
        request.join(timeout=1)
        self.assertFalse(request.is_alive())
        self.assertEqual(worker.wait_calls, 1)
        self.assertTrue(events)
        self.assertEqual(len(model.requests), 1)

    def test_close_waits_for_accepted_memory_before_worker_shutdown(self) -> None:
        worker = BlockingHandoffMemoryWorker()
        service = ConversationService(
            SyntheticStreamingModel(),
            post_response_worker=worker,
        )
        closer = Thread(target=service.close, daemon=True)

        closer.start()

        self.assertTrue(worker.wait_started.wait(timeout=1))
        self.assertFalse(worker.closed)
        worker.release.set()
        closer.join(timeout=1)
        self.assertFalse(closer.is_alive())
        self.assertTrue(worker.closed)

    def test_closed_session_rejects_new_work(self) -> None:
        service = ConversationService(
            SyntheticStreamingModel(),
            communication_style=CommunicationStyle("Be warm and concise."),
        )
        service.close()

        events = tuple(service.events_for("synthetic question"))

        self.assertEqual(service.communication_style, CommunicationStyle())
        self.assertEqual(events[0].text, "This assistant session is closed.")

    def test_invalid_ui_response_limit_is_refused_before_model_use(self) -> None:
        model = Mock(spec=LanguageModel)
        service = ConversationService(model)

        events = tuple(service.events_for("Hello", max_response_tokens=2_001))

        model.generate.assert_not_called()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].kind, ConversationEventKind.NOTICE)
        self.assertEqual(events[0].text, "The selected response limit is invalid.")


if __name__ == "__main__":
    unittest.main()
