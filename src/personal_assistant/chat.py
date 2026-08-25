"""Minimal command-line presentation over the shared conversation service."""

from collections.abc import Callable

from personal_assistant.config import ChatSettings
from personal_assistant.conversation import (
    ConversationEventKind,
    ConversationService,
    ExplicitMemoryHandler,
    PostResponseWorker,
)
from personal_assistant.memory_context import MemoryContextProvider
from personal_assistant.model import LanguageModel, StreamingLanguageModel


InputReader = Callable[[str], str]
OutputWriter = Callable[[str], None]
ChunkWriter = Callable[[str], None]
PreparedPrompt = tuple[str, int | None]
EXIT_COMMANDS = frozenset({"exit", "quit"})
LONG_RESPONSE_COMMAND = "/long"
MAX_RESPONSE_COMMAND = "/max"
CUSTOM_LIMIT_COMMAND = "/limit"


def _write_chunk(text: str) -> None:
    """Display text immediately without inserting a line after every chunk."""

    print(text, end="", flush=True)


class ChatSession:
    """Run the recovery CLI through the same bounded engine as the native UI."""

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
        self._settings = settings
        self._read_input = read_input
        self._write_output = write_output
        self._write_chunk = write_chunk
        self._streaming = isinstance(model, StreamingLanguageModel)
        self._conversation = ConversationService(
            model,
            settings,
            context_window_tokens=context_window_tokens,
            default_response_tokens=default_response_tokens,
            memory_context_provider=memory_context_provider,
            explicit_memory_handler=explicit_memory_handler,
            post_response_worker=post_response_worker,
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
                self._close_and_say_goodbye()
                return
            except KeyboardInterrupt:
                self._conversation.close()
                self._write_output("\nInterrupted. Goodbye.")
                return

            if prompt.strip().casefold() in EXIT_COMMANDS:
                self._close_and_say_goodbye()
                return
            prepared = self._prepared_prompt(prompt)
            if prepared is None:
                continue
            user_text, response_limit = prepared
            try:
                self._display_events(user_text, response_limit)
            except KeyboardInterrupt:
                self._conversation.close()
                self._write_output("\nRequest cancelled. Goodbye.")
                return

    def _display_events(
        self,
        user_text: str,
        response_limit: int | None,
    ) -> None:
        response_pieces: list[str] = []
        stream_started = False
        for event in self._conversation.events_for(
            user_text,
            max_response_tokens=response_limit,
        ):
            if event.kind is ConversationEventKind.ASSISTANT_CHUNK:
                if self._streaming:
                    if not stream_started:
                        self._write_chunk("Assistant: ")
                        stream_started = True
                    self._write_chunk(event.text)
                else:
                    response_pieces.append(event.text)
            elif event.kind is ConversationEventKind.NOTICE:
                if stream_started:
                    self._write_chunk("\n")
                    stream_started = False
                self._write_output(event.text)
            elif event.kind is ConversationEventKind.COMPLETED:
                if self._streaming:
                    if stream_started:
                        self._write_chunk("\n")
                        stream_started = False
                else:
                    self._write_output(f"Assistant: {''.join(response_pieces)}")
                if event.limit_reached:
                    self._write_output(
                        "[Response stopped at its token limit. Use '/long "
                        "<question>' or '/max <question>' for a longer answer.]"
                    )

    def _prepared_prompt(self, prompt: str) -> PreparedPrompt | None:
        stripped = prompt.strip()
        if not stripped:
            return None
        command, separator, remaining = stripped.partition(" ")
        lowered = command.casefold()
        if lowered not in {
            LONG_RESPONSE_COMMAND,
            MAX_RESPONSE_COMMAND,
            CUSTOM_LIMIT_COMMAND,
        }:
            return prompt, None
        if lowered == LONG_RESPONSE_COMMAND:
            if not separator or not remaining.strip():
                self._write_output("Usage: /long <question>")
                return None
            return remaining.strip(), self._settings.long_response_tokens
        if lowered == MAX_RESPONSE_COMMAND:
            if not separator or not remaining.strip():
                self._write_output("Usage: /max <question>")
                return None
            return remaining.strip(), self._settings.maximum_response_tokens
        return self._custom_limit_prompt(separator, remaining)

    def _custom_limit_prompt(
        self,
        separator: str,
        remaining: str,
    ) -> PreparedPrompt | None:
        usage = (
            "Usage: /limit <1-"
            f"{self._settings.maximum_response_tokens}> <question>"
        )
        if not separator:
            self._write_output(usage)
            return None
        token_limit, question_separator, question = remaining.partition(" ")
        if not question_separator or not question.strip():
            self._write_output(usage)
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
        return question.strip(), response_limit

    def _close_and_say_goodbye(self) -> None:
        self._conversation.close()
        self._write_output("Goodbye.")
