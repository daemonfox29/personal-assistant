"""Temporary in-memory conversation context for one chat session."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ConversationTurn:
    """One completed user-and-assistant exchange."""

    user_text: str
    assistant_text: str


class SessionConversationMemory:
    """Keep recent conversation context in RAM and never write it to disk."""

    def __init__(self, character_limit: int) -> None:
        if character_limit <= 0:
            raise ValueError("The session history limit must be greater than zero.")

        self._character_limit = character_limit
        self._turns: list[ConversationTurn] = []

    def add_turn(self, user_text: str, assistant_text: str) -> None:
        """Remember a completed exchange for the rest of this session only."""

        self._turns.append(
            ConversationTurn(
                user_text=user_text,
                assistant_text=assistant_text,
            )
        )

    def prompt_with_history(self, user_text: str) -> str:
        """Add the most recent conversation turns before a new user message."""

        history = self._recent_history()
        if not history:
            return user_text

        return (
            "Recent conversation context:\n"
            f"{history}\n"
            "Current user message:\n"
            f"{user_text}"
        )

    def _recent_history(self) -> str:
        selected_turns: list[str] = []
        selected_characters = 0

        for turn in reversed(self._turns):
            formatted_turn = (
                f"User: {turn.user_text}\n"
                f"Assistant: {turn.assistant_text}\n"
            )
            remaining_characters = self._character_limit - selected_characters
            if remaining_characters <= 0:
                break

            if len(formatted_turn) <= remaining_characters:
                selected_turns.append(formatted_turn)
                selected_characters += len(formatted_turn)
                continue

            selected_turns.append(
                "[Earlier context was shortened]\n"
                + formatted_turn[-remaining_characters:]
            )
            break

        return "".join(reversed(selected_turns))
