"""Validated non-secret preferences persisted for the native application."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import stat
from tempfile import mkstemp

from personal_assistant.model import validate_response_token_limit


PREFERENCES_VERSION = 1
PREFERENCES_FILENAME = "preferences.json"
MIN_CONTEXT_TOKENS = 2_048
MAX_CONTEXT_TOKENS = 131_072
MIN_INPUT_TOKENS = 1_024
MAX_PREFERENCES_BYTES = 4_096


class RuntimePreferencesError(RuntimeError):
    """A preferences file is unavailable, malformed, or unsafe."""


@dataclass(frozen=True)
class RuntimePreferences:
    """User-adjustable resource limits that never contain secrets."""

    context_tokens: int = 16_384
    default_response_tokens: int = 400
    maximum_response_tokens: int = 2_000

    def __post_init__(self) -> None:
        if (
            isinstance(self.context_tokens, bool)
            or not isinstance(self.context_tokens, int)
            or not MIN_CONTEXT_TOKENS
            <= self.context_tokens
            <= MAX_CONTEXT_TOKENS
        ):
            raise ValueError("The context window is outside its supported range.")
        validate_response_token_limit(self.default_response_tokens)
        validate_response_token_limit(self.maximum_response_tokens)
        if self.default_response_tokens > self.maximum_response_tokens:
            raise ValueError(
                "The default response limit cannot exceed the response ceiling."
            )
        if self.context_tokens - self.maximum_response_tokens < MIN_INPUT_TOKENS:
            raise ValueError(
                "The context window must reserve at least 1,024 tokens for input."
            )


@dataclass(frozen=True)
class RuntimePreferencesStore:
    """Read and atomically replace one small, versioned JSON preferences file."""

    path: Path

    def __post_init__(self) -> None:
        if not isinstance(self.path, Path) or not self.path.is_absolute():
            raise ValueError("Preferences require an explicit absolute path.")
        if self.path.name != PREFERENCES_FILENAME:
            raise ValueError("The preferences filename is invalid.")

    def load(self) -> RuntimePreferences | None:
        if not self.path.exists() and not self.path.is_symlink():
            return None
        if self.path.is_symlink() or not self.path.is_file():
            raise RuntimePreferencesError("The preferences file is unsafe.")
        try:
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(self.path, flags)
            try:
                status = os.fstat(descriptor)
                if not stat.S_ISREG(status.st_mode):
                    raise RuntimePreferencesError(
                        "The preferences file is unsafe."
                    )
                if status.st_size > MAX_PREFERENCES_BYTES:
                    raise RuntimePreferencesError(
                        "The preferences file is too large."
                    )
                stream = os.fdopen(descriptor, "r", encoding="utf-8")
                descriptor = -1
                with stream:
                    payload = json.load(stream)
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
            if not isinstance(payload, dict) or set(payload) != {
                "context_tokens",
                "default_response_tokens",
                "maximum_response_tokens",
                "version",
            }:
                raise RuntimePreferencesError("The preferences file is invalid.")
            if (
                isinstance(payload["version"], bool)
                or payload["version"] != PREFERENCES_VERSION
            ):
                raise RuntimePreferencesError(
                    "The preferences version is not supported."
                )
            return RuntimePreferences(
                context_tokens=payload["context_tokens"],
                default_response_tokens=payload["default_response_tokens"],
                maximum_response_tokens=payload["maximum_response_tokens"],
            )
        except RuntimePreferencesError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            raise RuntimePreferencesError("The preferences file is invalid.") from error

    def save(self, preferences: RuntimePreferences) -> None:
        if not isinstance(preferences, RuntimePreferences):
            raise TypeError("A validated preferences value is required.")
        parent = self.path.parent
        try:
            parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if parent.is_symlink() or not parent.is_dir():
                raise RuntimePreferencesError(
                    "The preferences directory is unsafe."
                )
            payload = json.dumps(
                {
                    "context_tokens": preferences.context_tokens,
                    "default_response_tokens": preferences.default_response_tokens,
                    "maximum_response_tokens": preferences.maximum_response_tokens,
                    "version": PREFERENCES_VERSION,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            descriptor, temporary_name = mkstemp(
                prefix=".preferences-",
                suffix=".tmp",
                dir=parent,
                text=True,
            )
            temporary_path = Path(temporary_name)
            try:
                if os.name == "posix":
                    os.fchmod(descriptor, 0o600)
                stream = os.fdopen(descriptor, "w", encoding="utf-8")
                descriptor = -1
                with stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary_path, self.path)
                self._sync_directory(parent)
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
                if temporary_path.exists() and not temporary_path.is_symlink():
                    temporary_path.unlink()
        except RuntimePreferencesError:
            raise
        except OSError as error:
            raise RuntimePreferencesError(
                "The preferences could not be saved safely."
            ) from error

    def delete(self) -> None:
        """Remove preferences only when the target is the expected regular file."""

        if not self.path.exists() and not self.path.is_symlink():
            return
        if self.path.is_symlink() or not self.path.is_file():
            raise RuntimePreferencesError("The preferences file is unsafe.")
        try:
            self.path.unlink()
            self._sync_directory(self.path.parent)
        except OSError as error:
            raise RuntimePreferencesError(
                "The preferences could not be removed safely."
            ) from error

    @staticmethod
    def _sync_directory(directory: Path) -> None:
        try:
            descriptor = os.open(directory, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        except OSError:
            pass
        finally:
            os.close(descriptor)
