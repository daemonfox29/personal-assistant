"""Headless tests for secret handling and inert native rendering."""

import os
import unittest
from unittest.mock import patch
from datetime import datetime, timezone
from uuid import uuid4

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QCloseEvent, QFont  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QLineEdit,
    QMessageBox,
    QPushButton,
)

from personal_assistant.application_service import (  # noqa: E402
    ApplicationLaunchState,
    MemoryInventoryItem,
    MemoryReviewItem,
    MemoryReviewRelatedItem,
)
from personal_assistant.conversation import (  # noqa: E402
    ConversationEvent,
    ConversationEventKind,
)
from personal_assistant.conversation_history import (  # noqa: E402
    ConversationRole,
    ConversationSummary,
    StoredConversation,
    StoredConversationMessage,
)
from personal_assistant.runtime_preferences import RuntimePreferences  # noqa: E402
from personal_assistant.ui import (  # noqa: E402
    AssistantWindow,
    ChatPage,
    SettingsPage,
    UI_FONT_FAMILY,
    WelcomePage,
)


class NativeUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setFont(QFont(UI_FONT_FAMILY, 13))

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

    def test_automatic_unlock_state_needs_no_secret_field(self) -> None:
        page = WelcomePage()
        page.set_state(ApplicationLaunchState.AUTOMATIC_UNLOCK)
        requested: list[bool] = []
        page.automatic_unlock_requested.connect(lambda: requested.append(True))

        page._submit()

        self.assertEqual(requested, [True])
        self.assertEqual(page._form.labelForField(page._recovery), None)

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

    def test_enter_submits_and_shift_enter_inserts_a_newline(self) -> None:
        page = ChatPage()
        page.configure_session("synthetic", False, 400, 1_200, 2_000)
        sent: list[tuple[str, int]] = []
        page.message_requested.connect(lambda text, limit: sent.append((text, limit)))
        QTest.keyClicks(page._input, "first line")

        QTest.keyClick(
            page._input,
            Qt.Key.Key_Return,
            Qt.KeyboardModifier.ShiftModifier,
        )

        self.assertEqual(sent, [])
        self.assertIn("\n", page._input.toPlainText())
        page._input.insertPlainText("second line")
        QTest.keyClick(page._input, Qt.Key.Key_Return)
        self.assertEqual(sent, [("first line\nsecond line", 400)])
        self.assertEqual(page._input.toPlainText(), "")

    def test_thinking_indicator_animates_then_yields_to_memory_stage_direction(self) -> None:
        page = ChatPage()
        page.configure_session("synthetic", False, 400, 1_200, 2_000)
        page._input.setPlainText("Synthetic prompt")

        page._submit()

        self.assertIn("Thinking.", page.transcript_text())
        page._advance_thinking()
        self.assertIn("Thinking..", page.transcript_text())
        page.apply_event(
            ConversationEvent(
                ConversationEventKind.NOTICE,
                "Memory updated: pet.",
            )
        )
        transcript = page.transcript_text()
        self.assertNotIn("Thinking", transcript)
        self.assertIn("Memory updated: pet.", transcript)
        self.assertNotIn("Notice\nMemory updated", transcript)
        memory_text = page._transcript.document().find("Memory updated")
        self.assertTrue(memory_text.charFormat().fontItalic())

    def test_settings_page_emits_validated_bounded_values(self) -> None:
        page = SettingsPage()
        page.set_preferences(
            RuntimePreferences(
                context_tokens=32_768,
                default_response_tokens=800,
                maximum_response_tokens=1_600,
            )
        )
        saved: list[tuple[int, int, int]] = []
        page.save_requested.connect(lambda *values: saved.append(values))

        page._save()

        self.assertEqual(
            saved,
            [(32_768, 800, 1_600, "system", "system", 13)],
        )
        self.assertEqual(page._maximum_response_tokens.maximum(), 2_000)

    def test_settings_communication_style_is_bounded_and_emits_save(self) -> None:
        page = SettingsPage()
        saved: list[str] = []
        page.communication_style_save_requested.connect(saved.append)
        page.set_communication_style(
            "Be warm and use plain language.",
            persistent=True,
        )
        page._section_list.setCurrentRow(1)

        page._communication_save.click()

        self.assertEqual(saved, ["Be warm and use plain language."])
        self.assertEqual(page._section_pages.currentIndex(), 2)
        self.assertEqual(page._section_list.count(), 3)
        page._communication_style.setPlainText("x" * 2_001)
        self.assertFalse(page._communication_save.isEnabled())

    def test_memory_review_previews_correction_and_emits_bounded_values(self) -> None:
        page = SettingsPage()
        candidate_id = uuid4()
        target_id = uuid4()
        page.set_memory_candidates(
            (
                MemoryReviewItem(
                    candidate_id,
                    3,
                    "I now prefer synthetic evenings.",
                    "preference",
                    "personal",
                    "ask_before_mentioning",
                    "2026-09-25",
                    False,
                    (
                        MemoryReviewRelatedItem(
                            target_id,
                            4,
                            "I prefer synthetic mornings.",
                            "2026-08-20",
                        ),
                    ),
                ),
            )
        )
        applied: list[tuple[object, ...]] = []
        page.candidate_apply_requested.connect(
            lambda *values: applied.append(values)
        )
        page._candidate_table.selectRow(0)
        page._candidate_decision.setCurrentIndex(1)

        with patch(
            "personal_assistant.ui.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            page._candidate_apply.click()

        self.assertEqual(
            applied,
            [
                (
                    str(candidate_id),
                    3,
                    "I now prefer synthetic evenings.",
                    str(target_id),
                    4,
                    "correct",
                    page._candidate_date.date().toString("yyyy-MM-dd"),
                    "personal",
                )
            ],
        )

    def test_settings_memory_table_is_compact_filterable_and_emits_row_actions(
        self,
    ) -> None:
        page = SettingsPage()
        first_id = uuid4()
        second_id = uuid4()
        page.set_memories(
            (
                MemoryInventoryItem(
                    first_id,
                    "People & pets",
                    "Luna likes synthetic rope toys",
                    "preference",
                    "confirmed",
                    "2026-08-26",
                ),
                MemoryInventoryItem(
                    second_id,
                    "Observations",
                    "Synthetic schedule changes may be draining",
                    "insight",
                    "candidate",
                    "2026-08-25",
                ),
            )
        )
        source_requests: list[str] = []
        delete_requests: list[str] = []
        page.memory_source_requested.connect(source_requests.append)
        page.memory_delete_requested.connect(delete_requests.append)

        self.assertEqual(page._memory_table.rowCount(), 2)
        self.assertEqual(
            page._memory_table.item(0, 0).text(),
            "Luna likes synthetic rope toys",
        )
        self.assertEqual(page._memory_category.count(), 3)
        self.assertEqual(page._section_pages.currentIndex(), 0)
        self.assertEqual(page._memory_table.item(1, 1).text(), "Observation")
        self.assertEqual(page._memory_table.item(1, 2).text(), "Tentative")
        page._memory_search.setText("schedule")
        self.assertTrue(page._memory_table.isRowHidden(0))
        self.assertFalse(page._memory_table.isRowHidden(1))

        actions = page._memory_table.cellWidget(1, 4)
        buttons = actions.findChildren(QPushButton)
        buttons[0].click()
        buttons[1].click()
        self.assertEqual(source_requests, [str(second_id)])
        self.assertEqual(delete_requests, [str(second_id)])

    def test_sidebar_selects_and_renders_a_structured_saved_conversation(self) -> None:
        page = ChatPage()
        conversation_id = uuid4()
        summary = ConversationSummary(
            conversation_id,
            "Scooby history",
            datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        stored = StoredConversation(
            summary,
            (
                StoredConversationMessage(
                    ConversationRole.USER,
                    "Who is Scooby?",
                    1,
                ),
                StoredConversationMessage(
                    ConversationRole.ASSISTANT,
                    "Scooby is your dog.",
                    2,
                ),
            ),
        )
        selected: list[str] = []
        page.conversation_requested.connect(selected.append)

        page.set_conversations((summary,), conversation_id)
        page._conversation_list.itemClicked.emit(page._conversation_list.item(0))
        page.show_stored_conversation(stored)

        self.assertEqual(selected, [str(conversation_id)])
        self.assertIn("Who is Scooby?", page.transcript_text())
        self.assertIn("Scooby is your dog.", page.transcript_text())

    def test_source_navigation_highlights_exact_message_sequence(self) -> None:
        page = ChatPage()
        summary = ConversationSummary(
            uuid4(),
            "Synthetic source chat",
            datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        conversation = StoredConversation(
            summary,
            (
                StoredConversationMessage(
                    ConversationRole.USER,
                    "Repeated synthetic text",
                    1,
                ),
                StoredConversationMessage(
                    ConversationRole.ASSISTANT,
                    "Synthetic first response",
                    2,
                ),
                StoredConversationMessage(
                    ConversationRole.USER,
                    "Repeated synthetic text",
                    3,
                ),
                StoredConversationMessage(
                    ConversationRole.ASSISTANT,
                    "Synthetic second response",
                    4,
                ),
            ),
        )

        page.show_stored_conversation(conversation, highlight_sequence=3)

        selections = page._transcript.extraSelections()
        self.assertEqual(len(selections), 1)
        self.assertIn(
            "Repeated synthetic text",
            selections[0].cursor.selectedText(),
        )
        self.assertIn(
            "Synthetic second response",
            page.transcript_text(),
        )

    def test_busy_chat_prevents_a_second_visible_submission(self) -> None:
        page = ChatPage()

        page.set_busy(True)

        self.assertFalse(page._input.isEnabled())
        self.assertFalse(page._send.isEnabled())
        self.assertFalse(page._limit.isEnabled())

    def test_window_shutdown_closes_the_application_service(self) -> None:
        class Factory:
            runtime_preferences = RuntimePreferences()

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
            runtime_preferences = RuntimePreferences()

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
