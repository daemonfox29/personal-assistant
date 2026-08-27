"""Headless tests for secret handling and inert native rendering."""

import os
from threading import Event, get_ident
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
    ApplicationOpenError,
    ApplicationSessionInfo,
    AuditInventoryItem,
    AuditInventoryPage,
    BackupInventoryItem,
    BackupOverview,
    MemoryInventoryItem,
    MemoryInventoryPage,
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
        self.assertEqual(page._section_list.count(), 5)
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
                    "people-pets-luna",
                ),
                MemoryInventoryItem(
                    second_id,
                    "Observations",
                    "Synthetic schedule changes may be draining",
                    "insight",
                    "candidate",
                    "2026-08-25",
                ),
            ),
            next_cursor="synthetic-next-page",
        )
        source_requests: list[str] = []
        delete_requests: list[str] = []
        page_requests: list[str] = []
        page.memory_source_requested.connect(source_requests.append)
        page.memory_delete_requested.connect(delete_requests.append)
        page.memory_next_page_requested.connect(page_requests.append)

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
        page._memory_load_more.click()
        self.assertEqual(page_requests, ["synthetic-next-page"])
        page.set_memories(
            (
                MemoryInventoryItem(
                    uuid4(),
                    "People & pets",
                    "Luna likes synthetic rope toys",
                    "preference",
                    "confirmed",
                    "2026-08-20",
                    "people-pets-luna",
                ),
            ),
            append=True,
        )
        self.assertEqual(page._memory_table.rowCount(), 2)

    def test_backup_and_audit_pages_are_bounded_native_controls(self) -> None:
        page = SettingsPage()
        snapshot = BackupInventoryItem(
            "memory-20260826T190000Z-" + ("a" * 32) + ".db",
            1_572_864,
            "2026-08-26T19:00:00+00:00",
        )
        page.set_backups(BackupOverview("/tmp/synthetic-backups", (snapshot,)))
        restored: list[str] = []
        page.backup_restore_requested.connect(restored.append)
        page._backup_table.selectRow(0)
        page._backup_restore.click()

        self.assertEqual(restored, [snapshot.snapshot_name])
        self.assertEqual(page._backup_table.item(0, 1).text(), "1.5 MB")
        first = AuditInventoryItem(
            "2026-08-26T19:00:00.000Z",
            "backup",
            "backup_create",
            "succeeded",
            "normal",
        )
        page.set_audit_events(AuditInventoryPage((first,), "100"))
        audit_pages: list[str] = []
        page.audit_next_page_requested.connect(audit_pages.append)
        page._audit_load_more.click()

        self.assertEqual(page._audit_table.rowCount(), 1)
        self.assertEqual(page._audit_table.item(0, 2).text(), "Backup Create")
        self.assertEqual(audit_pages, ["100"])
        self.assertEqual(
            page._audit_table.accessibleName(),
            "Redacted audit events table",
        )

    def test_settings_primary_controls_are_named_and_keyboard_navigable(self) -> None:
        page = SettingsPage()
        page.show()
        page._section_list.setFocus()

        self.assertEqual(page._section_list.accessibleName(), "Settings sections")
        for control in (
            page._memory_search,
            page._memory_table,
            page._communication_style,
            page._context_tokens,
            page._default_response_tokens,
            page._maximum_response_tokens,
            page._backup_table,
            page._backup_create,
            page._backup_restore,
            page._audit_table,
            page._audit_load_more,
        ):
            self.assertTrue(control.accessibleName())

        QTest.keyClick(page._section_list, Qt.Key.Key_Down)
        self.assertEqual(page._section_pages.currentIndex(), 2)
        QTest.keyClick(page._section_list, Qt.Key.Key_Down)
        self.assertEqual(page._section_pages.currentIndex(), 3)
        QTest.keyClick(page._section_list, Qt.Key.Key_Down)
        self.assertEqual(page._section_pages.currentIndex(), 4)
        QTest.keyClick(page._section_list, Qt.Key.Key_Down)
        self.assertEqual(page._section_pages.currentIndex(), 5)
        page.close()

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
        self.assertTrue(page._settings.isEnabled())
        self.assertTrue(page._new_chat.isEnabled())
        self.assertTrue(page._private_chat.isEnabled())
        self.assertTrue(page._conversation_list.isEnabled())
        self.assertFalse(page._delete_chat.isEnabled())

    def test_generation_allows_navigation_without_mixing_chat_output(self) -> None:
        started = Event()
        release = Event()
        first_id = uuid4()
        second_id = uuid4()
        opened: list[object] = []
        first_summary = ConversationSummary(
            first_id,
            "First synthetic chat",
            datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        second_summary = ConversationSummary(
            second_id,
            "Second synthetic chat",
            datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
        second_conversation = StoredConversation(
            second_summary,
            (
                StoredConversationMessage(
                    ConversationRole.USER,
                    "Second chat question",
                    1,
                ),
                StoredConversationMessage(
                    ConversationRole.ASSISTANT,
                    "Second chat answer",
                    2,
                ),
            ),
        )

        class Factory:
            runtime_preferences = RuntimePreferences()

            @staticmethod
            def launch_state() -> ApplicationLaunchState:
                return ApplicationLaunchState.SESSION_ONLY

        class Service:
            communication_style = ""
            info = ApplicationSessionInfo(
                "synthetic",
                False,
                400,
                1_200,
                2_000,
            )
            active_conversation_id = first_id
            private_chat = False

            @staticmethod
            def iter_events(_text, *, max_response_tokens=None):
                started.set()
                yield ConversationEvent(
                    ConversationEventKind.ASSISTANT_CHUNK,
                    "First chat partial output",
                )
                release.wait(2.0)
                yield ConversationEvent(
                    ConversationEventKind.ASSISTANT_CHUNK,
                    " and completion",
                )
                yield ConversationEvent(ConversationEventKind.COMPLETED)

            @staticmethod
            def view_conversation(identifier):
                self.assertEqual(identifier, second_id)
                return second_conversation

            @staticmethod
            def open_conversation(identifier):
                opened.append(identifier)
                Service.active_conversation_id = identifier
                return second_conversation

            @staticmethod
            def list_conversations():
                return (second_summary, first_summary)

            @staticmethod
            def list_memories_page():
                return MemoryInventoryPage((), None)

            @staticmethod
            def list_audit_events():
                return AuditInventoryPage((), None)

            @staticmethod
            def close() -> None:
                pass

        window = AssistantWindow(Factory())
        window._service = Service()
        window._show_safe_error = self.fail
        window._chat.append_user("First chat question")
        window._start_message("First chat question", 400)
        for _ in range(100):
            self.app.processEvents()
            if started.is_set() and "partial output" in window._chat.transcript_text():
                break
            QTest.qWait(5)

        self.assertTrue(started.is_set())
        self.assertTrue(window._chat._settings.isEnabled())
        window._chat._settings.click()
        self.assertIs(window._pages.currentWidget(), window._settings)
        window._return_to_chat()
        self.assertIs(window._pages.currentWidget(), window._chat)
        self.assertFalse(window._chat._input.isEnabled())

        window._open_conversation(str(second_id))
        self.assertIn("Second chat answer", window._chat.transcript_text())
        self.assertNotIn("First chat partial output", window._chat.transcript_text())
        self.assertFalse(window._chat._input.isEnabled())
        self.assertIn("finishing in the background", window._chat._status.text())

        release.set()
        for _ in range(200):
            self.app.processEvents()
            if window._chat_thread is None:
                break
            QTest.qWait(5)

        self.assertIsNone(window._chat_thread)
        self.assertEqual(opened, [second_id])
        self.assertIn("Second chat answer", window._chat.transcript_text())
        self.assertNotIn("First chat partial output", window._chat.transcript_text())
        self.assertTrue(window._chat._input.isEnabled())
        window._service = None
        window.hide()

    def test_missing_backup_drive_does_not_block_settings(self) -> None:
        class Factory:
            runtime_preferences = RuntimePreferences(
                backup_directory="/Volumes/Synthetic Missing Drive"
            )

            @staticmethod
            def launch_state() -> ApplicationLaunchState:
                return ApplicationLaunchState.SESSION_ONLY

        class Service:
            communication_style = ""
            info = ApplicationSessionInfo(
                "synthetic",
                True,
                400,
                1_200,
                2_000,
            )

            @staticmethod
            def list_memories_page() -> MemoryInventoryPage:
                return MemoryInventoryPage((), None)

            @staticmethod
            def list_audit_events() -> AuditInventoryPage:
                return AuditInventoryPage((), None)

            @staticmethod
            def list_backups() -> BackupOverview:
                raise ApplicationOpenError(
                    "Encrypted backup status could not be read safely."
                )

            @staticmethod
            def close() -> None:
                pass

        window = AssistantWindow(Factory())
        window._service = Service()
        errors: list[str] = []
        window._show_safe_error = errors.append

        window._show_settings()

        self.assertIs(window._pages.currentWidget(), window._settings)
        for _ in range(100):
            self.app.processEvents()
            if window._backup_thread is None:
                break
            QTest.qWait(5)
        self.assertIsNone(window._backup_thread)
        self.assertTrue(window._settings.isEnabled())
        self.assertEqual(
            window._settings._backup_directory.text(),
            "/Volumes/Synthetic Missing Drive",
        )
        self.assertIn("Backup operation unavailable", window._settings._backup_status.text())
        self.assertEqual(
            errors,
            ["Encrypted backup status could not be read safely."],
        )
        window._service = None
        window.hide()

    def test_backup_work_runs_off_ui_thread_and_validates_before_persisting(
        self,
    ) -> None:
        calls: list[tuple[str, int]] = []

        class Factory:
            runtime_preferences = RuntimePreferences()

            @staticmethod
            def launch_state() -> ApplicationLaunchState:
                return ApplicationLaunchState.SESSION_ONLY

            def save_backup_directory(self, path) -> None:
                calls.append(("factory-save", get_ident()))
                self.runtime_preferences = RuntimePreferences(
                    backup_directory=str(path)
                )

        class Service:
            @staticmethod
            def create_backup() -> None:
                calls.append(("service-create", get_ident()))

            @staticmethod
            def configure_backup_directory(_path) -> None:
                calls.append(("service-configure", get_ident()))

            @staticmethod
            def list_backups() -> BackupOverview:
                calls.append(("service-list", get_ident()))
                return BackupOverview("/tmp/synthetic-backups", ())

            @staticmethod
            def close() -> None:
                pass

        factory = Factory()
        window = AssistantWindow(factory)
        window._service = Service()
        window._show_safe_error = self.fail
        ui_thread = get_ident()

        window._create_backup()
        self.assertIsNotNone(window._backup_thread)
        for _ in range(100):
            self.app.processEvents()
            if window._backup_thread is None:
                break
            QTest.qWait(5)
        self.assertEqual([name for name, _ in calls], ["service-create", "service-list"])
        self.assertTrue(all(thread_id != ui_thread for _, thread_id in calls))

        calls.clear()
        window._configure_backup_directory("/tmp/synthetic-backups")
        for _ in range(100):
            self.app.processEvents()
            if window._backup_thread is None:
                break
            QTest.qWait(5)
        self.assertEqual(
            [name for name, _ in calls],
            ["service-configure", "factory-save", "service-list"],
        )
        self.assertTrue(all(thread_id != ui_thread for _, thread_id in calls))
        window._service = None
        window.hide()

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
