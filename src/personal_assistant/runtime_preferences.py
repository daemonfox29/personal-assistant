"""Validated non-secret preferences persisted for the native application."""

from dataclasses import dataclass
from enum import StrEnum
import json
import os
from pathlib import Path
import stat
from tempfile import mkstemp

from personal_assistant.model import validate_response_token_limit


PREFERENCES_VERSION = 3
PREFERENCES_FILENAME = "preferences.json"
MIN_CONTEXT_TOKENS = 2_048
MAX_CONTEXT_TOKENS = 131_072
MIN_INPUT_TOKENS = 1_024
MAX_PREFERENCES_BYTES = 4_096
MIN_UI_FONT_SIZE = 11
MAX_UI_FONT_SIZE = 24
MAX_FONT_FAMILY_CHARS = 128
MAX_BACKUP_PATH_CHARS = 1_024


class ThemePreference(StrEnum):
    SYSTEM = "system"
    LIGHT = "light"
    DARK = "dark"


class RuntimePreferencesError(RuntimeError):
    """A preferences file is unavailable, malformed, or unsafe."""


@dataclass(frozen=True)
class RuntimePreferences:
    """User-adjustable resource limits that never contain secrets."""

    context_tokens: int = 16_384
    default_response_tokens: int = 400
    maximum_response_tokens: int = 2_000
    theme: ThemePreference = ThemePreference.SYSTEM
    font_family: str = "system"
    font_size: int = 13
    backup_directory: str = ""

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
        if not isinstance(self.theme, ThemePreference):
            raise ValueError("The interface theme is invalid.")
        if (
            not isinstance(self.font_family, str)
            or not self.font_family
            or len(self.font_family) > MAX_FONT_FAMILY_CHARS
            or any(ord(character) < 32 for character in self.font_family)
        ):
            raise ValueError("The interface font is invalid.")
        if (
            isinstance(self.font_size, bool)
            or not isinstance(self.font_size, int)
            or not MIN_UI_FONT_SIZE <= self.font_size <= MAX_UI_FONT_SIZE
        ):
            raise ValueError("The interface font size is outside its range.")
        if not isinstance(self.backup_directory, str):
            raise ValueError("The backup directory is invalid.")
        if self.backup_directory:
            backup_path = Path(self.backup_directory)
            if (
                len(self.backup_directory) > MAX_BACKUP_PATH_CHARS
                or not backup_path.is_absolute()
                or backup_path.name in {"", ".", ".."}
                or any(ord(character) < 32 for character in self.backup_directory)
            ):
                raise ValueError("The backup directory is invalid.")


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
            if not isinstance(payload, dict):
                raise RuntimePreferencesError("The preferences file is invalid.")
            version = payload.get("version")
            if isinstance(version, bool) or version not in {1, 2, PREFERENCES_VERSION}:
                raise RuntimePreferencesError(
                    "The preferences version is not supported."
                )
            version_one_keys = {
                "context_tokens",
                "default_response_tokens",
                "maximum_response_tokens",
                "version",
            }
            version_two_keys = version_one_keys | {
                "theme",
                "font_family",
                "font_size",
            }
            version_three_keys = version_two_keys | {"backup_directory"}
            expected_keys = {
                1: version_one_keys,
                2: version_two_keys,
                3: version_three_keys,
            }[version]
            if set(payload) != expected_keys:
                raise RuntimePreferencesError("The preferences file is invalid.")
            return RuntimePreferences(
                context_tokens=payload["context_tokens"],
                default_response_tokens=payload["default_response_tokens"],
                maximum_response_tokens=payload["maximum_response_tokens"],
                theme=(
                    ThemePreference.SYSTEM
                    if version == 1
                    else ThemePreference(payload["theme"])
                ),
                font_family=("system" if version == 1 else payload["font_family"]),
                font_size=(13 if version == 1 else payload["font_size"]),
                backup_directory=(
                    "" if version in {1, 2} else payload["backup_directory"]
                ),
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
                    "theme": preferences.theme.value,
                    "font_family": preferences.font_family,
                    "font_size": preferences.font_size,
                    "backup_directory": preferences.backup_directory,
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
