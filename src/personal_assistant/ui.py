"""Lean native PySide6 interface over the bounded application service."""

import os
import re
import sys
from threading import Event
from uuid import UUID

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtGui import (
    QColor,
    QCloseEvent,
    QFont,
    QFontDatabase,
    QKeyEvent,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from personal_assistant.application_service import (
    ApplicationLaunchState,
    ApplicationOpenError,
    ApplicationRecoveryRequired,
    ApplicationServiceError,
    ApplicationSettingsError,
    AssistantApplicationFactory,
    AssistantApplicationService,
)
from personal_assistant.config import load_desktop_settings
from personal_assistant.conversation import ConversationEvent, ConversationEventKind
from personal_assistant.conversation_history import (
    ConversationRole,
    ConversationSummary,
    StoredConversation,
)
from personal_assistant.credential_store import default_recovery_credential_store
from personal_assistant.runtime_preferences import (
    MAX_CONTEXT_TOKENS,
    MAX_UI_FONT_SIZE,
    MIN_INPUT_TOKENS,
    MIN_CONTEXT_TOKENS,
    MIN_UI_FONT_SIZE,
    RuntimePreferences,
    RuntimePreferencesError,
    ThemePreference,
)
from personal_assistant.terminal_output import sanitize_terminal_text


WINDOW_TITLE = "Personal Assistant"
UI_FONT_FAMILY = (
    "Helvetica Neue"
    if sys.platform == "darwin"
    else "Segoe UI"
    if sys.platform == "win32"
    else "DejaVu Sans"
)
CODE_FONT_FAMILY = (
    "Menlo"
    if sys.platform == "darwin"
    else "Consolas"
    if sys.platform == "win32"
    else "DejaVu Sans Mono"
)
MAX_VISIBLE_MESSAGE_CHARS = 32_000
MAX_TRANSCRIPT_BLOCKS = 2_000
MAX_DISPLAY_MESSAGES = 2_000
INLINE_MARKUP = re.compile(r"(\*\*[^*\n]+\*\*|`[^`\n]+`)")
HEADING_MARKUP = re.compile(r"^(#{1,3})\s+(.+)$")
BULLET_MARKUP = re.compile(r"^\s*[-*]\s+(.+)$")
NUMBERED_MARKUP = re.compile(r"^\s*(\d{1,3})[.)]\s+(.+)$")


class WelcomePage(QWidget):
    setup_requested = Signal(str, str, str, str)
    automatic_unlock_requested = Signal()
    unlock_requested = Signal(str)
    session_only_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._state = ApplicationLaunchState.SETUP_REQUIRED
        outer = QVBoxLayout(self)
        outer.setContentsMargins(64, 48, 64, 48)
        outer.addStretch()

        title = QLabel("Personal Assistant")
        title.setObjectName("welcomeTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(title)
        subtitle = QLabel(
            "Local-first chat with encrypted memory and deterministic safety "
            "boundaries."
        )
        subtitle.setWordWrap(True)
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(subtitle)

        self._card = QFrame()
        self._card.setObjectName("card")
        self._form = QFormLayout(self._card)
        self._form.setContentsMargins(28, 28, 28, 28)
        outer.addWidget(self._card)
        outer.addStretch()
        self.set_state(ApplicationLaunchState.SETUP_REQUIRED)

    def set_state(self, state: ApplicationLaunchState) -> None:
        self._state = state
        while self._form.rowCount():
            self._form.removeRow(0)
        self._recovery = self._secret_field()
        self._recovery_confirmation = self._secret_field()
        self._passcode = self._secret_field()
        self._passcode_confirmation = self._secret_field()
        self._primary = QPushButton()
        self._primary.setDefault(True)
        self._primary.clicked.connect(self._submit)
        self._session_only = QPushButton("Continue without persistent memory")
        self._session_only.setObjectName("secondaryButton")
        self._session_only.clicked.connect(self.session_only_requested)
        if state is ApplicationLaunchState.AUTOMATIC_UNLOCK:
            explanation = QLabel(
                "Encrypted memory will unlock through this computer's protected "
                "credential store."
            )
            explanation.setWordWrap(True)
            self._form.addRow(explanation)
            self._primary.setText("Start securely")
            self._form.addRow(self._primary)
            self._session_only.hide()
        elif state is ApplicationLaunchState.UNLOCK_REQUIRED:
            self._form.addRow("Recovery passphrase", self._recovery)
            self._primary.setText("Unlock and start")
            self._form.addRow(self._primary)
            self._session_only.hide()
        elif state is ApplicationLaunchState.SETUP_REQUIRED:
            explanation = QLabel(
                "Create a recovery passphrase (12+ characters) and a different "
                "high-risk passcode (8+ characters). Neither secret is stored."
            )
            explanation.setWordWrap(True)
            self._form.addRow(explanation)
            self._form.addRow("Recovery passphrase", self._recovery)
            self._form.addRow("Repeat recovery", self._recovery_confirmation)
            self._form.addRow("High-risk passcode", self._passcode)
            self._form.addRow("Repeat passcode", self._passcode_confirmation)
            self._primary.setText("Create encrypted memory")
            self._form.addRow(self._primary)
            self._form.addRow(self._session_only)
            self._session_only.show()
        else:
            explanation = QLabel("Persistent memory is disabled in local settings.")
            explanation.setWordWrap(True)
            self._form.addRow(explanation)
            self._primary.setText("Start session-only chat")
            self._form.addRow(self._primary)
            self._session_only.hide()
        self._idle_primary_text = self._primary.text()

    def set_busy(self, busy: bool) -> None:
        self._card.setEnabled(not busy)
        self._primary.setText(
            "Starting safely…" if busy else self._idle_primary_text
        )

    @Slot()
    def _submit(self) -> None:
        if self._state is ApplicationLaunchState.AUTOMATIC_UNLOCK:
            self.automatic_unlock_requested.emit()
            return
        if self._state is ApplicationLaunchState.UNLOCK_REQUIRED:
            recovery = self._recovery.text()
            self._clear_secret_fields()
            self.unlock_requested.emit(recovery)
            recovery = ""
            return
        if self._state is ApplicationLaunchState.SESSION_ONLY:
            self.session_only_requested.emit()
            return
        recovery = self._recovery.text()
        recovery_confirmation = self._recovery_confirmation.text()
        passcode = self._passcode.text()
        passcode_confirmation = self._passcode_confirmation.text()
        self._clear_secret_fields()
        self.setup_requested.emit(
            recovery,
            recovery_confirmation,
            passcode,
            passcode_confirmation,
        )
        recovery = recovery_confirmation = passcode = passcode_confirmation = ""

    def _clear_secret_fields(self) -> None:
        for field in (
            self._recovery,
            self._recovery_confirmation,
            self._passcode,
            self._passcode_confirmation,
        ):
            field.clear()

    @staticmethod
    def _secret_field() -> QLineEdit:
        field = QLineEdit()
        field.setEchoMode(QLineEdit.EchoMode.Password)
        field.setMaxLength(256)
        return field


class MessageComposer(QPlainTextEdit):
    """Multiline composer where Enter sends and Shift+Enter inserts a line."""

    submit_requested = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in {
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
        } and event.modifiers() in {
            Qt.KeyboardModifier.NoModifier,
            Qt.KeyboardModifier.KeypadModifier,
        }:
            self.submit_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class SettingsPage(QWidget):
    save_requested = Signal(int, int, int, str, str, int)
    back_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 36, 48, 36)
        title = QLabel("Settings")
        title.setObjectName("settingsTitle")
        layout.addWidget(title)
        explanation = QLabel(
            "Adjust appearance and local model resource limits. Changes are "
            "validated and audited; model limits apply after restart."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        card = QFrame()
        card.setObjectName("card")
        form = QFormLayout(card)
        form.setContentsMargins(28, 28, 28, 28)
        self._context_tokens = self._token_field(
            MIN_CONTEXT_TOKENS,
            MAX_CONTEXT_TOKENS,
            1_024,
        )
        self._context_tokens.valueChanged.connect(self._context_window_changed)
        self._default_response_tokens = self._token_field(1, 2_000, 100)
        self._maximum_response_tokens = self._token_field(1, 2_000, 100)
        self._maximum_response_tokens.valueChanged.connect(
            self._response_ceiling_changed
        )
        form.addRow("Context window", self._context_tokens)
        form.addRow("Default response limit", self._default_response_tokens)
        form.addRow("Response ceiling", self._maximum_response_tokens)
        self._theme = QComboBox()
        self._theme.addItem("Follow system", ThemePreference.SYSTEM.value)
        self._theme.addItem("Light", ThemePreference.LIGHT.value)
        self._theme.addItem("Dark", ThemePreference.DARK.value)
        self._font_family = QComboBox()
        self._font_family.addItem("System default", "system")
        for family in QFontDatabase.families():
            self._font_family.addItem(family, family)
        self._font_size = QSpinBox()
        self._font_size.setRange(MIN_UI_FONT_SIZE, MAX_UI_FONT_SIZE)
        self._font_size.setSuffix(" pt")
        form.addRow("Appearance", self._theme)
        form.addRow("Interface font", self._font_family)
        form.addRow("Interface font size", self._font_size)
        note = QLabel(
            "The response ceiling can be lowered but cannot exceed the project's "
            "2,000-token safety bound. Larger context windows use more RAM."
        )
        note.setWordWrap(True)
        form.addRow(note)
        layout.addWidget(card)
        self._result = QLabel()
        self._result.setObjectName("settingsResult")
        self._result.setWordWrap(True)
        layout.addWidget(self._result)
        buttons = QHBoxLayout()
        back = QPushButton("Back to chat")
        back.setObjectName("secondaryButton")
        back.clicked.connect(self.back_requested)
        save = QPushButton("Save settings")
        save.clicked.connect(self._save)
        buttons.addWidget(back)
        buttons.addStretch()
        buttons.addWidget(save)
        layout.addLayout(buttons)
        layout.addStretch()

    def set_preferences(self, preferences: RuntimePreferences) -> None:
        self._maximum_response_tokens.setValue(
            preferences.maximum_response_tokens
        )
        self._default_response_tokens.setValue(
            preferences.default_response_tokens
        )
        self._context_tokens.setValue(preferences.context_tokens)
        self._set_combo_value(self._theme, preferences.theme.value)
        self._set_combo_value(self._font_family, preferences.font_family)
        self._font_size.setValue(preferences.font_size)
        self._result.clear()

    def show_saved(self) -> None:
        self._result.setText(
            "Settings saved. Appearance is applied now; model limits apply after "
            "restart."
        )

    @Slot()
    def _save(self) -> None:
        self.save_requested.emit(
            self._context_tokens.value(),
            self._default_response_tokens.value(),
            self._maximum_response_tokens.value(),
            str(self._theme.currentData()),
            str(self._font_family.currentData()),
            self._font_size.value(),
        )

    @Slot(int)
    def _response_ceiling_changed(self, ceiling: int) -> None:
        self._default_response_tokens.setMaximum(ceiling)

    @Slot(int)
    def _context_window_changed(self, context_tokens: int) -> None:
        self._maximum_response_tokens.setMaximum(
            min(2_000, context_tokens - MIN_INPUT_TOKENS)
        )

    @staticmethod
    def _token_field(minimum: int, maximum: int, step: int) -> QSpinBox:
        field = QSpinBox()
        field.setRange(minimum, maximum)
        field.setSingleStep(step)
        field.setGroupSeparatorShown(True)
        field.setSuffix(" tokens")
        return field

    @staticmethod
    def _set_combo_value(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(0 if index < 0 else index)


class ChatPage(QWidget):
    message_requested = Signal(str, int)
    settings_requested = Signal()
    new_chat_requested = Signal(bool)
    conversation_requested = Signal(str)
    delete_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter)

        self._sidebar = QFrame()
        self._sidebar.setObjectName("historySidebar")
        sidebar = QVBoxLayout(self._sidebar)
        sidebar.setContentsMargins(14, 18, 14, 18)
        history_title = QLabel("Conversations")
        history_title.setObjectName("historyTitle")
        sidebar.addWidget(history_title)
        self._new_chat = QPushButton("New chat")
        self._new_chat.clicked.connect(lambda: self.new_chat_requested.emit(False))
        sidebar.addWidget(self._new_chat)
        self._private_chat = QPushButton("Private chat")
        self._private_chat.setObjectName("secondaryButton")
        self._private_chat.setToolTip(
            "Starts a chat that is not saved and does not create memory suggestions."
        )
        self._private_chat.clicked.connect(
            lambda: self.new_chat_requested.emit(True)
        )
        sidebar.addWidget(self._private_chat)
        self._conversation_list = QListWidget()
        self._conversation_list.setObjectName("conversationList")
        self._conversation_list.itemClicked.connect(self._conversation_clicked)
        sidebar.addWidget(self._conversation_list, 1)
        self._delete_chat = QPushButton("Delete selected")
        self._delete_chat.setObjectName("secondaryButton")
        self._delete_chat.clicked.connect(self._delete_selected)
        sidebar.addWidget(self._delete_chat)
        splitter.addWidget(self._sidebar)

        chat_panel = QWidget()
        layout = QVBoxLayout(chat_panel)
        layout.setContentsMargins(24, 20, 24, 20)
        header = QHBoxLayout()
        self._status = QLabel("Local session")
        self._status.setObjectName("sessionStatus")
        header.addWidget(self._status)
        header.addStretch()
        header.addWidget(QLabel("Response limit"))
        self._limit = QComboBox()
        header.addWidget(self._limit)
        self._settings = QPushButton("Settings")
        self._settings.setObjectName("secondaryButton")
        self._settings.clicked.connect(self.settings_requested)
        header.addWidget(self._settings)
        layout.addLayout(header)

        self._transcript = QTextEdit()
        self._transcript.setObjectName("transcript")
        self._transcript.setReadOnly(True)
        self._transcript.setAcceptRichText(False)
        self._transcript.document().setMaximumBlockCount(MAX_TRANSCRIPT_BLOCKS)
        layout.addWidget(self._transcript, 1)

        composer = QHBoxLayout()
        self._input = MessageComposer()
        self._input.setPlaceholderText(
            "Message your assistant…  Enter to send · Shift+Enter for a new line"
        )
        self._input.setMaximumHeight(110)
        self._input.submit_requested.connect(self._submit)
        self._send = QPushButton("Send")
        self._send.setDefault(True)
        self._send.clicked.connect(self._submit)
        composer.addWidget(self._input, 1)
        composer.addWidget(self._send)
        layout.addLayout(composer)
        self._assistant_open = False
        self._assistant_start: int | None = None
        self._assistant_raw: list[str] = []
        self._display_messages: list[tuple[ConversationRole, str]] = []
        self._base_status = "Local session"
        self._font_family = UI_FONT_FAMILY
        self._font_size = 14
        self._role_colors = {
            "You": "#7aa2ff",
            "Assistant": "#9ee6b8",
            "Notice": "#f0bd73",
        }
        self._body_color = "#e8eaf0"
        self._code_background = "#292f3a"
        self._code_color = "#d8e2ff"
        splitter.addWidget(chat_panel)
        splitter.setSizes([240, 700])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

    def configure_session(
        self,
        model_name: str,
        persistent_memory: bool,
        default_response_tokens: int,
        long_response_tokens: int,
        maximum_response_tokens: int,
    ) -> None:
        memory_text = "encrypted memory" if persistent_memory else "session only"
        self._base_status = f"{model_name} · {memory_text}"
        self._status.setText(self._base_status)
        self._sidebar.setVisible(persistent_memory)
        self._limit.clear()
        choices = (
            ("Default", default_response_tokens),
            ("Long", long_response_tokens),
            ("Maximum", maximum_response_tokens),
        )
        seen: set[int] = set()
        for label, limit in choices:
            if limit in seen:
                continue
            self._limit.addItem(f"{label} · {limit:,}", limit)
            seen.add(limit)
        self._limit.setCurrentIndex(0)

    def set_busy(self, busy: bool) -> None:
        self._input.setEnabled(not busy)
        self._send.setEnabled(not busy)
        self._limit.setEnabled(not busy)
        self._settings.setEnabled(not busy)
        self._new_chat.setEnabled(not busy)
        self._private_chat.setEnabled(not busy)
        self._conversation_list.setEnabled(not busy)
        self._delete_chat.setEnabled(not busy)
        if not busy:
            self._input.setFocus()

    def show_closing(self) -> None:
        self.set_busy(True)
        self._status.setText("Finishing the response and saving before close…")

    def append_user(self, text: str, *, record: bool = True) -> None:
        self._append_role("You")
        self._append_plain(f"{sanitize_terminal_text(text)}\n\n")
        if record:
            self._record_display_message(ConversationRole.USER, text)

    def apply_event(self, event: ConversationEvent, *, record: bool = True) -> None:
        if event.kind is ConversationEventKind.ASSISTANT_CHUNK:
            if not self._assistant_open:
                self._append_role("Assistant")
                self._assistant_open = True
                self._assistant_raw = []
                self._transcript.document().setMaximumBlockCount(0)
                self._assistant_start = self._transcript.textCursor().position()
            self._append_plain(event.text)
            self._assistant_raw.append(event.text)
        elif event.kind is ConversationEventKind.NOTICE:
            if self._assistant_open:
                self._finish_assistant(record=record)
            self._append_role("Notice")
            self._append_plain(f"{event.text}\n\n", italic=True)
            if record:
                self._record_display_message(ConversationRole.NOTICE, event.text)
        elif event.kind is ConversationEventKind.COMPLETED:
            if self._assistant_open:
                self._finish_assistant(record=record)
            if event.limit_reached:
                limit_notice = "Response stopped at its selected token limit."
                self._append_role("Notice")
                self._append_plain(
                    f"{limit_notice}\n\n",
                    italic=True,
                )
                if record:
                    self._record_display_message(
                        ConversationRole.NOTICE,
                        limit_notice,
                    )

    def transcript_text(self) -> str:
        return self._transcript.toPlainText()

    def set_conversations(
        self,
        conversations: tuple[ConversationSummary, ...],
        active_id: UUID | None,
    ) -> None:
        self._conversation_list.clear()
        active_text = None if active_id is None else str(active_id)
        for conversation in conversations:
            safe_title = sanitize_terminal_text(conversation.title)
            item = QListWidgetItem(safe_title)
            identifier = str(conversation.conversation_id)
            item.setData(Qt.ItemDataRole.UserRole, identifier)
            item.setToolTip(safe_title)
            self._conversation_list.addItem(item)
            if identifier == active_text:
                self._conversation_list.setCurrentItem(item)

    def show_new_conversation(self, *, private: bool) -> None:
        self._reset_transcript()
        self._conversation_list.clearSelection()
        self._status.setText(
            f"{self._base_status} · private, not saved"
            if private
            else f"{self._base_status} · new conversation"
        )

    def show_stored_conversation(self, conversation: StoredConversation) -> None:
        self._reset_transcript()
        for message in conversation.messages:
            if message.role is ConversationRole.USER:
                self.append_user(message.content)
            elif message.role is ConversationRole.ASSISTANT:
                self.apply_event(
                    ConversationEvent(
                        ConversationEventKind.ASSISTANT_CHUNK,
                        message.content,
                    )
                )
                self.apply_event(ConversationEvent(ConversationEventKind.COMPLETED))
            else:
                self.apply_event(
                    ConversationEvent(ConversationEventKind.NOTICE, message.content)
                )
        self._status.setText(self._base_status)

    def set_appearance(
        self,
        font_family: str,
        font_size: int,
        *,
        dark: bool,
    ) -> None:
        self._font_family = font_family
        self._font_size = font_size
        if dark:
            self._role_colors = {
                "You": "#7aa2ff",
                "Assistant": "#9ee6b8",
                "Notice": "#f0bd73",
            }
            self._body_color = "#e8eaf0"
            self._code_background = "#292f3a"
            self._code_color = "#d8e2ff"
        else:
            self._role_colors = {
                "You": "#315fd1",
                "Assistant": "#16724a",
                "Notice": "#8a5a16",
            }
            self._body_color = "#30333a"
            self._code_background = "#e7e9ee"
            self._code_color = "#273552"
        self._rerender_transcript()

    def _reset_transcript(self) -> None:
        self._transcript.clear()
        self._transcript.document().setMaximumBlockCount(MAX_TRANSCRIPT_BLOCKS)
        self._assistant_open = False
        self._assistant_start = None
        self._assistant_raw = []
        self._display_messages = []

    def _record_display_message(
        self,
        role: ConversationRole,
        content: str,
    ) -> None:
        self._display_messages.append((role, content))
        if len(self._display_messages) > MAX_DISPLAY_MESSAGES:
            del self._display_messages[: -MAX_DISPLAY_MESSAGES]

    def _rerender_transcript(self) -> None:
        messages = tuple(self._display_messages)
        self._reset_transcript()
        for role, content in messages:
            if role is ConversationRole.USER:
                self.append_user(content, record=False)
            elif role is ConversationRole.ASSISTANT:
                self.apply_event(
                    ConversationEvent(
                        ConversationEventKind.ASSISTANT_CHUNK,
                        content,
                    ),
                    record=False,
                )
                self.apply_event(
                    ConversationEvent(ConversationEventKind.COMPLETED),
                    record=False,
                )
            else:
                self.apply_event(
                    ConversationEvent(ConversationEventKind.NOTICE, content),
                    record=False,
                )
        self._display_messages = list(messages)

    @Slot(QListWidgetItem)
    def _conversation_clicked(self, item: QListWidgetItem) -> None:
        identifier = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(identifier, str):
            self.conversation_requested.emit(identifier)

    @Slot()
    def _delete_selected(self) -> None:
        item = self._conversation_list.currentItem()
        if item is None:
            return
        identifier = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(identifier, str):
            self.delete_requested.emit(identifier)

    @Slot()
    def _submit(self) -> None:
        text = self._input.toPlainText()
        if not text.strip():
            return
        if len(text) > MAX_VISIBLE_MESSAGE_CHARS:
            self.apply_event(
                ConversationEvent(
                    ConversationEventKind.NOTICE,
                    "That message is too large for the interface. Shorten it and "
                    "try again.",
                )
            )
            return
        response_limit = int(self._limit.currentData())
        self._input.clear()
        self.append_user(text)
        self.message_requested.emit(text, response_limit)

    def _append_role(self, label: str) -> None:
        role_format = QTextCharFormat()
        role_format.setForeground(QColor(self._role_colors[label]))
        role_format.setFontWeight(QFont.Weight.DemiBold)
        role_format.setFontPointSize(max(MIN_UI_FONT_SIZE, self._font_size - 2))
        role_format.setFontFamilies([self._font_family])
        self._append_with_format(f"{label}\n", role_format)

    def _append_plain(self, text: str, *, italic: bool = False) -> None:
        body_format = self._body_format()
        body_format.setFontItalic(italic)
        self._append_with_format(text, body_format)

    def _append_with_format(
        self,
        text: str,
        character_format: QTextCharFormat,
    ) -> None:
        cursor = self._transcript.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(text, character_format)
        self._transcript.setTextCursor(cursor)
        self._transcript.ensureCursorVisible()

    def _finish_assistant(self, *, record: bool = True) -> None:
        start = self._assistant_start
        if start is None:
            self._assistant_open = False
            return
        cursor = QTextCursor(self._transcript.document())
        cursor.setPosition(start)
        cursor.setPosition(
            self._transcript.document().characterCount() - 1,
            QTextCursor.MoveMode.KeepAnchor,
        )
        cursor.removeSelectedText()
        assistant_text = "".join(self._assistant_raw)
        self._insert_safe_markdown(cursor, assistant_text)
        cursor.insertText("\n\n", self._body_format())
        self._transcript.setTextCursor(cursor)
        self._transcript.ensureCursorVisible()
        self._transcript.document().setMaximumBlockCount(MAX_TRANSCRIPT_BLOCKS)
        self._assistant_open = False
        self._assistant_start = None
        self._assistant_raw = []
        if record:
            self._record_display_message(
                ConversationRole.ASSISTANT,
                assistant_text,
            )

    def _insert_safe_markdown(self, cursor: QTextCursor, text: str) -> None:
        """Apply a small inert Markdown subset through native text formats."""

        lines = text.split("\n")
        for index, line in enumerate(lines):
            heading = HEADING_MARKUP.fullmatch(line)
            bullet = BULLET_MARKUP.fullmatch(line)
            numbered = NUMBERED_MARKUP.fullmatch(line)
            if heading is not None:
                heading_format = self._body_format()
                heading_format.setFontWeight(QFont.Weight.Bold)
                heading_format.setFontPointSize(
                    self._font_size + max(1, 5 - (2 * len(heading.group(1))))
                )
                cursor.insertText(heading.group(2), heading_format)
            elif bullet is not None:
                bullet_format = self._body_format()
                bullet_format.setForeground(QColor(self._role_colors["Assistant"]))
                cursor.insertText("• ", bullet_format)
                self._insert_inline(cursor, bullet.group(1))
            elif numbered is not None:
                number_format = self._body_format()
                number_format.setForeground(QColor(self._role_colors["Assistant"]))
                cursor.insertText(f"{numbered.group(1)}. ", number_format)
                self._insert_inline(cursor, numbered.group(2))
            else:
                self._insert_inline(cursor, line)
            if index < len(lines) - 1:
                cursor.insertText("\n", self._body_format())

    def _insert_inline(self, cursor: QTextCursor, text: str) -> None:
        position = 0
        for match in INLINE_MARKUP.finditer(text):
            cursor.insertText(text[position : match.start()], self._body_format())
            token = match.group(0)
            token_format = self._body_format()
            if token.startswith("**"):
                token_format.setFontWeight(QFont.Weight.Bold)
                cursor.insertText(token[2:-2], token_format)
            else:
                token_format.setFontFamilies([CODE_FONT_FAMILY])
                token_format.setBackground(QColor(self._code_background))
                token_format.setForeground(QColor(self._code_color))
                cursor.insertText(token[1:-1], token_format)
            position = match.end()
        cursor.insertText(text[position:], self._body_format())

    def _body_format(self) -> QTextCharFormat:
        body_format = QTextCharFormat()
        body_format.setForeground(QColor(self._body_color))
        body_format.setFontPointSize(self._font_size)
        body_format.setFontFamilies([self._font_family])
        return body_format


class _StartupWorker(QObject):
    succeeded = Signal(object)
    recovery_required = Signal()
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        factory: AssistantApplicationFactory,
        mode: str,
        secrets: tuple[str, ...] = (),
    ) -> None:
        super().__init__()
        self._factory = factory
        self._mode = mode
        self._secrets = secrets
        self._cancelled = Event()

    def cancel(self) -> None:
        self._cancelled.set()

    @Slot()
    def run(self) -> None:
        service: AssistantApplicationService | None = None
        try:
            if self._mode == "setup":
                recovery, recovery_confirmation, passcode, passcode_confirmation = (
                    self._secrets
                )
                self._factory.setup(
                    recovery,
                    recovery_confirmation,
                    passcode,
                    passcode_confirmation,
                )
                service = self._factory.open(recovery)
            elif self._mode == "unlock":
                service = self._factory.open(self._secrets[0])
            elif self._mode == "automatic":
                service = self._factory.open()
            else:
                service = self._factory.open(session_only=True)
            if self._cancelled.is_set():
                service.close()
            else:
                self.succeeded.emit(service)
                service = None
        except ApplicationRecoveryRequired:
            self.recovery_required.emit()
        except ApplicationServiceError as error:
            self.failed.emit(str(error))
        finally:
            self._secrets = ()
            if service is not None:
                service.close()
            self.finished.emit()


class _ChatWorker(QObject):
    event_ready = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        service: AssistantApplicationService,
        text: str,
        response_limit: int,
    ) -> None:
        super().__init__()
        self._service = service
        self._text = text
        self._response_limit = response_limit

    @Slot()
    def run(self) -> None:
        try:
            for event in self._service.iter_events(
                self._text,
                max_response_tokens=self._response_limit,
            ):
                self.event_ready.emit(event)
        except ApplicationServiceError as error:
            self.failed.emit(str(error))
        finally:
            self._text = ""
            self.finished.emit()


