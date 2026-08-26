"""UI-neutral bounded conversation orchestration for trusted interfaces."""

from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from threading import Lock
from typing import Protocol
from uuid import UUID, uuid4

from personal_assistant.config import ChatSettings
from personal_assistant.memory_context import MemoryContextError, MemoryContextProvider
from personal_assistant.model import (
    LanguageModel,
    MalformedModelResponseError,
    ModelError,
    ModelNotFoundError,
    ModelRequest,
    ModelUnavailableError,
    StreamingLanguageModel,
    response_instruction,
    validate_response_token_limit,
)
from personal_assistant.session_memory import (
    ConversationTurn,
    MessageTooLargeError,
    SessionConversationMemory,
)
from personal_assistant.terminal_output import sanitize_terminal_text


class ExplicitMemoryHandler(Protocol):
    def remember(self, content: str, correlation_id: UUID) -> str:
        """Store an explicit memory through a trusted deterministic boundary."""


class PostResponseWorker(Protocol):
    def submit(self, user_text: str, assistant_text: str) -> bool:
        """Queue one completed turn without blocking visible output."""

    def wait_until_idle(self, timeout_seconds: float = 15.0) -> bool:
        """Wait boundedly for previously accepted turns to finish."""

    def close(self) -> None:
        """Cancel future persistence before runtime secrets are released."""


class ConversationEventKind(StrEnum):
    ASSISTANT_CHUNK = "assistant_chunk"
    COMPLETED = "completed"
    NOTICE = "notice"


@dataclass(frozen=True)
class ConversationEvent:
    kind: ConversationEventKind
    text: str = ""
    limit_reached: bool = False


@dataclass(frozen=True)
class _PreparedTurn:
    request: ModelRequest
    user_text: str
    notices: tuple[str, ...]


