"""Headless tests for secret handling and inert native rendering."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QCloseEvent, QFont  # noqa: E402
from PySide6.QtWidgets import QApplication, QLineEdit  # noqa: E402

from personal_assistant.application_service import ApplicationLaunchState  # noqa: E402
from personal_assistant.conversation import (  # noqa: E402
    ConversationEvent,
    ConversationEventKind,
)
from personal_assistant.ui import AssistantWindow, ChatPage, WelcomePage  # noqa: E402


class NativeUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_setup_fields_are_masked_and_cleared_before_signal_returns(self) -> None:
        page = WelcomePage()
        page.set_state(ApplicationLaunchState.SETUP_REQUIRED)
        fields = (
            page._recovery,
            page._recovery_confirmation,
            page._passcode,
            page._passcode_confirmation,
        )
        for field, value in zip(fields, ("recovery", "recovery", "passcode", "passcode")):
            field.setText(value)
            self.assertEqual(field.echoMode(), QLineEdit.EchoMode.Password)
        captured: list[tuple[str, str, str, str]] = []
        page.setup_requested.connect(lambda *values: captured.append(values))

        page._submit()

        self.assertEqual(captured[0], ("recovery", "recovery", "passcode", "passcode"))
        self.assertTrue(all(field.text() == "" for field in fields))

    def test_transcript_uses_plain_text_and_exposes_invisible_controls(self) -> None:
        page = ChatPage()
        page.append_user("<img src=https://example.invalid>\u202e")
        page.apply_event(
            ConversationEvent(
                ConversationEventKind.ASSISTANT_CHUNK,
                "<script>alert(1)</script>",
            )
        )
        page.apply_event(ConversationEvent(ConversationEventKind.COMPLETED))

        transcript = page.transcript_text()
        self.assertIn("<img src=https://example.invalid>", transcript)
        self.assertIn(r"\u202e", transcript)
        self.assertIn("<script>alert(1)</script>", transcript)
        self.assertFalse(page._transcript.acceptRichText())

    def test_assistant_markdown_gets_inert_native_formatting(self) -> None:
        page = ChatPage()
        page.apply_event(
            ConversationEvent(
                ConversationEventKind.ASSISTANT_CHUNK,
                "## Plan\n- **First** use `safe code`.\n"
                "[Reference](https://example.invalid)",
            )
        )
        page.apply_event(ConversationEvent(ConversationEventKind.COMPLETED))

        transcript = page.transcript_text()
        self.assertIn("Plan\n• First use safe code.", transcript)
        self.assertIn("[Reference](https://example.invalid)", transcript)
        heading = page._transcript.document().find("Plan")
        link_text = page._transcript.document().find("Reference")
        self.assertEqual(heading.charFormat().fontWeight(), QFont.Weight.Bold)
        self.assertFalse(link_text.charFormat().isAnchor())

    def test_oversized_ui_message_is_refused_before_signal(self) -> None:
        page = ChatPage()
        sent: list[tuple[str, int]] = []
        page.message_requested.connect(lambda text, limit: sent.append((text, limit)))
        page._input.setPlainText("x" * 32_001)

        page._submit()

        self.assertEqual(sent, [])
        self.assertIn("too large for the interface", page.transcript_text())

    def test_busy_chat_prevents_a_second_visible_submission(self) -> None:
        page = ChatPage()

        page.set_busy(True)

        self.assertFalse(page._input.isEnabled())
        self.assertFalse(page._send.isEnabled())
        self.assertFalse(page._limit.isEnabled())

    def test_window_shutdown_closes_the_application_service(self) -> None:
        class Factory:
            @staticmethod
            def launch_state() -> ApplicationLaunchState:
                return ApplicationLaunchState.SESSION_ONLY

        class Service:
            closed = False

            def close(self) -> None:
                self.closed = True

        window = AssistantWindow(Factory())
        service = Service()
        window._service = service
        event = QCloseEvent()

        window.closeEvent(event)

        self.assertTrue(service.closed)
        self.assertTrue(event.isAccepted())

    def test_failed_post_setup_startup_refreshes_to_unlock_state(self) -> None:
        class Factory:
            state = ApplicationLaunchState.SETUP_REQUIRED

            def launch_state(self) -> ApplicationLaunchState:
                return self.state

        factory = Factory()
        window = AssistantWindow(factory)
        shown_errors: list[str] = []
        window._show_safe_error = shown_errors.append
        factory.state = ApplicationLaunchState.UNLOCK_REQUIRED

        window._startup_failed("Ollama is unavailable.")

        self.assertEqual(shown_errors, ["Ollama is unavailable."])
        self.assertEqual(window._welcome._state, ApplicationLaunchState.UNLOCK_REQUIRED)
        self.assertTrue(window._welcome.isEnabled())


if __name__ == "__main__":
    unittest.main()
