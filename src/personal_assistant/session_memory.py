"""Token-bounded structured conversation context for one chat session."""

from dataclasses import dataclass

from personal_assistant.model import MessageRole, ModelMessage


MESSAGE_OVERHEAD_TOKENS = 8
REQUEST_OVERHEAD_TOKENS = 32


class MessageTooLargeError(ValueError):
    """Raised when the current request cannot fit without conversation history."""


def conservative_token_count(text: str) -> int:
    """Return a safe model-independent upper bound for ordinary text tokens."""

    return len(text.encode("utf-8"))


def message_token_count(message: ModelMessage) -> int:
    """Count conservative content tokens plus role/framing overhead."""

    return conservative_token_count(message.content) + MESSAGE_OVERHEAD_TOKENS


@dataclass(frozen=True)
class ConversationTurn:
    """One completed user-and-assistant exchange."""

    user_text: str
    assistant_text: str

    def messages(self) -> tuple[ModelMessage, ModelMessage]:
        return (
            ModelMessage(MessageRole.USER, self.user_text),
            ModelMessage(MessageRole.ASSISTANT, self.assistant_text),
        )

    def token_count(self) -> int:
        return sum(message_token_count(message) for message in self.messages())


class SessionConversationMemory:
    """Keep bounded, complete conversation turns in RAM only."""

    def __init__(self, token_limit: int) -> None:
        if token_limit <= 0:
            raise ValueError("The session history limit must be greater than zero.")

        self._token_limit = token_limit
        self._stored_tokens = 0
        self._turns: list[ConversationTurn] = []

    def add_turn(self, user_text: str, assistant_text: str) -> None:
        """Remember a completed exchange without exceeding the RAM budget."""

        turn = ConversationTurn(user_text, assistant_text)
        turn_tokens = turn.token_count()

        if turn_tokens > self._token_limit:
            self._turns.clear()
            self._stored_tokens = 0
            return

        self._turns.append(turn)
        self._stored_tokens += turn_tokens

        while self._stored_tokens > self._token_limit:
            removed_turn = self._turns.pop(0)
            self._stored_tokens -= removed_turn.token_count()

    def messages_for_request(
        self,
        *,
        system_text: str,
        user_text: str,
        input_token_limit: int,
    ) -> tuple[ModelMessage, ...]:
        """Return complete recent turns that fit with system and user messages."""

        system_message = ModelMessage(MessageRole.SYSTEM, system_text)
        user_message = ModelMessage(MessageRole.USER, user_text)
        required_tokens = (
            REQUEST_OVERHEAD_TOKENS
            + message_token_count(system_message)
            + message_token_count(user_message)
        )

        if required_tokens > input_token_limit:
            raise MessageTooLargeError(
                "The system instruction and current message exceed the input budget."
            )

        selected_turns: list[ConversationTurn] = []
        selected_tokens = required_tokens

        for turn in reversed(self._turns):
            turn_tokens = turn.token_count()
            if selected_tokens + turn_tokens > input_token_limit:
                break
            selected_turns.append(turn)
            selected_tokens += turn_tokens

        messages: list[ModelMessage] = [system_message]
        for turn in reversed(selected_turns):
            messages.extend(turn.messages())
        messages.append(user_message)
        return tuple(messages)