class ConversationService:
    """Serialize chat requests and expose only sanitized display events."""

    def __init__(
        self,
        model: LanguageModel,
        settings: ChatSettings = ChatSettings(),
        *,
        context_window_tokens: int = 16_384,
        default_response_tokens: int = 400,
        memory_context_provider: MemoryContextProvider | None = None,
        explicit_memory_handler: ExplicitMemoryHandler | None = None,
        post_response_worker: PostResponseWorker | None = None,
    ) -> None:
        if not isinstance(model, LanguageModel):
            raise TypeError("Conversation service requires a language model.")
        self._model = model
        self._settings = settings
        self._context_window_tokens = context_window_tokens
        self._default_response_tokens = validate_response_token_limit(
            default_response_tokens
        )
        if context_window_tokens <= self._default_response_tokens:
            raise ValueError("The context window must leave room for model input.")
        self._memory_context_provider = memory_context_provider
        self._explicit_memory_handler = explicit_memory_handler
        self._post_response_worker = post_response_worker
        self._memory = SessionConversationMemory(settings.session_history_tokens)
        self._request_lock = Lock()
        self._lifecycle_lock = Lock()
        self._closed = False
        self._wait_for_memory_before_next_request = False

    def events_for(
        self,
        user_text: str,
        *,
        max_response_tokens: int | None = None,
        allow_persistent_memory: bool = True,
        conversation_recall_context: str | None = None,
    ) -> Iterator[ConversationEvent]:
        """Yield sanitized events for one request without concurrent generation."""

        if not isinstance(user_text, str):
            yield ConversationEvent(
                ConversationEventKind.NOTICE,
                "A message must be plain text.",
            )
            return
        if not self._request_lock.acquire(blocking=False):
            yield ConversationEvent(
                ConversationEventKind.NOTICE,
                "A response is already being generated.",
            )
            return
        try:
            with self._lifecycle_lock:
                closed = self._closed
            if closed:
                yield ConversationEvent(
                    ConversationEventKind.NOTICE,
                    "This assistant session is closed.",
                )
                return
            if (
                allow_persistent_memory
                and self._wait_for_memory_before_next_request
            ):
                self._wait_for_memory_before_next_request = False
                if not self._wait_for_post_response_memory():
                    yield ConversationEvent(
                        ConversationEventKind.NOTICE,
                        "Recent memory processing is still finishing; the newest "
                        "facts may not be available yet.",
                    )
            explicit_result = (
                self._handle_explicit_memory(user_text)
                if allow_persistent_memory
                else None
            )
            if explicit_result is not None:
                yield ConversationEvent(ConversationEventKind.NOTICE, explicit_result)
                return
            prepared = self._prepare_turn(
                user_text,
                max_response_tokens,
                allow_persistent_memory=allow_persistent_memory,
                conversation_recall_context=conversation_recall_context,
            )
            if isinstance(prepared, str):
                if prepared:
                    yield ConversationEvent(ConversationEventKind.NOTICE, prepared)
                return
            for notice in prepared.notices:
                yield ConversationEvent(ConversationEventKind.NOTICE, notice)
            response_pieces: list[str] = []
            limit_reached = False
            try:
                if isinstance(self._model, StreamingLanguageModel):
                    for chunk in self._model.stream_generate(prepared.request):
                        safe_text = sanitize_terminal_text(chunk.text)
                        response_pieces.append(safe_text)
                        limit_reached = limit_reached or chunk.done_reason == "length"
                        if safe_text:
                            yield ConversationEvent(
                                ConversationEventKind.ASSISTANT_CHUNK,
                                safe_text,
                            )
                else:
                    response = self._model.generate(prepared.request)
                    safe_text = sanitize_terminal_text(response.text)
                    response_pieces.append(safe_text)
                    if safe_text:
                        yield ConversationEvent(
                            ConversationEventKind.ASSISTANT_CHUNK,
                            safe_text,
                        )
            except ModelError as error:
                yield ConversationEvent(
                    ConversationEventKind.NOTICE,
                    self._friendly_model_error(error),
                )
                return
            response_text = "".join(response_pieces)
            with self._lifecycle_lock:
                closed = self._closed
            if not closed:
                self._memory.add_turn(prepared.user_text, response_text)
                if allow_persistent_memory and self._post_response_worker is not None:
                    self._post_response_worker.submit(
                        prepared.user_text,
                        response_text,
                    )
            yield ConversationEvent(
                ConversationEventKind.COMPLETED,
                limit_reached=limit_reached,
            )
        finally:
            self._request_lock.release()

    def close(self) -> None:
        """Stop accepting work and close optional background memory analysis."""

        with self._lifecycle_lock:
            if self._closed:
                return
            self._closed = True
        if self._post_response_worker is not None:
            self._wait_for_post_response_memory()
            self._post_response_worker.close()

    def replace_history(
        self,
        turns: tuple[ConversationTurn, ...],
        *,
        wait_for_memory: bool = False,
    ) -> None:
        """Load bounded complete turns while no request is in progress."""

        if not isinstance(wait_for_memory, bool):
            raise TypeError("Memory handoff setting must be a boolean.")
        if not self._request_lock.acquire(blocking=False):
            raise RuntimeError("Conversation history cannot change during a request.")
        try:
            with self._lifecycle_lock:
                if self._closed:
                    raise RuntimeError("This conversation service is closed.")
            self._memory.replace_turns(turns)
            self._wait_for_memory_before_next_request = wait_for_memory
        finally:
            self._request_lock.release()

    def _wait_for_post_response_memory(self) -> bool:
        worker = self._post_response_worker
        if worker is None:
            return True
        waiter = getattr(worker, "wait_until_idle", None)
        if not callable(waiter):
            return True
        try:
            return bool(waiter(15.0))
        except Exception:
            return False

    def _handle_explicit_memory(self, prompt: str) -> str | None:
        if self._explicit_memory_handler is None:
            return None
        stripped = prompt.strip()
        lowered = stripped.casefold()
        content: str | None = None
        if lowered == "/remember":
            content = ""
        elif lowered.startswith("/remember "):
            content = stripped[len("/remember") :].strip()
        elif lowered.startswith("remember that "):
            content = stripped[len("remember that ") :].strip()
        if content is None:
            return None
        return self._explicit_memory_handler.remember(content, uuid4())

    def _prepare_turn(
        self,
        user_text: str,
        requested_response_tokens: int | None,
        *,
        allow_persistent_memory: bool = True,
        conversation_recall_context: str | None = None,
    ) -> _PreparedTurn | str:
        stripped = user_text.strip()
        if not stripped:
            return ""
        if conversation_recall_context is not None and (
            not isinstance(conversation_recall_context, str)
            or len(conversation_recall_context) > 8_192
        ):
            return "Saved conversation context is invalid."
        try:
            response_limit = (
                self._default_response_tokens
                if requested_response_tokens is None
                else validate_response_token_limit(requested_response_tokens)
            )
        except (TypeError, ValueError):
            return "The selected response limit is invalid."
        if response_limit > self._settings.maximum_response_tokens:
            return (
                "The response limit exceeds the configured maximum of "
                f"{self._settings.maximum_response_tokens:,} tokens."
            )
        input_token_limit = self._context_window_tokens - response_limit
        base_system_text = response_instruction(response_limit)
        persistent_context: str | None = None
        notices: list[str] = []
        if allow_persistent_memory and self._memory_context_provider is not None:
            try:
                persistent_context = self._memory_context_provider.context_for(
                    user_text,
                    uuid4(),
                )
            except MemoryContextError:
                notices.append(
                    "Persistent memory is unavailable for this request; "
                    "continuing without it."
                )
        system_text = (
            base_system_text
            + (persistent_context or "")
            + (conversation_recall_context or "")
        )
        try:
            messages = self._memory.messages_for_request(
                system_text=system_text,
                user_text=user_text,
                input_token_limit=input_token_limit,
            )
        except MessageTooLargeError:
            if persistent_context is not None:
                try:
                    messages = self._memory.messages_for_request(
                        system_text=(
                            base_system_text + (conversation_recall_context or "")
                        ),
                        user_text=user_text,
                        input_token_limit=input_token_limit,
                    )
                except MessageTooLargeError:
                    pass
                else:
                    notices.append(
                        "Relevant persistent memory did not fit this request; "
                        "continuing without it."
                    )
                    return _PreparedTurn(
                        ModelRequest(messages, response_limit),
                        user_text,
                        tuple(notices),
                    )
            if conversation_recall_context is not None:
                try:
                    messages = self._memory.messages_for_request(
                        system_text=base_system_text,
                        user_text=user_text,
                        input_token_limit=input_token_limit,
                    )
                except MessageTooLargeError:
                    pass
                else:
                    notices.append(
                        "Saved conversation excerpts did not fit this request; "
                        "continuing without them."
                    )
                    return _PreparedTurn(
                        ModelRequest(messages, response_limit),
                        user_text,
                        tuple(notices),
                    )
            return (
                "That message is too large for the current context window. "
                "Shorten it and try again."
            )
        return _PreparedTurn(
            ModelRequest(messages, response_limit),
            user_text,
            tuple(notices),
        )

    @staticmethod
    def _friendly_model_error(error: ModelError) -> str:
        if isinstance(error, ModelUnavailableError):
            return "Ollama is unavailable. Check that it is installed and try again."
        if isinstance(error, ModelNotFoundError):
            return "The configured local model is not installed."
        if isinstance(error, MalformedModelResponseError):
            return "Ollama returned an unreadable response. Please try again."
        return "The local model request failed. Please try again."
