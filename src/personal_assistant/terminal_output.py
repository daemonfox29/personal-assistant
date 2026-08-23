"""Render untrusted text without allowing terminal control sequences."""

import unicodedata


def _escaped_code_point(character: str) -> str:
    value = ord(character)
    return f"\\u{value:04x}" if value <= 0xFFFF else f"\\U{value:08x}"


def sanitize_terminal_text(text: str) -> str:
    """Expose unsafe control and invisible formatting characters as text."""

    safe: list[str] = []
    for character in text:
        value = ord(character)
        variation_selector = (
            0xFE00 <= value <= 0xFE0F
            or 0xE0100 <= value <= 0xE01EF
        )
        if character in {"\n", "\t"}:
            safe.append(character)
        elif (
            unicodedata.category(character) in {"Cc", "Cf"}
            or variation_selector
        ):
            safe.append(_escaped_code_point(character))
        else:
            safe.append(character)
    return "".join(safe)