class AssistantWindow(QMainWindow):
    def __init__(self, factory: AssistantApplicationFactory) -> None:
        super().__init__()
        self._factory = factory
        self._service: AssistantApplicationService | None = None
        self._startup_thread: QThread | None = None
        self._startup_worker: _StartupWorker | None = None
        self._chat_thread: QThread | None = None
        self._chat_worker: _ChatWorker | None = None
        self._closing = False
        self._appearance_preferences = factory.runtime_preferences
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(940, 720)
        self.setMinimumSize(720, 540)

        self._pages = QStackedWidget()
        self._welcome = WelcomePage()
        self._chat = ChatPage()
        self._settings = SettingsPage()
        self._pages.addWidget(self._welcome)
        self._pages.addWidget(self._chat)
        self._pages.addWidget(self._settings)
        self.setCentralWidget(self._pages)

        self._welcome.setup_requested.connect(self._start_setup)
        self._welcome.automatic_unlock_requested.connect(
            self._start_automatic_unlock
        )
        self._welcome.unlock_requested.connect(self._start_unlock)
        self._welcome.session_only_requested.connect(self._start_session_only)
        self._chat.message_requested.connect(self._start_message)
        self._chat.settings_requested.connect(self._show_settings)
        self._chat.new_chat_requested.connect(self._new_chat)
        self._chat.conversation_requested.connect(self._open_conversation)
        self._chat.delete_requested.connect(self._delete_conversation)
        self._settings.save_requested.connect(self._save_settings)
        self._settings.back_requested.connect(self._return_to_chat)
        QApplication.instance().styleHints().colorSchemeChanged.connect(
            self._system_theme_changed
        )
        self._apply_appearance(self._appearance_preferences)
        launch_state: ApplicationLaunchState | None = None
        try:
            launch_state = factory.launch_state()
            self._welcome.set_state(launch_state)
        except ApplicationOpenError as error:
            self._welcome.setEnabled(False)
            self._show_safe_error(str(error))
        if launch_state is ApplicationLaunchState.AUTOMATIC_UNLOCK:
            self._start_automatic_unlock()

    @Slot(str, str, str, str)
    def _start_setup(
        self,
        recovery: str,
        recovery_confirmation: str,
        passcode: str,
        passcode_confirmation: str,
    ) -> None:
        self._start_application(
            "setup",
            (recovery, recovery_confirmation, passcode, passcode_confirmation),
        )

    @Slot(str)
    def _start_unlock(self, recovery: str) -> None:
        self._start_application("unlock", (recovery,))

    @Slot()
    def _start_automatic_unlock(self) -> None:
        self._start_application("automatic", ())

    @Slot()
    def _start_session_only(self) -> None:
        self._start_application("session", ())

    def _start_application(self, mode: str, secrets: tuple[str, ...]) -> None:
        if self._startup_thread is not None:
            return
        self._welcome.set_busy(True)
        thread = QThread(self)
        worker = _StartupWorker(self._factory, mode, secrets)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._application_started)
        worker.recovery_required.connect(self._recovery_required)
        worker.failed.connect(self._startup_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._startup_finished)
        self._startup_thread = thread
        self._startup_worker = worker
        thread.start()

    @Slot(object)
    def _application_started(self, service: AssistantApplicationService) -> None:
        if self._closing:
            service.close()
            return
        self._service = service
        self._chat.configure_session(
            service.info.model_name,
            service.info.persistent_memory,
            service.info.default_response_tokens,
            service.info.long_response_tokens,
            service.info.maximum_response_tokens,
        )
        self._chat.show_new_conversation(private=service.private_chat)
        self._refresh_history()
        for notice in service.info.startup_notices:
            self._chat.apply_event(
                ConversationEvent(ConversationEventKind.NOTICE, notice)
            )
        self._pages.setCurrentWidget(self._chat)
        self._chat.set_busy(False)

    @Slot(str)
    def _startup_failed(self, message: str) -> None:
        if not self._closing:
            self._show_safe_error(message)
            try:
                self._welcome.set_state(self._factory.launch_state())
            except ApplicationOpenError as error:
                self._welcome.setEnabled(False)
                self._show_safe_error(str(error))
            else:
                self._welcome.setEnabled(True)
                self._welcome.set_busy(False)

    @Slot()
    def _recovery_required(self) -> None:
        if not self._closing:
            self._welcome.set_state(ApplicationLaunchState.UNLOCK_REQUIRED)
            self._welcome.setEnabled(True)
            self._welcome.set_busy(False)

    @Slot()
    def _startup_finished(self) -> None:
        if self._startup_thread is not None:
            self._startup_thread.deleteLater()
        self._startup_thread = None
        self._startup_worker = None
        self._finish_close_if_ready()

    @Slot(str, int)
    def _start_message(self, text: str, response_limit: int) -> None:
        if self._service is None or self._chat_thread is not None:
            return
        self._chat.set_busy(True)
        thread = QThread(self)
        worker = _ChatWorker(self._service, text, response_limit)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.event_ready.connect(self._chat.apply_event)
        worker.failed.connect(self._chat_failure)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._chat_finished)
        self._chat_thread = thread
        self._chat_worker = worker
        thread.start()

    @Slot(str)
    def _chat_failure(self, message: str) -> None:
        self._chat.apply_event(
            ConversationEvent(ConversationEventKind.NOTICE, message)
        )

    @Slot()
    def _chat_finished(self) -> None:
        if self._chat_thread is not None:
            self._chat_thread.deleteLater()
        self._chat_thread = None
        self._chat_worker = None
        if not self._closing:
            self._refresh_history()
            self._chat.set_busy(False)
        self._finish_close_if_ready()

    @Slot()
    def _show_settings(self) -> None:
        self._settings.set_preferences(self._factory.runtime_preferences)
        self._pages.setCurrentWidget(self._settings)

    @Slot(int, int, int, str, str, int)
    def _save_settings(
        self,
        context_tokens: int,
        default_response_tokens: int,
        maximum_response_tokens: int,
        theme: str,
        font_family: str,
        font_size: int,
    ) -> None:
        try:
            preferences = RuntimePreferences(
                context_tokens=context_tokens,
                default_response_tokens=default_response_tokens,
                maximum_response_tokens=maximum_response_tokens,
                theme=ThemePreference(theme),
                font_family=font_family,
                font_size=font_size,
            )
            self._factory.save_runtime_preferences(preferences)
        except (ValueError, ApplicationSettingsError) as error:
            self._show_safe_error(str(error))
            return
        self._apply_appearance(preferences)
        self._settings.show_saved()

    @Slot(bool)
    def _new_chat(self, private: bool) -> None:
        if self._service is None or self._chat_thread is not None:
            return
        try:
            self._service.new_conversation(private=private)
        except ApplicationOpenError as error:
            self._show_safe_error(str(error))
            return
        self._chat.show_new_conversation(private=self._service.private_chat)
        self._refresh_history()

    @Slot(str)
    def _open_conversation(self, identifier: str) -> None:
        if self._service is None or self._chat_thread is not None:
            return
        try:
            conversation = self._service.open_conversation(UUID(identifier))
        except (ValueError, ApplicationOpenError) as error:
            message = (
                str(error)
                if isinstance(error, ApplicationOpenError)
                else "The selected conversation identifier is invalid."
            )
            self._show_safe_error(message)
            return
        self._chat.show_stored_conversation(conversation)
        self._refresh_history()

    @Slot(str)
    def _delete_conversation(self, identifier: str) -> None:
        if self._service is None or self._chat_thread is not None:
            return
        answer = QMessageBox.question(
            self,
            WINDOW_TITLE,
            "Permanently delete this conversation from the live encrypted "
            "database? Existing encrypted backups retain it until they expire.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self._service.delete_conversation(UUID(identifier))
        except (ValueError, ApplicationOpenError) as error:
            message = (
                str(error)
                if isinstance(error, ApplicationOpenError)
                else "The selected conversation identifier is invalid."
            )
            self._show_safe_error(message)
            return
        self._chat.show_new_conversation(private=False)
        self._refresh_history()

    def _refresh_history(self) -> None:
        if self._service is None:
            return
        try:
            conversations = self._service.list_conversations()
        except ApplicationOpenError as error:
            self._show_safe_error(str(error))
            return
        self._chat.set_conversations(
            conversations,
            self._service.active_conversation_id,
        )

    @Slot()
    def _return_to_chat(self) -> None:
        self._pages.setCurrentWidget(self._chat)
        self._chat.set_busy(False)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._closing = True
        if self._startup_worker is not None:
            self._startup_worker.cancel()
        if self._startup_thread is not None or self._chat_thread is not None:
            if self._chat_thread is not None:
                self._pages.setCurrentWidget(self._chat)
                self._chat.show_closing()
            event.ignore()
            return
        self._close_service()
        event.accept()
        QApplication.instance().quit()

    def _finish_close_if_ready(self) -> None:
        if (
            self._closing
            and self._startup_thread is None
            and self._chat_thread is None
        ):
            self._close_service()
            self.hide()
            QApplication.instance().quit()

    def _close_service(self) -> None:
        if self._service is not None:
            self._service.close()
            self._service = None

    def _show_safe_error(self, message: str) -> None:
        QMessageBox.warning(self, WINDOW_TITLE, message)

    def _apply_appearance(self, preferences: RuntimePreferences) -> None:
        self._appearance_preferences = preferences
        installed_families = set(QFontDatabase.families())
        font_family = (
            preferences.font_family
            if preferences.font_family != "system"
            and preferences.font_family in installed_families
            else UI_FONT_FAMILY
        )
        QApplication.instance().setFont(QFont(font_family, preferences.font_size))
        if preferences.theme is ThemePreference.DARK:
            dark = True
        elif preferences.theme is ThemePreference.LIGHT:
            dark = False
        else:
            scheme = QApplication.instance().styleHints().colorScheme()
            dark = scheme is Qt.ColorScheme.Dark
            if scheme is Qt.ColorScheme.Unknown:
                dark = (
                    QApplication.instance().palette().window().color().lightness()
                    < 128
                )
        self._chat.set_appearance(
            font_family,
            preferences.font_size,
            dark=dark,
        )
        self._apply_styles(dark=dark, font_size=preferences.font_size)

    def _system_theme_changed(self, _scheme: object) -> None:
        if self._appearance_preferences.theme is ThemePreference.SYSTEM:
            self._apply_appearance(self._appearance_preferences)

    def _apply_styles(self, *, dark: bool, font_size: int) -> None:
        colors = (
            {
                "window": "#111318",
                "text": "#e8eaf0",
                "card": "#1b1f27",
                "border": "#303744",
                "field": "#151820",
                "field_border": "#394150",
                "primary": "#536dfe",
                "primary_hover": "#657cff",
                "disabled": "#343947",
                "disabled_text": "#858b99",
                "secondary_border": "#4b5568",
                "secondary_hover": "#252b36",
                "muted": "#aeb6c8",
                "selection": "#526cff",
                "sidebar": "#171a20",
            }
            if dark
            else {
                "window": "#f2f1ee",
                "text": "#30333a",
                "card": "#faf9f6",
                "border": "#d5d3ce",
                "field": "#fbfaf7",
                "field_border": "#c9c8c3",
                "primary": "#4668c8",
                "primary_hover": "#3759b5",
                "disabled": "#d9d8d4",
                "disabled_text": "#8a8985",
                "secondary_border": "#aaa9a4",
                "secondary_hover": "#e6e4df",
                "muted": "#666a73",
                "selection": "#7f9be0",
                "sidebar": "#e9e7e2",
            }
        )
        self.setStyleSheet(
            f"""
            QWidget {{ background: {colors['window']}; color: {colors['text']}; }}
            QLabel {{ background: transparent; }}
            #welcomeTitle {{ font-size: {font_size + 10}pt; font-weight: 650;
                             margin: 8px; }}
            #settingsTitle {{ font-size: {font_size + 7}pt; font-weight: 650;
                              margin: 8px; }}
            #historyTitle {{ font-size: {font_size + 3}pt; font-weight: 650; }}
            #historySidebar {{ background: {colors['sidebar']};
                              border-right: 1px solid {colors['border']}; }}
            #conversationList {{ background: transparent; border: 0; padding: 2px; }}
            #conversationList::item {{ border-radius: 7px; padding: 8px; }}
            #conversationList::item:selected {{ background: {colors['selection']}; }}
            #card {{ background: {colors['card']}; border: 1px solid {colors['border']};
                    border-radius: 14px; max-width: 620px; }}
            QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox {{
                background: %s; border: 1px solid %s;
                border-radius: 8px; padding: 8px; selection-background-color: %s;
            }}
            #transcript {{ padding: 12px; }}
            QPushButton {{ background: {colors['primary']}; border: 0;
                          border-radius: 8px; padding: 9px 14px; font-weight: 600; }}
            QPushButton:hover {{ background: {colors['primary_hover']}; }}
            QPushButton:disabled {{ background: {colors['disabled']};
                                    color: {colors['disabled_text']}; }}
            #secondaryButton {{ background: transparent;
                                border: 1px solid {colors['secondary_border']}; }}
            #secondaryButton:hover {{ background: {colors['secondary_hover']}; }}
            #sessionStatus {{ color: {colors['muted']}; }}
            """
            % (colors["field"], colors["field_border"], colors["selection"])
        )


def main() -> int:
    """Launch the native interface without creating a network-facing UI server."""

    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    app = QApplication(sys.argv)
    app.setApplicationName(WINDOW_TITLE)
    app.setOrganizationName("Personal Assistant")
    application_font = QFont(UI_FONT_FAMILY, 13)
    app.setFont(application_font)
    try:
        settings = load_desktop_settings()
        factory = AssistantApplicationFactory(
            settings,
            recovery_store=default_recovery_credential_store(
                settings.memory.data_directory
            ),
        )
    except (ValueError, ApplicationServiceError, RuntimePreferencesError):
        QMessageBox.critical(
            None,
            WINDOW_TITLE,
            "The assistant configuration is invalid. Check local settings.",
        )
        return 1
    window = AssistantWindow(factory)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
