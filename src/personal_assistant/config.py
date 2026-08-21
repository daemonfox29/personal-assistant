"""Shared, non-secret settings for the Personal Assistant."""

from collections.abc import Mapping
from dataclasses import dataclass, field
import os


@dataclass(frozen=True)
class OllamaSettings:
    """Connection and resource settings for the local Ollama adapter."""

    base_url: str = "http://127.0.0.1:11434"
    model_name: str = "qwen3:14b"
    context_tokens: int = 4096
    max_response_tokens: int = 400
    keep_alive: str = "5m"
    timeout_seconds: float = 120.0


@dataclass(frozen=True)
class ChatSettings:
    """Interaction settings for the local command-line chat."""

    session_history_characters: int = 6000
    long_response_tokens: int = 1200
    maximum_response_tokens: int = 2000


@dataclass(frozen=True)
class AppSettings:
    """All shared application settings."""

    ollama: OllamaSettings = field(default_factory=OllamaSettings)
    chat: ChatSettings = field(default_factory=ChatSettings)


def load_settings(
    environment: Mapping[str, str] | None = None,
) -> AppSettings:
    """Load safe optional environment overrides for this local machine."""

    if environment is None:
        environment = os.environ
    defaults = AppSettings()

    chat_settings = ChatSettings(
        session_history_characters=_positive_integer(
            environment,
            "PERSONAL_ASSISTANT_HISTORY_CHARACTERS",
            defaults.chat.session_history_characters,
        ),
        long_response_tokens=_positive_integer(
            environment,
            "PERSONAL_ASSISTANT_LONG_RESPONSE_TOKENS",
            defaults.chat.long_response_tokens,
        ),
        maximum_response_tokens=_positive_integer(
            environment,
            "PERSONAL_ASSISTANT_MAX_RESPONSE_TOKENS",
            defaults.chat.maximum_response_tokens,
        ),
    )
    if chat_settings.long_response_tokens > chat_settings.maximum_response_tokens:
        raise ValueError(
            "PERSONAL_ASSISTANT_LONG_RESPONSE_TOKENS cannot exceed "
            "PERSONAL_ASSISTANT_MAX_RESPONSE_TOKENS."
        )

    return AppSettings(
        ollama=OllamaSettings(
            base_url=environment.get(
                "PERSONAL_ASSISTANT_OLLAMA_URL",
                defaults.ollama.base_url,
            ),
            model_name=environment.get(
                "PERSONAL_ASSISTANT_MODEL_NAME",
                defaults.ollama.model_name,
            ),
            context_tokens=_positive_integer(
                environment,
                "PERSONAL_ASSISTANT_CONTEXT_TOKENS",
                defaults.ollama.context_tokens,
            ),
            max_response_tokens=_positive_integer(
                environment,
                "PERSONAL_ASSISTANT_RESPONSE_TOKENS",
                defaults.ollama.max_response_tokens,
            ),
            keep_alive=environment.get(
                "PERSONAL_ASSISTANT_KEEP_ALIVE",
                defaults.ollama.keep_alive,
            ),
            timeout_seconds=defaults.ollama.timeout_seconds,
        ),
        chat=chat_settings,
    )


def _positive_integer(
    environment: Mapping[str, str],
    name: str,
    default: int,
) -> int:
    value = environment.get(name)
    if value is None:
        return default

    try:
        integer_value = int(value)
    except ValueError as error:
        raise ValueError(f"{name} must be a whole number.") from error

    if integer_value <= 0:
        raise ValueError(f"{name} must be greater than zero.")

    return integer_value
