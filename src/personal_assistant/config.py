"""Shared, non-secret settings for the Personal Assistant."""

from collections.abc import Mapping
from dataclasses import dataclass, field
import os
from pathlib import Path

from personal_assistant.local_http import validate_loopback_http_url
from personal_assistant.model import validate_response_token_limit


@dataclass(frozen=True)
class OllamaSettings:
    """Connection and resource settings for the local Ollama adapter."""

    base_url: str = "http://127.0.0.1:11434"
    model_name: str = "qwen3:14b"
    context_tokens: int = 16384
    max_response_tokens: int = 400
    keep_alive: str = "5m"
    timeout_seconds: float = 120.0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "base_url",
            validate_loopback_http_url(self.base_url, base_url=True),
        )
        validate_response_token_limit(self.max_response_tokens)


@dataclass(frozen=True)
class ChatSettings:
    """Interaction settings for the local command-line chat."""

    session_history_tokens: int = 6000
    long_response_tokens: int = 1200
    maximum_response_tokens: int = 2000

    def __post_init__(self) -> None:
        validate_response_token_limit(self.long_response_tokens)
        validate_response_token_limit(self.maximum_response_tokens)
        if self.long_response_tokens > self.maximum_response_tokens:
            raise ValueError(
                "The long response limit cannot exceed the maximum response limit."
            )


@dataclass(frozen=True)
class MemorySettings:
    """Machine-local paths and bounded persistent-memory runtime choices."""

    enabled: bool = True
    data_directory: Path = field(
        default_factory=lambda: Path.home() / ".personal-assistant"
    )
    backup_directory: Path | None = None
    context_tokens: int = 2_000
    automatic_suggestions: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool) or not isinstance(
            self.automatic_suggestions, bool
        ):
            raise ValueError("Memory enablement settings must be true or false.")
        if not isinstance(
            self.data_directory, Path
        ) or not self.data_directory.is_absolute():
            raise ValueError("Memory data directory must be explicit and absolute.")
        if self.data_directory.name in {"", ".", ".."}:
            raise ValueError("Memory data directory is invalid.")
        if self.backup_directory is not None and (
            not isinstance(self.backup_directory, Path)
            or not self.backup_directory.is_absolute()
        ):
            raise ValueError("Memory backup directory must be explicit and absolute.")
        if (
            isinstance(self.context_tokens, bool)
            or not isinstance(self.context_tokens, int)
            or not 1 <= self.context_tokens <= 2_500
        ):
            raise ValueError("Memory context token limit is outside its safe range.")


@dataclass(frozen=True)
class AppSettings:
    """All shared application settings."""

    ollama: OllamaSettings = field(default_factory=OllamaSettings)
    chat: ChatSettings = field(default_factory=ChatSettings)
    memory: MemorySettings = field(default_factory=MemorySettings)

    def __post_init__(self) -> None:
        if self.ollama.max_response_tokens > self.chat.maximum_response_tokens:
            raise ValueError(
                "The default response limit cannot exceed the maximum response "
                "limit."
            )


def load_settings(
    environment: Mapping[str, str] | None = None,
) -> AppSettings:
    """Load safe optional environment overrides for this local machine."""

    if environment is None:
        environment = os.environ
    defaults = AppSettings()

    chat_settings = ChatSettings(
        session_history_tokens=_positive_integer(
            environment,
            "PERSONAL_ASSISTANT_HISTORY_TOKENS",
            defaults.chat.session_history_tokens,
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
        memory=MemorySettings(
            enabled=_boolean(
                environment,
                "PERSONAL_ASSISTANT_MEMORY_ENABLED",
                defaults.memory.enabled,
            ),
            data_directory=_absolute_path(
                environment,
                "PERSONAL_ASSISTANT_DATA_DIR",
                defaults.memory.data_directory,
            ),
            backup_directory=_optional_absolute_path(
                environment,
                "PERSONAL_ASSISTANT_BACKUP_DIR",
            ),
            context_tokens=_positive_integer(
                environment,
                "PERSONAL_ASSISTANT_MEMORY_TOKENS",
                defaults.memory.context_tokens,
            ),
            automatic_suggestions=_boolean(
                environment,
                "PERSONAL_ASSISTANT_AUTOMATIC_MEMORY",
                defaults.memory.automatic_suggestions,
            ),
        ),
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


def _boolean(
    environment: Mapping[str, str],
    name: str,
    default: bool,
) -> bool:
    value = environment.get(name)
    if value is None:
        return default
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false.")


def _absolute_path(
    environment: Mapping[str, str],
    name: str,
    default: Path,
) -> Path:
    value = environment.get(name)
    path = default if value is None else Path(value)
    if not path.is_absolute():
        raise ValueError(f"{name} must be an explicit absolute path.")
    return path


def _optional_absolute_path(
    environment: Mapping[str, str],
    name: str,
) -> Path | None:
    value = environment.get(name)
    if value is None or not value.strip():
        return None
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f"{name} must be an explicit absolute path.")
    return path
