"""UI-neutral conversation-service boundary tests."""

from threading import Event, Thread
import unittest
from unittest.mock import Mock
from uuid import UUID

from personal_assistant.assistant_preferences import CommunicationStyle
from personal_assistant.conversation import (
    ConversationEventKind,
    ConversationService,
)
from personal_assistant.model import (
    LanguageModel,
    MessageRole,
    ModelRequest,
    ModelResponse,
    ModelStreamChunk,
    ModelUnavailableError,
)


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
