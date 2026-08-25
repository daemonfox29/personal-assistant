"""A minimal local command-line chat interface."""

from collections.abc import Callable
from typing import Protocol
from uuid import UUID, uuid4

from personal_assistant.config import ChatSettings
from personal_assistant.memory_context import (
    MemoryContextError,
    MemoryContextProvider,
)
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
    MessageTooLargeError,
    SessionConversationMemory,
)
from personal_assistant.terminal_output import sanitize_terminal_text


InputReader = Callable[[str], str]
OutputWriter = Callable[[str], None]
ChunkWriter = Callable[[str], None]
PreparedRequest = tuple[ModelRequest, str]
EXIT_COMMANDS = frozenset({"exit", "quit"})
LONG_RESPONSE_COMMAND = "/long"
MAX_RESPONSE_COMMAND = "/max"
CUSTOM_LIMIT_COMMAND = "/limit"
REMEMBER_COMMAND = "/remember"


class ExplicitMemoryHandler(Protocol):
    """Trusted local handler invoked before text can reach the model."""

    def remember(self, content: str, correlation_id: UUID) -> str:
        """Store an explicit instruction and return a fixed outcome."""


class PostResponseWorker(Protocol):
    """Receive completed turns only after their visible response finishes."""

    def submit(self, user_text: str, assistant_text: str) -> bool:
        """Queue a turn without blocking the conversation."""

    def close(self) -> None:
        """Cancel future persistence before runtime secrets are released."""


def _write_chunk(text: str) -> None:
    """Display text immediately without inserting a line after every chunk."""

    print(text, end="", flush=True)


class ChatSession:
    """Run a text conversation using one language-model implementation."""

    def __init__(
        self,
        model: LanguageModel,
        settings: ChatSettings = ChatSettings(),
        *,
        context_window_tokens: int = 16384,
        default_response_tokens: int = 400,
        read_input: InputReader = input,
        write_output: OutputWriter = print,
        write_chunk: ChunkWriter = _write_chunk,
        memory_context_provider: MemoryContextProvider | None = None,
        explicit_memory_handler: ExplicitMemoryHandler | None = None,
        post_response_worker: PostResponseWorker | None = None,
    ) -> None:
        self._model = model
        self._read_input = read_input
        self._write_output = write_output
        self._write_chunk = write_chunk
        self._memory_context_provider = memory_context_provider
        self._explicit_memory_handler = explicit_memory_handler
        self._post_response_worker = post_response_worker
        self._settings = settings
        self._context_window_tokens = context_window_tokens
        self._default_response_tokens = validate_response_token_limit(
            default_response_tokens
        )
        if context_window_tokens <= self._default_response_tokens:
            raise ValueError(
                "The context window must leave room for model input."
            )
        self._memory = SessionConversationMemory(
            settings.session_history_tokens
        )

    def run(self) -> None:
        """Continue chatting until the user exits or closes the terminal."""

        self._write_output(
            "Type 'quit' or 'exit' to close. Use '/long <question>' for a "
            f"{self._settings.long_response_tokens:,}-token answer, "
            f"'/max <question>' for {self._settings.maximum_response_tokens:,} "
            "tokens, or '/limit <1-"
            f"{self._settings.maximum_response_tokens}> <question>' for a "
            "custom limit."
        )

        while True:
            try:
                prompt = self._read_input("You: ")
            except EOFError:
                self._close_background_work()
                self._say_goodbye()
                return
            except KeyboardInterrupt:
                self._close_background_work()
                self._write_output("\nInterrupted. Goodbye.")
                return

            if prompt.strip().lower() in EXIT_COMMANDS:
                self._close_background_work()
                self._say_goodbye()
                return

            if self._handle_explicit_memory(prompt):
                continue

            prepared_request = self._request_from_prompt(prompt)
            if prepared_request is None:
                continue
            request, user_text = prepared_request

            try:
                if isinstance(self._model, StreamingLanguageModel):
                    response_text = self._stream_response(request)
                else:
                    response = self._model.generate(request)
                    response_text = sanitize_terminal_text(response.text)
                    self._write_output(f"Assistant: {response_text}")
            except KeyboardInterrupt:
                self._close_background_work()
                self._write_output("\nRequest cancelled. Goodbye.")
                return
            except ModelError as error:
                if isinstance(self._model, StreamingLanguageModel):
                    self._write_chunk("\n")
                self._write_output(self._friendly_model_error(error))
                continue

            self._memory.add_turn(user_text, response_text)
            if self._post_response_worker is not None:
                self._post_response_worker.submit(user_text, response_text)

    def _close_background_work(self) -> None:
        if self._post_response_worker is not None:
            self._post_response_worker.close()

    def _handle_explicit_memory(self, prompt: str) -> bool:
        if self._explicit_memory_handler is None:
            return False
        stripped = prompt.strip()
        lowered = stripped.casefold()
        content: str | None = None
        if lowered == REMEMBER_COMMAND:
            content = ""
        elif lowered.startswith(f"{REMEMBER_COMMAND} "):
            content = stripped[len(REMEMBER_COMMAND) :].strip()
        elif lowered.startswith("remember that "):
            content = stripped[len("remember that ") :].strip()
        if content is None:
            return False
        result = self._explicit_memory_handler.remember(content, uuid4())
        self._write_output(result)
        return True

    def _stream_response(self, request: ModelRequest) -> str:
        self._write_chunk("Assistant: ")
        limit_reached = False
        response_pieces: list[str] = []
        for chunk in self._model.stream_generate(request):
            safe_text = sanitize_terminal_text(chunk.text)
            self._write_chunk(safe_text)
            response_pieces.append(safe_text)
            limit_reached = limit_reached or chunk.done_reason == "length"
        self._write_chunk("\n")
        if limit_reached:
            self._write_output(
                "[Response stopped at its token limit. Use '/long <question>' "
                "or '/max <question>' for a longer answer.]"
            )
        return "".join(response_pieces)

    def _friendly_model_error(self, error: ModelError) -> str:
        if isinstance(error, ModelUnavailableError):
            return "Ollama is unavailable. Check that it is installed and try again."
        if isinstance(error, ModelNotFoundError):
            return "The configured local model is not installed."
        if isinstance(error, MalformedModelResponseError):
            return "Ollama returned an unreadable response. Please try again."
        return "The local model request failed. Please try again."

    def _long_request(
        self,
        separator: str,
        remaining_prompt: str,
    ) -> PreparedRequest | None:
        if not separator or not remaining_prompt.strip():
            self._write_output("Usage: /long <question>")
            return None

        return self._prepared_request(
            remaining_prompt.strip(),
            max_response_tokens=self._settings.long_response_tokens,
        )

    def _max_request(
        self,
        separator: str,
        remaining_prompt: str,
    ) -> PreparedRequest | None:
        if not separator or not remaining_prompt.strip():
            self._write_output("Usage: /max <question>")
            return None

        return self._prepared_request(
            remaining_prompt.strip(),
            max_response_tokens=self._settings.maximum_response_tokens,
        )

    def _custom_limit_request(
        self,
        separator: str,
        remaining_prompt: str,
    ) -> PreparedRequest | None:
        if not separator:
            self._write_output(
                "Usage: /limit <1-"
                f"{self._settings.maximum_response_tokens}> <question>"
            )
            return None

        token_limit, question_separator, question = remaining_prompt.partition(" ")
        if not question_separator or not question.strip():
            self._write_output(
                "Usage: /limit <1-"
                f"{self._settings.maximum_response_tokens}> <question>"
            )
            return None

        try:
            response_limit = int(token_limit)
        except ValueError:
            self._write_output("The /limit token limit must be a whole number.")
            return None

        if not 1 <= response_limit <= self._settings.maximum_response_tokens:
            self._write_output(
                "The /limit token limit must be between 1 and "
                f"{self._settings.maximum_response_tokens}."
            )
            return None

        return self._prepared_request(
            question.strip(),
            max_response_tokens=response_limit,
        )

    def _request_from_prompt(self, prompt: str) -> PreparedRequest | None:
        """Return a request, or ignore blank input and incomplete commands."""

        stripped_prompt = prompt.strip()
        if not stripped_prompt:
            return None

        command, separator, remaining_prompt = stripped_prompt.partition(" ")
        if command.lower() not in {
            LONG_RESPONSE_COMMAND,
            MAX_RESPONSE_COMMAND,
            CUSTOM_LIMIT_COMMAND,
        }:
            return self._prepared_request(prompt)

        if command.lower() == LONG_RESPONSE_COMMAND:
            return self._long_request(separator, remaining_prompt)
        if command.lower() == MAX_RESPONSE_COMMAND:
            return self._max_request(separator, remaining_prompt)
        return self._custom_limit_request(separator, remaining_prompt)

    def _prepared_request(
        self,
        user_text: str,
        *,
        max_response_tokens: int | None = None,
    ) -> PreparedRequest | None:
        response_limit = (
            self._default_response_tokens
            if max_response_tokens is None
            else validate_response_token_limit(max_response_tokens)
        )
        input_token_limit = self._context_window_tokens - response_limit

        base_system_text = response_instruction(response_limit)
        persistent_context: str | None = None
        if self._memory_context_provider is not None:
            try:
                persistent_context = self._memory_context_provider.context_for(
                    user_text, uuid4()
                )
            except MemoryContextError:
                self._write_output(
                    "Persistent memory is unavailable for this request; "
                    "continuing without it."
                )

        system_text = base_system_text + (persistent_context or "")

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
                        system_text=base_system_text,
                        user_text=user_text,
                        input_token_limit=input_token_limit,
                    )
                except MessageTooLargeError:
                    pass
                else:
                    self._write_output(
                        "Relevant persistent memory did not fit this request; "
                        "continuing without it."
                    )
                    return (
                        ModelRequest(
                            messages=messages,
                            max_response_tokens=response_limit,
                        ),
                        user_text,
                    )
            self._write_output(
                "That message is too large for the current context window. "
                "Shorten it and try again."
            )
            return None

        return (
            ModelRequest(
                messages=messages,
                max_response_tokens=response_limit,
            ),
            user_text,
        )

    def _say_goodbye(self) -> None:
        self._write_output("Goodbye.")
