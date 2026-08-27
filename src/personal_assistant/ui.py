"""Lean native PySide6 interface over the bounded application service."""

import os
from pathlib import Path
import re
import sys
from threading import Event
from time import monotonic
from uuid import UUID

from PySide6.QtCore import QDate, QObject, QThread, QTimer, Qt, Signal, Slot
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
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QHeaderView,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QInputDialog,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
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
    AuditInventoryPage,
    BackupOverview,
    MemoryInventoryItem,
    MemoryReviewItem,
    SearchServiceOverview,
)
from personal_assistant.assistant_preferences import (
    MAX_COMMUNICATION_STYLE_CHARS,
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
    MAX_UI_FONT_SIZE,
    MIN_INPUT_TOKENS,
    MIN_CONTEXT_TOKENS,
    MIN_UI_FONT_SIZE,
    RuntimePreferences,
    RuntimePreferencesError,
    SEARCH_IDLE_CHOICES_SECONDS,
    ThemePreference,
)
from personal_assistant.search_policy import SEARCH_SOURCE_LABELS, SearchSource
from personal_assistant.search_runtime import SearchRuntimeState
from personal_assistant.terminal_output import sanitize_terminal_text


WINDOW_TITLE = "Personal Assistant"
CHAT_RENDER_INTERVAL_SECONDS = 0.04
CHAT_RENDER_BATCH_CHARS = 256
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
THINKING_PHRASES = (
    "Thinking",
    "Thinking",
    "Pondering",
    "Connecting the dots",
    "Thinking",
)
CONTEXT_WINDOW_PRESETS: tuple[tuple[str, int], ...] = (
    ("8K", 8_192),
    ("16K", 16_384),
    ("32K", 32_768),
    ("64K", 65_536),
    ("128K", 131_072),
)


def _is_memory_stage_direction(text: str) -> bool:
    return text.startswith(
        (
            "Memory updated:",
            "Memory confirmed:",
            "Memory unchanged:",
            "Memory needs clarification:",
            "Memory needs confirmation:",
            "Memory not saved:",
        )
    )


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
    communication_style_save_requested = Signal(str)
    search_save_requested = Signal(int, object)
    search_start_requested = Signal()
    search_stop_requested = Signal()
    search_refresh_requested = Signal()
    memory_source_requested = Signal(str)
    memory_delete_requested = Signal(str)
    memory_next_page_requested = Signal(str)
    backup_directory_requested = Signal(str)
    backup_create_requested = Signal()
    backup_restore_requested = Signal(str)
    audit_next_page_requested = Signal(str)
    candidate_unlock_requested = Signal(str)
    candidate_reject_requested = Signal(str, int)
    candidate_apply_requested = Signal(str, int, str, str, int, str, str, str)
    back_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        navigation = QFrame()
        navigation.setObjectName("settingsSidebar")
        navigation.setFixedWidth(210)
        navigation_layout = QVBoxLayout(navigation)
        navigation_layout.setContentsMargins(16, 24, 16, 18)
        navigation_layout.setSpacing(12)
        navigation_title = QLabel("Settings")
        navigation_title.setObjectName("settingsNavigationTitle")
        navigation_layout.addWidget(navigation_title)
        self._section_list = QListWidget()
        self._section_list.setObjectName("settingsSectionList")
        self._section_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        memory_section = QListWidgetItem("Memory")
        memory_section.setData(Qt.ItemDataRole.UserRole, 0)
        communication_section = QListWidgetItem("Communication style")
        communication_section.setData(Qt.ItemDataRole.UserRole, 2)
        model_section = QListWidgetItem("Model & appearance")
        model_section.setData(Qt.ItemDataRole.UserRole, 3)
        search_section = QListWidgetItem("Web search")
        search_section.setData(Qt.ItemDataRole.UserRole, 4)
        backup_section = QListWidgetItem("Backups")
        backup_section.setData(Qt.ItemDataRole.UserRole, 5)
        audit_section = QListWidgetItem("Audit trail")
        audit_section.setData(Qt.ItemDataRole.UserRole, 6)
        self._section_list.addItem(memory_section)
        self._section_list.addItem(communication_section)
        self._section_list.addItem(model_section)
        self._section_list.addItem(search_section)
        self._section_list.addItem(backup_section)
        self._section_list.addItem(audit_section)
        navigation_layout.addWidget(self._section_list, 1)
        back = QPushButton("Back to chat")
        back.setObjectName("secondaryButton")
        back.clicked.connect(self.back_requested)
        navigation_layout.addWidget(back)
        layout.addWidget(navigation)

        self._section_pages = QStackedWidget()
        self._section_pages.addWidget(self._build_memory_page())
        self._section_pages.addWidget(self._build_memory_review_page())
        self._section_pages.addWidget(self._build_communication_page())
        self._section_pages.addWidget(self._build_model_page())
        self._section_pages.addWidget(self._build_search_page())
        self._section_pages.addWidget(self._build_backup_page())
        self._section_pages.addWidget(self._build_audit_page())
        layout.addWidget(self._section_pages, 1)
        self._section_list.currentItemChanged.connect(
            self._select_settings_section
        )
        self._configure_accessibility()
        self._section_list.setCurrentRow(0)

    def _configure_accessibility(self) -> None:
        self._section_list.setAccessibleName("Settings sections")
        self._section_list.setAccessibleDescription(
            "Choose Memory, Communication style, Model and appearance, "
            "Web search, Backups, or Audit trail."
        )
        self._memory_search.setAccessibleName("Search loaded memories")
        self._memory_table.setAccessibleName("Saved memories table")
        self._memory_load_more.setAccessibleName("Load more saved memories")
        self._communication_style.setAccessibleName(
            "Global assistant communication instructions"
        )
        self._context_tokens.setAccessibleName("Model context window")
        self._context_tokens.setAccessibleDescription(
            "Choose an exact context window of 8K, 16K, 32K, 64K, or 128K "
            "tokens."
        )
        self._default_response_tokens.setAccessibleName(
            "Default response token limit"
        )
        self._maximum_response_tokens.setAccessibleName(
            "Maximum response token ceiling"
        )
        self._search_idle.setAccessibleName("Search service idle timeout")
        self._search_start.setAccessibleName("Start local web search service")
        self._search_stop.setAccessibleName("Stop local web search service")
        self._search_refresh.setAccessibleName("Refresh web search status")
        self._backup_table.setAccessibleName("Managed encrypted backups table")
        self._backup_create.setAccessibleName("Create encrypted backup now")
        self._backup_restore.setAccessibleName(
            "Restore selected encrypted backup"
        )
        self._audit_table.setAccessibleName("Redacted audit events table")
        self._audit_load_more.setAccessibleName("Load older audit events")

    def _build_search_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(12)
        title = QLabel("Web search")
        title.setObjectName("settingsTitle")
        layout.addWidget(title)
        explanation = QLabel(
            "Search starts automatically when a question needs current public "
            "information. The model cannot operate or reconfigure the local "
            "search service itself."
        )
        explanation.setObjectName("settingsSubtitle")
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        status_card = QFrame()
        status_card.setObjectName("card")
        status_layout = QVBoxLayout(status_card)
        status_layout.setContentsMargins(22, 20, 22, 20)
        self._search_status = QLabel("Checking local search status…")
        self._search_status.setObjectName("settingsResult")
        self._search_status.setWordWrap(True)
        status_layout.addWidget(self._search_status)
        status_actions = QHBoxLayout()
        self._search_refresh = QPushButton("Refresh")
        self._search_refresh.setObjectName("secondaryButton")
        self._search_refresh.clicked.connect(self.search_refresh_requested)
        status_actions.addWidget(self._search_refresh)
        status_actions.addStretch()
        self._search_stop = QPushButton("Stop after current search")
        self._search_stop.setObjectName("secondaryButton")
        self._search_stop.clicked.connect(self.search_stop_requested)
        status_actions.addWidget(self._search_stop)
        self._search_start = QPushButton("Start search service")
        self._search_start.clicked.connect(self.search_start_requested)
        status_actions.addWidget(self._search_start)
        status_layout.addLayout(status_actions)
        layout.addWidget(status_card)

        preferences_card = QFrame()
        preferences_card.setObjectName("card")
        preferences_layout = QVBoxLayout(preferences_card)
        preferences_layout.setContentsMargins(22, 20, 22, 20)
        idle_row = QHBoxLayout()
        idle_row.addWidget(QLabel("Stop service after inactivity"))
        self._search_idle = QComboBox()
        for seconds in SEARCH_IDLE_CHOICES_SECONDS:
            minutes = seconds // 60
            self._search_idle.addItem(
                f"{minutes} minute" if minutes == 1 else f"{minutes} minutes",
                seconds,
            )
        idle_row.addStretch()
        idle_row.addWidget(self._search_idle)
        preferences_layout.addLayout(idle_row)
        providers_label = QLabel("Enabled quality sources")
        providers_label.setObjectName("communicationStylePrompt")
        preferences_layout.addWidget(providers_label)
        self._search_sources: dict[SearchSource, QCheckBox] = {}
        providers_grid = QGridLayout()
        providers_grid.setHorizontalSpacing(28)
        providers_grid.setVerticalSpacing(6)
        for index, (source, label) in enumerate(SEARCH_SOURCE_LABELS.items()):
            checkbox = QCheckBox(label)
            checkbox.setAccessibleName(f"Enable {label} search source")
            self._search_sources[source] = checkbox
            providers_grid.addWidget(checkbox, index // 2, index % 2)
        preferences_layout.addLayout(providers_grid)
        disclosure = QLabel(
            "Queries are sent through your local SearXNG service to the enabled "
            "public providers. Google Web and Google Scholar require no account "
            "or API key, but may rate-limit or block automated requests. Query "
            "text and results are not stored in the app audit trail."
        )
        disclosure.setObjectName("settingsSubtitle")
        disclosure.setWordWrap(True)
        preferences_layout.addWidget(disclosure)
        save_row = QHBoxLayout()
        self._search_result = QLabel()
        self._search_result.setObjectName("settingsResult")
        self._search_result.setWordWrap(True)
        save_row.addWidget(self._search_result, 1)
        self._search_save = QPushButton("Save search settings")
        self._search_save.clicked.connect(self._save_search_settings)
        save_row.addWidget(self._search_save)
        preferences_layout.addLayout(save_row)
        layout.addWidget(preferences_card, 1)
        return page

    def _build_backup_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(12)
        title = QLabel("Encrypted backups")
        title.setObjectName("settingsTitle")
        layout.addWidget(title)
        explanation = QLabel(
            "Choose one destination for managed encrypted snapshots. Backups "
            "remain encrypted with the same database key and are never opened "
            "by this screen."
        )
        explanation.setObjectName("settingsSubtitle")
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        destination_card = QFrame()
        destination_card.setObjectName("card")
        destination_layout = QVBoxLayout(destination_card)
        destination_layout.setContentsMargins(22, 20, 22, 20)
        destination_title = QLabel("Backup destination")
        destination_title.setObjectName("communicationStylePrompt")
        destination_layout.addWidget(destination_title)
        destination_row = QHBoxLayout()
        self._backup_directory = QLineEdit()
        self._backup_directory.setReadOnly(True)
        self._backup_directory.setPlaceholderText("No backup folder selected")
        self._backup_directory.setAccessibleName("Current backup destination")
        destination_row.addWidget(self._backup_directory, 1)
        self._backup_choose = QPushButton("Choose folder")
        self._backup_choose.setObjectName("secondaryButton")
        self._backup_choose.setAccessibleName("Choose encrypted backup folder")
        self._backup_choose.clicked.connect(self._choose_backup_directory)
        destination_row.addWidget(self._backup_choose)
        destination_layout.addLayout(destination_row)
        layout.addWidget(destination_card)

        snapshots_card = QFrame()
        snapshots_card.setObjectName("card")
        snapshots_layout = QVBoxLayout(snapshots_card)
        snapshots_layout.setContentsMargins(22, 20, 22, 20)
        snapshots_title = QLabel("Managed snapshots")
        snapshots_title.setObjectName("communicationStylePrompt")
        snapshots_layout.addWidget(snapshots_title)
        self._backup_table = QTableWidget(0, 3)
        self._backup_table.setObjectName("backupTable")
        self._backup_table.setHorizontalHeaderLabels(
            ("Created", "Size", "Snapshot")
        )
        self._backup_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._backup_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._backup_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self._backup_table.setAlternatingRowColors(True)
        self._backup_table.setShowGrid(False)
        self._backup_table.verticalHeader().setVisible(False)
        backup_header = self._backup_table.horizontalHeader()
        backup_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        backup_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        backup_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._backup_table.itemSelectionChanged.connect(
            self._backup_selection_changed
        )
        snapshots_layout.addWidget(self._backup_table, 1)
        warning = QLabel(
            "Restore replaces the live encrypted database. It requires typing "
            "RESTORE and your high-risk passcode; a safety snapshot is created "
            "before replacement."
        )
        warning.setObjectName("settingsSubtitle")
        warning.setWordWrap(True)
        snapshots_layout.addWidget(warning)
        actions = QHBoxLayout()
        self._backup_status = QLabel("Backups are not configured.")
        self._backup_status.setObjectName("settingsResult")
        self._backup_status.setWordWrap(True)
        actions.addWidget(self._backup_status, 1)
        self._backup_restore = QPushButton("Restore selected")
        self._backup_restore.setObjectName("secondaryButton")
        self._backup_restore.setEnabled(False)
        self._backup_restore.clicked.connect(self._restore_selected_backup)
        actions.addWidget(self._backup_restore)
        self._backup_create = QPushButton("Create backup now")
        self._backup_create.setEnabled(False)
        self._backup_create.clicked.connect(self.backup_create_requested)
        actions.addWidget(self._backup_create)
        snapshots_layout.addLayout(actions)
        layout.addWidget(snapshots_card, 1)
        return page

    def _build_audit_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(12)
        title = QLabel("Audit trail")
        title.setObjectName("settingsTitle")
        layout.addWidget(title)
        explanation = QLabel(
            "Inspect recent security and lifecycle events. This view deliberately "
            "omits conversation text, memory values, prompts, file paths, and "
            "identifiers. It shows at most 1,000 recent events."
        )
        explanation.setObjectName("settingsSubtitle")
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        self._audit_table = QTableWidget(0, 5)
        self._audit_table.setObjectName("auditTable")
        self._audit_table.setHorizontalHeaderLabels(
            ("Time (UTC)", "Component", "Action", "Outcome", "Reason")
        )
        self._audit_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._audit_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._audit_table.setAlternatingRowColors(True)
        self._audit_table.setShowGrid(False)
        self._audit_table.verticalHeader().setVisible(False)
        audit_header = self._audit_table.horizontalHeader()
        audit_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        audit_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        audit_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        audit_header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        audit_header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self._audit_table, 1)
        footer = QHBoxLayout()
        self._audit_status = QLabel("0 audit events loaded")
        self._audit_status.setObjectName("sessionStatus")
        footer.addWidget(self._audit_status)
        footer.addStretch()
        self._audit_load_more = QPushButton("Load older events")
        self._audit_load_more.setObjectName("secondaryButton")
        self._audit_load_more.clicked.connect(self._load_more_audit_events)
        self._audit_load_more.hide()
        footer.addWidget(self._audit_load_more)
        layout.addLayout(footer)
        self._audit_next_cursor: str | None = None
        return page

    def _build_communication_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(12)
        title = QLabel("Communication style")
        title.setObjectName("settingsTitle")
        layout.addWidget(title)
        explanation = QLabel(
            "Set a global preference for the assistant's tone, verbosity, "
            "formatting, and conversational manner. It applies to new replies "
            "in every chat."
        )
        explanation.setWordWrap(True)
        explanation.setObjectName("settingsSubtitle")
        layout.addWidget(explanation)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 22, 24, 22)
        prompt = QLabel("How should the assistant communicate with you?")
        prompt.setObjectName("communicationStylePrompt")
        card_layout.addWidget(prompt)
        self._communication_style = QPlainTextEdit()
        self._communication_style.setObjectName("communicationStyleInput")
        self._communication_style.setPlaceholderText(
            "Example: Be warm and direct. Use plain language, explain unfamiliar "
            "technical ideas, and keep routine answers concise."
        )
        self._communication_style.setTabChangesFocus(True)
        self._communication_style.setMinimumHeight(180)
        self._communication_style.textChanged.connect(
            self._communication_style_changed
        )
        card_layout.addWidget(self._communication_style)
        self._communication_count = QLabel(
            f"0 / {MAX_COMMUNICATION_STYLE_CHARS:,} characters"
        )
        self._communication_count.setObjectName("sessionStatus")
        card_layout.addWidget(self._communication_count)
        boundary = QLabel(
            "This preference is encrypted and revisioned. It can shape style, "
            "but cannot change safety rules, permissions, truthfulness, or tool "
            "authority. Leave it blank to restore the default style."
        )
        boundary.setWordWrap(True)
        boundary.setObjectName("settingsSubtitle")
        card_layout.addWidget(boundary)
        layout.addWidget(card)
        layout.addStretch()
        self._communication_result = QLabel()
        self._communication_result.setObjectName("settingsResult")
        self._communication_result.setWordWrap(True)
        layout.addWidget(self._communication_result)
        save_row = QHBoxLayout()
        save_row.addStretch()
        self._communication_save = QPushButton("Save communication style")
        self._communication_save.clicked.connect(
            lambda: self.communication_style_save_requested.emit(
                self._communication_style.toPlainText()
            )
        )
        save_row.addWidget(self._communication_save)
        layout.addLayout(save_row)
        return page

    def _build_model_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(12)
        title = QLabel("Model & appearance")
        title.setObjectName("settingsTitle")
        layout.addWidget(title)
        explanation = QLabel(
            "Adjust appearance and local model resource limits. Changes are "
            "validated and audited; model limits apply after restart."
        )
        explanation.setWordWrap(True)
        explanation.setObjectName("settingsSubtitle")
        layout.addWidget(explanation)

        card = QFrame()
        card.setObjectName("card")
        form = QFormLayout(card)
        form.setContentsMargins(28, 28, 28, 28)
        self._context_tokens = QComboBox()
        for label, token_count in CONTEXT_WINDOW_PRESETS:
            self._context_tokens.addItem(label, token_count)
        self._context_tokens.currentIndexChanged.connect(
            self._context_window_changed
        )
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
        layout.addStretch()
        self._result = QLabel()
        self._result.setObjectName("settingsResult")
        self._result.setWordWrap(True)
        layout.addWidget(self._result)
        save_row = QHBoxLayout()
        save_row.addStretch()
        save = QPushButton("Save settings")
        save.clicked.connect(self._save)
        save_row.addWidget(save)
        layout.addLayout(save_row)
        return page

    def _build_memory_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 28, 24, 28)
        layout.setSpacing(12)
        title = QLabel("Memory")
        title.setObjectName("settingsTitle")
        layout.addWidget(title)
        explanation = QLabel(
            "Review what the assistant currently remembers. Open the exact "
            "source message when available, or remove a memory from normal use."
        )
        explanation.setWordWrap(True)
        explanation.setObjectName("settingsSubtitle")
        layout.addWidget(explanation)

        self._memory_search = QLineEdit()
        self._memory_search.setPlaceholderText("Search loaded memories")
        self._memory_search.setClearButtonEnabled(True)
        self._memory_search.textChanged.connect(self._filter_memory_rows)
        layout.addWidget(self._memory_search)

        memory_splitter = QSplitter(Qt.Orientation.Horizontal)
        category_panel = QFrame()
        category_panel.setObjectName("memoryCategoryPanel")
        category_panel.setMinimumWidth(150)
        category_panel.setMaximumWidth(175)
        category_layout = QVBoxLayout(category_panel)
        category_layout.setContentsMargins(10, 12, 10, 12)
        category_title = QLabel("Categories")
        category_title.setObjectName("memoryCategoryTitle")
        category_layout.addWidget(category_title)
        self._memory_category = QListWidget()
        self._memory_category.setObjectName("memoryCategoryList")
        self._memory_category.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._memory_category.currentItemChanged.connect(
            lambda _current, _previous: self._filter_memory_rows()
        )
        category_layout.addWidget(self._memory_category, 1)
        memory_splitter.addWidget(category_panel)

        self._memory_table = QTableWidget(0, 5)
        self._memory_table.setObjectName("memoryTable")
        self._memory_table.setHorizontalHeaderLabels(
            ("Memory", "Type", "Status", "Updated", "Actions")
        )
        self._memory_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self._memory_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._memory_table.setAlternatingRowColors(True)
        self._memory_table.setShowGrid(False)
        self._memory_table.setWordWrap(False)
        self._memory_table.verticalHeader().setVisible(False)
        self._memory_table.verticalHeader().setDefaultSectionSize(38)
        header = self._memory_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3, 4):
            header.setSectionResizeMode(
                column,
                QHeaderView.ResizeMode.ResizeToContents,
            )
        memory_splitter.addWidget(self._memory_table)
        memory_splitter.setStretchFactor(0, 0)
        memory_splitter.setStretchFactor(1, 1)
        memory_splitter.setSizes((170, 720))
        layout.addWidget(memory_splitter, 1)
        page_footer = QHBoxLayout()
        self._memory_page_status = QLabel("0 memories loaded")
        self._memory_page_status.setObjectName("sessionStatus")
        page_footer.addWidget(self._memory_page_status)
        page_footer.addStretch()
        self._memory_load_more = QPushButton("Load more")
        self._memory_load_more.setObjectName("secondaryButton")
        self._memory_load_more.clicked.connect(self._load_more_memories)
        self._memory_load_more.hide()
        page_footer.addWidget(self._memory_load_more)
        layout.addLayout(page_footer)
        self._loaded_memories: tuple[MemoryInventoryItem, ...] = ()
        self._memory_next_cursor: str | None = None
        return page

    def _build_memory_review_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 28, 24, 28)
        layout.setSpacing(12)
        title = QLabel("Memory review")
        title.setObjectName("settingsTitle")
        layout.addWidget(title)
        explanation = QLabel(
            "Review automatic suggestions before they become established memory. "
            "You can edit and confirm, reject, correct a related memory, or record "
            "a dated change. Nothing here can grant the assistant authority."
        )
        explanation.setWordWrap(True)
        explanation.setObjectName("settingsSubtitle")
        layout.addWidget(explanation)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self._candidate_table = QTableWidget(0, 4)
        self._candidate_table.setObjectName("candidateTable")
        self._candidate_table.setHorizontalHeaderLabels(
            ("Suggestion", "Type", "Sensitivity", "Expires")
        )
        self._candidate_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self._candidate_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._candidate_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self._candidate_table.setAlternatingRowColors(True)
        self._candidate_table.setShowGrid(False)
        self._candidate_table.setWordWrap(False)
        self._candidate_table.verticalHeader().setVisible(False)
        self._candidate_table.verticalHeader().setDefaultSectionSize(38)
        candidate_header = self._candidate_table.horizontalHeader()
        candidate_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3):
            candidate_header.setSectionResizeMode(
                column,
                QHeaderView.ResizeMode.ResizeToContents,
            )
        self._candidate_table.itemSelectionChanged.connect(
            self._candidate_selected
        )
        splitter.addWidget(self._candidate_table)

        detail = QFrame()
        detail.setObjectName("card")
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(20, 20, 20, 20)
        detail_layout.setSpacing(10)
        detail_title = QLabel("Review decision")
        detail_title.setObjectName("communicationStylePrompt")
        detail_layout.addWidget(detail_title)
        self._candidate_editor = QPlainTextEdit()
        self._candidate_editor.setObjectName("candidateEditor")
        self._candidate_editor.setPlaceholderText(
            "Select a suggestion to inspect it."
        )
        self._candidate_editor.setMaximumHeight(130)
        self._candidate_editor.setTabChangesFocus(True)
        detail_layout.addWidget(self._candidate_editor)
        self._candidate_metadata = QLabel()
        self._candidate_metadata.setObjectName("settingsSubtitle")
        self._candidate_metadata.setWordWrap(True)
        detail_layout.addWidget(self._candidate_metadata)
        self._candidate_unlock = QPushButton("Unlock protected suggestion")
        self._candidate_unlock.setObjectName("secondaryButton")
        self._candidate_unlock.clicked.connect(self._unlock_candidate)
        self._candidate_unlock.hide()
        detail_layout.addWidget(self._candidate_unlock)

        decision_form = QFormLayout()
        self._candidate_decision = QComboBox()
        self._candidate_decision.addItem(
            "Confirm as an additional global memory",
            "confirm",
        )
        self._candidate_decision.addItem(
            "Correct the related current memory",
            "correct",
        )
        self._candidate_decision.addItem(
            "Record a change beginning on a date",
            "successor",
        )
        self._candidate_decision.currentIndexChanged.connect(
            self._candidate_decision_changed
        )
        decision_form.addRow("Decision", self._candidate_decision)
        self._candidate_target = QComboBox()
        decision_form.addRow("Related memory", self._candidate_target)
        self._candidate_date = QDateEdit(QDate.currentDate())
        self._candidate_date.setCalendarPopup(True)
        self._candidate_date.setDisplayFormat("yyyy-MM-dd")
        decision_form.addRow("Change date", self._candidate_date)
        detail_layout.addLayout(decision_form)

        scope_note = QLabel(
            "A true context-specific exception remains tentative for now. "
            "Enforceable named scopes require a future scope registry; this screen "
            "will not fake that boundary."
        )
        scope_note.setObjectName("settingsSubtitle")
        scope_note.setWordWrap(True)
        detail_layout.addWidget(scope_note)
        detail_layout.addStretch()
        self._candidate_result = QLabel()
        self._candidate_result.setObjectName("settingsResult")
        self._candidate_result.setWordWrap(True)
        detail_layout.addWidget(self._candidate_result)
        actions = QHBoxLayout()
        self._candidate_reject = QPushButton("Reject")
        self._candidate_reject.setObjectName("secondaryButton")
        self._candidate_reject.clicked.connect(self._reject_candidate)
        actions.addWidget(self._candidate_reject)
        actions.addStretch()
        self._candidate_apply = QPushButton("Apply reviewed decision")
        self._candidate_apply.clicked.connect(self._apply_candidate)
        actions.addWidget(self._candidate_apply)
        detail_layout.addLayout(actions)
        splitter.addWidget(detail)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes((560, 390))
        layout.addWidget(splitter, 1)
        self._memory_candidates: dict[str, MemoryReviewItem] = {}
        self._set_candidate_controls_enabled(False)
        return page

    @Slot(QListWidgetItem, QListWidgetItem)
    def _select_settings_section(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        if current is not None:
            self._section_pages.setCurrentIndex(
                int(current.data(Qt.ItemDataRole.UserRole))
            )

    def show_memory_page(self) -> None:
        self._section_list.setCurrentRow(0)

    def set_memory_candidates(
        self,
        candidates: tuple[MemoryReviewItem, ...],
    ) -> None:
        self._memory_candidates = {
            str(candidate.record_id): candidate for candidate in candidates
        }
        self._candidate_table.setRowCount(0)
        for candidate in candidates:
            row = self._candidate_table.rowCount()
            self._candidate_table.insertRow(row)
            value = QTableWidgetItem(candidate.value)
            value.setData(Qt.ItemDataRole.UserRole, str(candidate.record_id))
            value.setToolTip(candidate.value)
            self._candidate_table.setItem(row, 0, value)
            self._candidate_table.setItem(
                row,
                1,
                QTableWidgetItem(candidate.kind.replace("_", " ").title()),
            )
            self._candidate_table.setItem(
                row,
                2,
                QTableWidgetItem(candidate.sensitivity.title()),
            )
            self._candidate_table.setItem(
                row,
                3,
                QTableWidgetItem(candidate.expires_at or "—"),
            )
        self._candidate_result.setText(
            "No automatic suggestions await review."
            if not candidates
            else f"{len(candidates)} suggestion(s) await review."
        )
        self._candidate_editor.clear()
        self._candidate_metadata.clear()
        self._candidate_target.clear()
        self._candidate_unlock.hide()
        self._set_candidate_controls_enabled(False)

    def replace_unlocked_candidate(self, candidate: MemoryReviewItem) -> None:
        identifier = str(candidate.record_id)
        self._memory_candidates[identifier] = candidate
        for row in range(self._candidate_table.rowCount()):
            item = self._candidate_table.item(row, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == identifier:
                item.setText(candidate.value)
                item.setToolTip(candidate.value)
                self._candidate_table.selectRow(row)
                self._candidate_selected()
                return

    def show_candidate_result(self, text: str) -> None:
        self._candidate_result.setText(text)

    def _selected_candidate(self) -> MemoryReviewItem | None:
        row = self._candidate_table.currentRow()
        item = self._candidate_table.item(row, 0) if row >= 0 else None
        if item is None:
            return None
        return self._memory_candidates.get(
            str(item.data(Qt.ItemDataRole.UserRole))
        )

    @Slot()
    def _candidate_selected(self) -> None:
        candidate = self._selected_candidate()
        if candidate is None:
            self._set_candidate_controls_enabled(False)
            return
        self._candidate_editor.setPlainText(candidate.value if not candidate.locked else "")
        self._candidate_editor.setReadOnly(candidate.locked)
        self._candidate_metadata.setText(
            f"{candidate.kind.replace('_', ' ').title()} · "
            f"{candidate.sensitivity.title()} · "
            f"{candidate.mention_policy.replace('_', ' ')}"
        )
        self._candidate_unlock.setVisible(candidate.locked)
        self._candidate_target.clear()
        for related in candidate.related_confirmed:
            self._candidate_target.addItem(
                f"{related.value}  ·  updated {related.updated_at}",
                (str(related.record_id), related.row_version),
            )
        self._set_candidate_controls_enabled(not candidate.locked)
        self._candidate_decision_changed()

    def _set_candidate_controls_enabled(self, enabled: bool) -> None:
        self._candidate_editor.setEnabled(enabled)
        self._candidate_decision.setEnabled(enabled)
        self._candidate_reject.setEnabled(enabled)
        self._candidate_apply.setEnabled(enabled)
        self._candidate_target.setEnabled(enabled)
        self._candidate_date.setEnabled(enabled)

    @Slot()
    def _candidate_decision_changed(self) -> None:
        if not self._candidate_decision.isEnabled():
            return
        decision = str(self._candidate_decision.currentData())
        needs_target = decision in {"correct", "successor"}
        has_target = self._candidate_target.count() > 0
        self._candidate_target.setEnabled(needs_target and has_target)
        self._candidate_date.setEnabled(decision == "successor" and has_target)
        self._candidate_apply.setEnabled(not needs_target or has_target)

    @Slot()
    def _unlock_candidate(self) -> None:
        candidate = self._selected_candidate()
        if candidate is not None and candidate.locked:
            self.candidate_unlock_requested.emit(str(candidate.record_id))

    @Slot()
    def _reject_candidate(self) -> None:
        candidate = self._selected_candidate()
        if candidate is None or candidate.locked:
            return
        answer = QMessageBox.question(
            self,
            WINDOW_TITLE,
            "Reject this suggestion? It will leave normal review and retrieval, "
            "while its encrypted revision and audit history remain.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.candidate_reject_requested.emit(
                str(candidate.record_id),
                candidate.row_version,
            )

    @Slot()
    def _apply_candidate(self) -> None:
        candidate = self._selected_candidate()
        if candidate is None or candidate.locked:
            return
        edited = self._candidate_editor.toPlainText().strip()
        if not edited:
            self._candidate_result.setText("A reviewed memory cannot be empty.")
            return
        decision = str(self._candidate_decision.currentData())
        target_id = ""
        target_version = 0
        target_value = ""
        if decision in {"correct", "successor"}:
            data = self._candidate_target.currentData()
            if not isinstance(data, tuple) or len(data) != 2:
                self._candidate_result.setText(
                    "Select a current related memory before reconciling."
                )
                return
            target_id, target_version = str(data[0]), int(data[1])
            target_value = self._candidate_target.currentText().split("  ·  ")[0]
        effective_date = self._candidate_date.date().toString("yyyy-MM-dd")
        if decision == "confirm":
            preview = f"Confirm this as an additional global memory?\n\n{edited}"
        elif decision == "correct":
            preview = (
                "Correct the established memory below? The prior value remains in "
                f"revision history.\n\nCurrent: {target_value}\n\nNew: {edited}"
            )
        else:
            preview = (
                f"Record a dated change beginning {effective_date}?\n\n"
                f"Previous: {target_value}\n\nNew: {edited}"
            )
        answer = QMessageBox.question(
            self,
            WINDOW_TITLE,
            preview,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.candidate_apply_requested.emit(
            str(candidate.record_id),
            candidate.row_version,
            edited,
            target_id,
            target_version,
            decision,
            effective_date,
            candidate.sensitivity,
        )

    def set_communication_style(self, text: str, *, persistent: bool) -> None:
        self._communication_style.setPlainText(text)
        self._communication_style.setEnabled(persistent)
        self._communication_save.setEnabled(persistent)
        self._communication_result.setText(
            ""
            if persistent
            else "Encrypted memory is required to save a global style."
        )

    def show_communication_saved(self) -> None:
        self._communication_result.setText(
            "Communication style saved and applied to future replies."
        )

    @Slot()
    def _choose_backup_directory(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Choose encrypted backup folder",
            self._backup_directory.text(),
            QFileDialog.Option.ShowDirsOnly,
        )
        if selected:
            self.backup_directory_requested.emit(selected)

    def set_backups(self, overview: BackupOverview) -> None:
        self._backup_directory.setText(overview.directory)
        self._backup_table.setRowCount(0)
        for snapshot in overview.snapshots:
            row = self._backup_table.rowCount()
            self._backup_table.insertRow(row)
            created = QTableWidgetItem(snapshot.created_at.replace("T", " ")[:19])
            created.setData(Qt.ItemDataRole.UserRole, snapshot.snapshot_name)
            self._backup_table.setItem(row, 0, created)
            self._backup_table.setItem(
                row,
                1,
                QTableWidgetItem(self._format_byte_count(snapshot.byte_count)),
            )
            self._backup_table.setItem(
                row,
                2,
                QTableWidgetItem(
                    f"Managed snapshot · {snapshot.snapshot_name[24:32]}"
                ),
            )
            self._backup_table.item(row, 2).setToolTip(snapshot.snapshot_name)
        configured = bool(overview.directory)
        self._backup_create.setEnabled(configured)
        self._backup_restore.setEnabled(False)
        self._backup_status.setText(
            "Choose a destination to enable encrypted backups."
            if not configured
            else (
                "No managed snapshots yet."
                if not overview.snapshots
                else f"{len(overview.snapshots)} managed snapshot(s) available."
            )
        )

    def show_backup_result(self, text: str) -> None:
        self._backup_status.setText(text)

    def show_backup_loading(self, directory: str, text: str) -> None:
        self._backup_directory.setText(directory)
        self._backup_table.setRowCount(0)
        self._backup_create.setEnabled(False)
        self._backup_restore.setEnabled(False)
        self._backup_status.setText(text)

    def show_backup_error(self, directory: str, text: str) -> None:
        self._backup_directory.setText(directory)
        self._backup_table.setRowCount(0)
        self._backup_create.setEnabled(False)
        self._backup_restore.setEnabled(False)
        self._backup_status.setText(text)

    def set_audit_events(
        self,
        page: AuditInventoryPage,
        *,
        append: bool = False,
    ) -> None:
        if not append:
            self._audit_table.setRowCount(0)
        for event in page.items:
            row = self._audit_table.rowCount()
            self._audit_table.insertRow(row)
            values = (
                event.timestamp.replace("T", " ").replace("Z", "")[:19],
                event.component.replace("_", " ").title(),
                event.operation.replace("_", " ").title(),
                event.outcome.title(),
                event.reason_code.replace("_", " ").title(),
            )
            for column, value in enumerate(values):
                self._audit_table.setItem(row, column, QTableWidgetItem(value))
        self._audit_next_cursor = page.next_cursor
        self._audit_load_more.setVisible(page.next_cursor is not None)
        self._audit_status.setText(
            f"{self._audit_table.rowCount()} audit events loaded"
        )

    def show_audit_unavailable(self) -> None:
        """Explain why session-only users cannot inspect owner audit history."""

        self._audit_table.setRowCount(0)
        self._audit_next_cursor = None
        self._audit_load_more.hide()
        self._audit_status.setText(
            "Audit history is unavailable in session-only mode. "
            "Unlock persistent memory to view it."
        )

    @Slot()
    def _load_more_audit_events(self) -> None:
        if self._audit_next_cursor is not None:
            self.audit_next_page_requested.emit(self._audit_next_cursor)

    @Slot()
    def _backup_selection_changed(self) -> None:
        self._backup_restore.setEnabled(
            bool(self._backup_directory.text())
            and self._backup_table.currentRow() >= 0
        )

    @Slot()
    def _restore_selected_backup(self) -> None:
        row = self._backup_table.currentRow()
        item = self._backup_table.item(row, 0) if row >= 0 else None
        if item is not None:
            self.backup_restore_requested.emit(
                str(item.data(Qt.ItemDataRole.UserRole))
            )

    @staticmethod
    def _format_byte_count(byte_count: int) -> str:
        if byte_count < 1_024:
            return f"{byte_count} B"
        if byte_count < 1_048_576:
            return f"{byte_count / 1_024:.1f} KB"
        return f"{byte_count / 1_048_576:.1f} MB"

    @Slot()
    def _communication_style_changed(self) -> None:
        length = len(self._communication_style.toPlainText())
        self._communication_count.setText(
            f"{length:,} / {MAX_COMMUNICATION_STYLE_CHARS:,} characters"
        )
        self._communication_save.setEnabled(
            self._communication_style.isEnabled()
            and length <= MAX_COMMUNICATION_STYLE_CHARS
        )

    def set_preferences(self, preferences: RuntimePreferences) -> None:
        self._maximum_response_tokens.setValue(
            preferences.maximum_response_tokens
        )
        self._default_response_tokens.setValue(
            preferences.default_response_tokens
        )
        self._set_context_window_value(preferences.context_tokens)
        self._set_combo_value(self._theme, preferences.theme.value)
        self._set_combo_value(self._font_family, preferences.font_family)
        self._font_size.setValue(preferences.font_size)
        self._set_combo_value(
            self._search_idle,
            preferences.search_idle_seconds,
        )
        enabled = set(preferences.enabled_search_sources)
        for source, checkbox in self._search_sources.items():
            checkbox.setChecked(source in enabled)
        self._result.clear()
        self._search_result.clear()

    def set_search_overview(self, overview: SearchServiceOverview) -> None:
        labels = {
            SearchRuntimeState.UNAVAILABLE: "Unavailable",
            SearchRuntimeState.OFF: "Off",
            SearchRuntimeState.READY: "Ready",
            SearchRuntimeState.BUSY: "Busy — search in progress",
            SearchRuntimeState.STOPPING: "Stopping after the current search",
            SearchRuntimeState.CLOSED: "Closed",
        }
        self._search_status.setText(
            f"Local search service: {labels[overview.state]}. Idle timeout: "
            f"{overview.idle_seconds // 60} minute(s)."
        )
        can_start = overview.state in {
            SearchRuntimeState.OFF,
            SearchRuntimeState.UNAVAILABLE,
        }
        can_stop = overview.state in {
            SearchRuntimeState.READY,
            SearchRuntimeState.BUSY,
            SearchRuntimeState.STOPPING,
        }
        self._search_start.setEnabled(can_start)
        self._search_stop.setEnabled(can_stop)
        self._search_refresh.setEnabled(True)

    def show_search_loading(self, message: str) -> None:
        self._search_status.setText(message)
        self._search_start.setEnabled(False)
        self._search_stop.setEnabled(False)
        self._search_refresh.setEnabled(False)

    def show_search_result(self, message: str) -> None:
        self._search_result.setText(message)

    @Slot()
    def _save_search_settings(self) -> None:
        sources = tuple(
            source
            for source, checkbox in self._search_sources.items()
            if checkbox.isChecked()
        )
        if not sources:
            self._search_result.setText(
                "Enable at least one reviewed search source."
            )
            return
        self.search_save_requested.emit(
            int(self._search_idle.currentData()),
            sources,
        )

    def show_saved(self) -> None:
        self._result.setText(
            "Settings saved. Appearance is applied now; model limits apply after "
            "restart."
        )

    def set_memories(
        self,
        memories: tuple[MemoryInventoryItem, ...],
        *,
        next_cursor: str | None = None,
        append: bool = False,
    ) -> None:
        if append:
            existing_ids = {item.record_id for item in self._loaded_memories}
            existing_identities = {
                item.identity
                for item in self._loaded_memories
                if item.identity
            }
            self._loaded_memories += tuple(
                memory
                for memory in memories
                if memory.record_id not in existing_ids
                and (
                    not memory.identity
                    or memory.identity not in existing_identities
                )
            )
        else:
            self._loaded_memories = memories
        self._memory_next_cursor = next_cursor
        memories = self._loaded_memories
        self._memory_table.setRowCount(0)
        category_counts = {
            category: sum(memory.category == category for memory in memories)
            for category in sorted({memory.category for memory in memories})
        }
        selected_item = self._memory_category.currentItem()
        selected_category = (
            str(selected_item.data(Qt.ItemDataRole.UserRole))
            if selected_item is not None
            else ""
        )
        self._memory_category.blockSignals(True)
        self._memory_category.clear()
        all_categories = QListWidgetItem(f"All memories  {len(memories)}")
        all_categories.setData(Qt.ItemDataRole.UserRole, "")
        self._memory_category.addItem(all_categories)
        selected_row = 0
        for category, count in category_counts.items():
            item = QListWidgetItem(f"{category}  {count}")
            item.setData(Qt.ItemDataRole.UserRole, category)
            item.setToolTip(category)
            self._memory_category.addItem(item)
            if category == selected_category:
                selected_row = self._memory_category.count() - 1
        self._memory_category.setCurrentRow(selected_row)
        self._memory_category.blockSignals(False)
        for memory in memories:
            row = self._memory_table.rowCount()
            self._memory_table.insertRow(row)
            values = (
                sanitize_terminal_text(memory.value),
                (
                    "Observation"
                    if memory.kind == "insight"
                    else memory.kind.replace("_", " ").title()
                ),
                (
                    "Tentative"
                    if memory.status == "candidate"
                    else memory.status.title()
                ),
                memory.updated_at,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, str(memory.record_id))
                item.setData(
                    int(Qt.ItemDataRole.UserRole) + 1,
                    memory.category,
                )
                if column == 0:
                    item.setToolTip(value)
                self._memory_table.setItem(row, column, item)
            actions = QWidget()
            actions.setObjectName("memoryRowActions")
            action_layout = QHBoxLayout(actions)
            action_layout.setContentsMargins(0, 0, 0, 0)
            action_layout.setSpacing(3)
            source = QPushButton("Source")
            source.setObjectName("tableAction")
            source.clicked.connect(
                lambda _checked=False, identifier=str(memory.record_id):
                self.memory_source_requested.emit(identifier)
            )
            delete = QPushButton("Delete")
            delete.setObjectName("tableDeleteAction")
            delete.clicked.connect(
                lambda _checked=False, identifier=str(memory.record_id):
                self.memory_delete_requested.emit(identifier)
            )
            action_layout.addWidget(source)
            action_layout.addWidget(delete)
            self._memory_table.setCellWidget(row, 4, actions)
        self._filter_memory_rows()
        self._memory_page_status.setText(f"{len(memories)} memories loaded")
        self._memory_load_more.setVisible(next_cursor is not None)
        self._memory_load_more.setEnabled(next_cursor is not None)

    @Slot()
    def _load_more_memories(self) -> None:
        if self._memory_next_cursor is None:
            return
        self._memory_load_more.setEnabled(False)
        self.memory_next_page_requested.emit(self._memory_next_cursor)

    @Slot()
    def _filter_memory_rows(self) -> None:
        category_item = self._memory_category.currentItem()
        category = (
            str(category_item.data(Qt.ItemDataRole.UserRole))
            if category_item is not None
            else ""
        )
        query = self._memory_search.text().strip().casefold()
        for row in range(self._memory_table.rowCount()):
            first_item = self._memory_table.item(row, 0)
            row_category = str(
                first_item.data(int(Qt.ItemDataRole.UserRole) + 1)
            )
            searchable = " ".join(
                self._memory_table.item(row, column).text()
                for column in range(4)
            ).casefold()
            searchable = f"{row_category} {searchable}".casefold()
            visible = (not category or row_category == category) and (
                not query or query in searchable
            )
            self._memory_table.setRowHidden(row, not visible)

    @Slot()
    def _save(self) -> None:
        self.save_requested.emit(
            self._selected_context_tokens(),
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
    def _context_window_changed(self, _index: int) -> None:
        context_tokens = self._selected_context_tokens()
        self._maximum_response_tokens.setMaximum(
            min(2_000, context_tokens - MIN_INPUT_TOKENS)
        )

    def _selected_context_tokens(self) -> int:
        value = self._context_tokens.currentData()
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        return MIN_CONTEXT_TOKENS

    def _set_context_window_value(self, context_tokens: int) -> None:
        index = self._context_tokens.findData(context_tokens)
        if index < 0:
            index = min(
                range(self._context_tokens.count()),
                key=lambda candidate: abs(
                    int(self._context_tokens.itemData(candidate))
                    - context_tokens
                ),
            )
        self._context_tokens.setCurrentIndex(index)

    @staticmethod
    def _token_field(minimum: int, maximum: int, step: int) -> QSpinBox:
        field = QSpinBox()
        field.setRange(minimum, maximum)
        field.setSingleStep(step)
        field.setGroupSeparatorShown(True)
        field.setSuffix(" tokens")
        return field

    @staticmethod
    def _set_combo_value(combo: QComboBox, value: object) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(0 if index < 0 else index)


class ChatPage(QWidget):
    message_requested = Signal(str, int)
    stop_requested = Signal()
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
        self._stop = QPushButton("Stop")
        self._stop.setObjectName("secondaryButton")
        self._stop.setAccessibleName("Stop generating response")
        self._stop.clicked.connect(self._request_stop)
        self._stop.hide()
        composer.addWidget(self._stop)
        layout.addLayout(composer)
        self._assistant_open = False
        self._assistant_start: int | None = None
        self._assistant_raw: list[str] = []
        self._thinking_start: int | None = None
        self._thinking_frame = 0
        self._thinking_request_count = 0
        self._thinking_phrase = THINKING_PHRASES[0]
        self._thinking_timer = QTimer(self)
        self._thinking_timer.setInterval(450)
        self._thinking_timer.timeout.connect(self._advance_thinking)
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
        self._settings.setEnabled(True)
        self._new_chat.setEnabled(True)
        self._private_chat.setEnabled(True)
        self._conversation_list.setEnabled(True)
        self._delete_chat.setEnabled(not busy)
        self._stop.setVisible(busy)
        self._stop.setEnabled(busy)
        if not busy:
            self._input.setFocus()

    def show_response_ready(self) -> None:
        """Return the session header to its ready state after a worker exits."""

        self._status.setText(self._base_status)

    def show_closing(self) -> None:
        self.set_busy(True)
        self._settings.setEnabled(False)
        self._new_chat.setEnabled(False)
        self._private_chat.setEnabled(False)
        self._conversation_list.setEnabled(False)
        self._status.setText("Finishing the response and saving before close…")

    def show_background_generation(self) -> None:
        self._status.setText(
            f"{self._base_status} · another response is finishing in the background"
        )

    def append_user(self, text: str, *, record: bool = True) -> None:
        self._append_role("You")
        self._append_plain(f"{sanitize_terminal_text(text)}\n\n")
        if record:
            self._record_display_message(ConversationRole.USER, text)

    def apply_event(self, event: ConversationEvent, *, record: bool = True) -> None:
        self._stop_thinking()
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
            if not _is_memory_stage_direction(event.text):
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
        elif event.kind is ConversationEventKind.CANCELLED:
            if self._assistant_open:
                self._finish_assistant(record=record)
            notice = event.text or "Stopped by you."
            self._append_role("Notice")
            self._append_plain(f"{notice}\n\n", italic=True)
            if record:
                self._record_display_message(ConversationRole.NOTICE, notice)

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

    def show_stored_conversation(
        self,
        conversation: StoredConversation,
        *,
        highlight_sequence: int | None = None,
    ) -> None:
        self._reset_transcript()
        highlight_range: tuple[int, int] | None = None
        for message in conversation.messages:
            start = self._transcript.textCursor().position()
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
            if message.sequence == highlight_sequence:
                highlight_range = (
                    start,
                    self._transcript.textCursor().position(),
                )
        if highlight_range is not None:
            cursor = QTextCursor(self._transcript.document())
            cursor.setPosition(highlight_range[0])
            cursor.setPosition(
                highlight_range[1],
                QTextCursor.MoveMode.KeepAnchor,
            )
            selection = QTextEdit.ExtraSelection()
            selection.cursor = cursor
            selection.format.setBackground(QColor("#ffe28a"))
            selection.format.setForeground(QColor("#202124"))
            self._transcript.setExtraSelections([selection])
            self._transcript.setTextCursor(cursor)
            self._transcript.ensureCursorVisible()
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
        self._stop_thinking()
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
        self._start_thinking()
        self.message_requested.emit(text, response_limit)

    @Slot()
    def _request_stop(self) -> None:
        if not self._stop.isEnabled():
            return
        self._stop.setEnabled(False)
        self._status.setText(f"{self._base_status} · stopping response…")
        self.stop_requested.emit()

    def _start_thinking(self) -> None:
        self._stop_thinking()
        self._thinking_phrase = THINKING_PHRASES[
            self._thinking_request_count % len(THINKING_PHRASES)
        ]
        self._thinking_request_count += 1
        self._thinking_frame = 0
        self._thinking_start = self._transcript.textCursor().position()
        self._render_thinking()
        self._thinking_timer.start()

    @Slot()
    def _advance_thinking(self) -> None:
        if self._thinking_start is None:
            return
        self._thinking_frame = (self._thinking_frame + 1) % 3
        self._render_thinking()

    def _render_thinking(self) -> None:
        start = self._thinking_start
        if start is None:
            return
        cursor = QTextCursor(self._transcript.document())
        cursor.setPosition(start)
        cursor.setPosition(
            self._transcript.document().characterCount() - 1,
            QTextCursor.MoveMode.KeepAnchor,
        )
        cursor.removeSelectedText()
        dots = "." * (self._thinking_frame + 1)
        body_format = self._body_format()
        body_format.setFontItalic(True)
        cursor.insertText(f"{self._thinking_phrase}{dots}\n\n", body_format)
        self._transcript.setTextCursor(cursor)
        self._transcript.ensureCursorVisible()

    def _stop_thinking(self) -> None:
        self._thinking_timer.stop()
        start = self._thinking_start
        if start is None:
            return
        cursor = QTextCursor(self._transcript.document())
        cursor.setPosition(start)
        cursor.setPosition(
            self._transcript.document().characterCount() - 1,
            QTextCursor.MoveMode.KeepAnchor,
        )
        cursor.removeSelectedText()
        self._transcript.setTextCursor(cursor)
        self._thinking_start = None

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
        pending_chunks: list[str] = []
        pending_chars = 0
        last_emit = 0.0

        def emit_pending() -> None:
            nonlocal pending_chars, last_emit
            if not pending_chunks:
                return
            self.event_ready.emit(
                ConversationEvent(
                    ConversationEventKind.ASSISTANT_CHUNK,
                    "".join(pending_chunks),
                )
            )
            pending_chunks.clear()
            pending_chars = 0
            last_emit = monotonic()

        try:
            for event in self._service.iter_events(
                self._text,
                max_response_tokens=self._response_limit,
            ):
                if event.kind is ConversationEventKind.ASSISTANT_CHUNK:
                    pending_chunks.append(event.text)
                    pending_chars += len(event.text)
                    if (
                        monotonic() - last_emit >= CHAT_RENDER_INTERVAL_SECONDS
                        or pending_chars >= CHAT_RENDER_BATCH_CHARS
                    ):
                        emit_pending()
                else:
                    emit_pending()
                    self.event_ready.emit(event)
        except ApplicationServiceError as error:
            emit_pending()
            self.failed.emit(str(error))
        finally:
            emit_pending()
            self._text = ""
            self.finished.emit()


class _SearchWorker(QObject):
    succeeded = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        service: AssistantApplicationService,
        operation: str,
        idle_seconds: int = 120,
        sources: tuple[SearchSource, ...] = (),
    ) -> None:
        super().__init__()
        self._service = service
        self._operation = operation
        self._idle_seconds = idle_seconds
        self._sources = sources

    @Slot()
    def run(self) -> None:
        try:
            if self._operation == "start":
                overview = self._service.start_search_service()
            elif self._operation == "stop":
                overview = self._service.stop_search_service()
            elif self._operation == "configure":
                overview = self._service.configure_search(
                    self._idle_seconds,
                    self._sources,
                )
            else:
                overview = self._service.refresh_search_overview()
            self.succeeded.emit(overview)
        except ApplicationServiceError as error:
            self.failed.emit(str(error))
        finally:
            self._sources = ()
            self.finished.emit()


class _BackupWorker(QObject):
    """Run slow encrypted-backup operations outside the Qt presentation thread."""

    succeeded = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        factory: AssistantApplicationFactory,
        service: AssistantApplicationService,
        operation: str,
        arguments: tuple[str, ...] = (),
    ) -> None:
        super().__init__()
        self._factory = factory
        self._service = service
        self._operation = operation
        self._arguments = arguments

    @Slot()
    def run(self) -> None:
        try:
            if self._operation == "status":
                overview = self._service.list_backups()
            elif self._operation == "configure":
                destination = Path(self._arguments[0])
                self._service.configure_backup_directory(destination)
                self._factory.save_backup_directory(destination)
                overview = self._service.list_backups()
            elif self._operation == "create":
                self._service.create_backup()
                overview = self._service.list_backups()
            elif self._operation == "restore":
                self._service.restore_backup(
                    self._arguments[0],
                    self._arguments[1],
                    self._arguments[2],
                )
                overview = self._service.list_backups()
            else:
                raise ApplicationOpenError("The backup operation is invalid.")
            self.succeeded.emit(overview)
        except ApplicationServiceError as error:
            self.failed.emit(str(error))
        finally:
            self._arguments = ()
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
        self._deferred_chat_destination: tuple[str, UUID | bool] | None = None
        self._backup_thread: QThread | None = None
        self._backup_worker: _BackupWorker | None = None
        self._backup_action: str | None = None
        self._search_thread: QThread | None = None
        self._search_worker: _SearchWorker | None = None
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
        self._chat.stop_requested.connect(self._stop_message)
        self._chat.settings_requested.connect(self._show_settings)
        self._chat.new_chat_requested.connect(self._new_chat)
        self._chat.conversation_requested.connect(self._open_conversation)
        self._chat.delete_requested.connect(self._delete_conversation)
        self._settings.save_requested.connect(self._save_settings)
        self._settings.communication_style_save_requested.connect(
            self._save_communication_style
        )
        self._settings.search_save_requested.connect(self._save_search_settings)
        self._settings.search_start_requested.connect(
            lambda: self._start_search_task("start")
        )
        self._settings.search_stop_requested.connect(
            lambda: self._start_search_task("stop")
        )
        self._settings.search_refresh_requested.connect(
            lambda: self._start_search_task("status")
        )
        self._settings.memory_source_requested.connect(self._open_memory_source)
        self._settings.memory_delete_requested.connect(self._delete_memory)
        self._settings.memory_next_page_requested.connect(
            self._load_next_memory_page
        )
        self._settings.backup_directory_requested.connect(
            self._configure_backup_directory
        )
        self._settings.backup_create_requested.connect(self._create_backup)
        self._settings.backup_restore_requested.connect(self._restore_backup)
        self._settings.audit_next_page_requested.connect(
            self._load_next_audit_page
        )
        self._settings.candidate_unlock_requested.connect(
            self._unlock_memory_candidate
        )
        self._settings.candidate_reject_requested.connect(
            self._reject_memory_candidate
        )
        self._settings.candidate_apply_requested.connect(
            self._apply_memory_candidate
        )
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
        self._deferred_chat_destination = None
        self._chat.set_busy(True)
        thread = QThread(self)
        worker = _ChatWorker(self._service, text, response_limit)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.event_ready.connect(self._chat_event_ready)
        worker.failed.connect(self._chat_failure)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._chat_finished)
        self._chat_thread = thread
        self._chat_worker = worker
        thread.start()

    @Slot()
    def _stop_message(self) -> None:
        if self._service is not None and self._chat_thread is not None:
            self._service.cancel_active_response()

    @Slot(object)
    def _chat_event_ready(self, event: ConversationEvent) -> None:
        if self._deferred_chat_destination is None:
            self._chat.apply_event(event)

    @Slot(str)
    def _chat_failure(self, message: str) -> None:
        if self._deferred_chat_destination is None:
            self._chat.apply_event(
                ConversationEvent(ConversationEventKind.NOTICE, message)
            )
        else:
            self._show_safe_error(message)

    @Slot()
    def _chat_finished(self) -> None:
        if self._chat_thread is not None:
            self._chat_thread.deleteLater()
        self._chat_thread = None
        self._chat_worker = None
        if not self._closing:
            self._activate_deferred_chat_destination()
            self._chat.show_response_ready()
            self._chat.set_busy(False)
        self._finish_close_if_ready()

    def _activate_deferred_chat_destination(self) -> None:
        destination = self._deferred_chat_destination
        self._deferred_chat_destination = None
        if self._service is None:
            return
        if destination is None:
            self._refresh_history()
            return
        kind, value = destination
        try:
            if kind == "new":
                self._service.new_conversation(private=bool(value))
                self._chat.show_new_conversation(
                    private=self._service.private_chat
                )
            elif kind == "stored" and isinstance(value, UUID):
                conversation = self._service.open_conversation(value)
                self._chat.show_stored_conversation(conversation)
        except ApplicationOpenError as error:
            self._show_safe_error(str(error))
        self._refresh_history()

    @Slot()
    def _show_settings(self) -> None:
        self._settings.set_preferences(self._factory.runtime_preferences)
        self._settings.show_memory_page()
        self._pages.setCurrentWidget(self._settings)
        if self._service is not None:
            search_overview = getattr(self._service, "search_overview", None)
            if callable(search_overview):
                self._settings.set_search_overview(search_overview())
            else:
                self._settings.set_search_overview(
                    SearchServiceOverview(
                        SearchRuntimeState.UNAVAILABLE,
                        self._factory.runtime_preferences.search_idle_seconds,
                        (),
                    )
                )
            self._settings.set_communication_style(
                self._service.communication_style,
                persistent=self._service.info.persistent_memory,
            )
            try:
                page = self._service.list_memories_page()
                self._settings.set_memories(
                    page.items,
                    next_cursor=page.next_cursor,
                )
            except ApplicationOpenError as error:
                self._show_safe_error(str(error))
            if self._service.info.persistent_memory:
                try:
                    self._settings.set_audit_events(
                        self._service.list_audit_events()
                    )
                except ApplicationOpenError as error:
                    self._show_safe_error(str(error))
                directory = self._factory.runtime_preferences.backup_directory
                self._settings.show_backup_loading(
                    directory,
                    "Checking encrypted backup status…",
                )
                self._start_backup_task("status")
            else:
                self._settings.show_audit_unavailable()
                self._settings.set_backups(BackupOverview("", ()))

    @Slot(int, object)
    def _save_search_settings(self, idle_seconds: int, sources: object) -> None:
        if self._service is None:
            return
        try:
            selected = tuple(SearchSource(value) for value in sources)
            current = self._factory.runtime_preferences
            preferences = RuntimePreferences(
                context_tokens=current.context_tokens,
                default_response_tokens=current.default_response_tokens,
                maximum_response_tokens=current.maximum_response_tokens,
                theme=current.theme,
                font_family=current.font_family,
                font_size=current.font_size,
                backup_directory=current.backup_directory,
                search_idle_seconds=idle_seconds,
                enabled_search_sources=selected,
            )
            self._factory.save_runtime_preferences(preferences)
        except (TypeError, ValueError, ApplicationSettingsError) as error:
            self._show_safe_error(str(error))
            return
        self._start_search_task(
            "configure",
            idle_seconds=idle_seconds,
            sources=selected,
        )

    def _start_search_task(
        self,
        operation: str,
        *,
        idle_seconds: int = 120,
        sources: tuple[SearchSource, ...] = (),
    ) -> None:
        if self._service is None or self._search_thread is not None:
            return
        messages = {
            "start": "Starting the isolated local search service…",
            "stop": "Stopping search safely…",
            "configure": "Applying search settings…",
            "status": "Checking local search status…",
        }
        self._settings.show_search_loading(messages[operation])
        thread = QThread(self)
        worker = _SearchWorker(
            self._service,
            operation,
            idle_seconds,
            sources,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._search_task_succeeded)
        worker.failed.connect(self._search_task_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._search_task_finished)
        self._search_thread = thread
        self._search_worker = worker
        thread.start()

    @Slot(object)
    def _search_task_succeeded(self, overview: SearchServiceOverview) -> None:
        self._settings.set_search_overview(overview)
        self._settings.show_search_result("Search settings are active.")

    @Slot(str)
    def _search_task_failed(self, message: str) -> None:
        self._settings.show_search_result(message)
        if self._service is not None:
            self._settings.set_search_overview(self._service.search_overview())

    @Slot()
    def _search_task_finished(self) -> None:
        if self._search_thread is not None:
            self._search_thread.deleteLater()
        self._search_thread = None
        self._search_worker = None
        self._finish_close_if_ready()

    def _candidate_passcode(self, action: str) -> str | None:
        passcode, accepted = QInputDialog.getText(
            self,
            WINDOW_TITLE,
            f"High-risk passcode required to {action}:",
            QLineEdit.EchoMode.Password,
        )
        if not accepted or not passcode:
            passcode = ""
            return None
        return passcode

    @Slot(str)
    def _unlock_memory_candidate(self, identifier: str) -> None:
        if self._service is None:
            return
        passcode = self._candidate_passcode("review this protected suggestion")
        if passcode is None:
            return
        try:
            candidate = self._service.unlock_memory_candidate(
                UUID(identifier),
                passcode,
            )
        except (ValueError, ApplicationOpenError) as error:
            self._show_safe_error(
                str(error)
                if isinstance(error, ApplicationOpenError)
                else "The candidate identifier is invalid."
            )
            return
        finally:
            passcode = ""
        self._settings.replace_unlocked_candidate(candidate)

    @Slot(str, int)
    def _reject_memory_candidate(self, identifier: str, version: int) -> None:
        if self._service is None:
            return
        try:
            self._service.reject_memory_candidate(UUID(identifier), version)
            self._refresh_memory_settings(
                "Suggestion rejected; encrypted history was retained."
            )
        except (ValueError, ApplicationOpenError) as error:
            self._show_safe_error(
                str(error)
                if isinstance(error, ApplicationOpenError)
                else "The candidate identifier is invalid."
            )

    @Slot(str, int, str, str, int, str, str, str)
    def _apply_memory_candidate(
        self,
        identifier: str,
        version: int,
        edited_value: str,
        target_identifier: str,
        target_version: int,
        decision: str,
        effective_date: str,
        sensitivity: str,
    ) -> None:
        if self._service is None:
            return
        passcode: str | None = None
        if sensitivity in {"sensitive", "restricted"}:
            passcode = self._candidate_passcode("confirm this protected memory change")
            if passcode is None:
                return
        try:
            candidate_id = UUID(identifier)
            if decision == "confirm":
                self._service.confirm_memory_candidate(
                    candidate_id,
                    version,
                    edited_value,
                    high_risk_passcode=passcode,
                )
            else:
                self._service.reconcile_memory_candidate(
                    candidate_id,
                    version,
                    UUID(target_identifier),
                    target_version,
                    edited_value,
                    decision,
                    effective_date=effective_date,
                    high_risk_passcode=passcode,
                )
            self._refresh_memory_settings(
                "Reviewed decision applied with encrypted revision history."
            )
        except (ValueError, ApplicationOpenError) as error:
            self._show_safe_error(
                str(error)
                if isinstance(error, ApplicationOpenError)
                else "The reconciliation identifiers are invalid."
            )
        finally:
            passcode = ""

    def _refresh_memory_settings(self, result: str) -> None:
        if self._service is None:
            return
        try:
            page = self._service.list_memories_page()
            self._settings.set_memories(
                page.items,
                next_cursor=page.next_cursor,
            )
            self._settings.set_memory_candidates(
                self._service.list_memory_candidates()
            )
        except ApplicationOpenError as error:
            self._show_safe_error(str(error))
            return
        self._settings.show_candidate_result(result)

    @Slot(str)
    def _load_next_memory_page(self, cursor: str) -> None:
        if self._service is None:
            return
        try:
            page = self._service.list_memories_page(cursor)
            self._settings.set_memories(
                page.items,
                next_cursor=page.next_cursor,
                append=True,
            )
        except ApplicationOpenError as error:
            self._show_safe_error(str(error))

    @Slot(str)
    def _configure_backup_directory(self, selected: str) -> None:
        if self._service is None:
            return
        self._settings.show_backup_loading(
            selected,
            "Validating the backup destination…",
        )
        self._start_backup_task("configure", (selected,))

    @Slot()
    def _create_backup(self) -> None:
        if self._service is None:
            return
        self._settings.show_backup_result(
            "Creating and verifying the encrypted backup…"
        )
        self._start_backup_task("create")

    @Slot(str)
    def _restore_backup(self, snapshot_name: str) -> None:
        if self._service is None:
            return
        confirmation, accepted = QInputDialog.getText(
            self,
            WINDOW_TITLE,
            "Type RESTORE exactly to replace the live encrypted database:",
        )
        if not accepted or confirmation != "RESTORE":
            confirmation = ""
            return
        passcode = self._candidate_passcode("restore this encrypted backup")
        if passcode is None:
            confirmation = ""
            return
        self._settings.show_backup_result(
            "Verifying and restoring the encrypted backup…"
        )
        self._start_backup_task(
            "restore",
            (snapshot_name, confirmation, passcode),
        )
        confirmation = ""
        passcode = ""

    def _start_backup_task(
        self,
        operation: str,
        arguments: tuple[str, ...] = (),
    ) -> None:
        if self._service is None or self._backup_thread is not None:
            return
        self._settings.setEnabled(False)
        thread = QThread(self)
        worker = _BackupWorker(
            self._factory,
            self._service,
            operation,
            arguments,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._backup_succeeded)
        worker.failed.connect(self._backup_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._backup_finished)
        self._backup_action = operation
        self._backup_thread = thread
        self._backup_worker = worker
        thread.start()

    @Slot(object)
    def _backup_succeeded(self, overview: BackupOverview) -> None:
        action = self._backup_action
        self._settings.set_backups(overview)
        messages = {
            "status": (
                "No managed snapshots yet."
                if not overview.snapshots
                else f"{len(overview.snapshots)} managed snapshot(s) available."
            ),
            "configure": "Encrypted backup destination saved and active.",
            "create": "Encrypted backup created and fully verified.",
            "restore": (
                "Encrypted backup restored. Conversation and memory views refreshed."
            ),
        }
        self._settings.show_backup_result(
            messages.get(action or "", "Encrypted backup status updated.")
        )
        if action == "restore" and self._service is not None:
            try:
                page = self._service.list_memories_page()
                self._settings.set_memories(
                    page.items,
                    next_cursor=page.next_cursor,
                )
                self._refresh_history()
            except ApplicationOpenError as error:
                self._show_safe_error(str(error))

    @Slot(str)
    def _backup_failed(self, message: str) -> None:
        directory = self._factory.runtime_preferences.backup_directory
        self._settings.show_backup_error(
            directory,
            "Backup operation unavailable. Choose a present local or external "
            "folder and try again.",
        )
        self._show_safe_error(message)

    @Slot()
    def _backup_finished(self) -> None:
        if self._backup_thread is not None:
            self._backup_thread.deleteLater()
        self._backup_thread = None
        self._backup_worker = None
        self._backup_action = None
        if not self._closing:
            self._settings.setEnabled(True)
        self._finish_close_if_ready()

    @Slot(str)
    def _load_next_audit_page(self, cursor: str) -> None:
        if self._service is None:
            return
        try:
            self._settings.set_audit_events(
                self._service.list_audit_events(cursor),
                append=True,
            )
        except ApplicationOpenError as error:
            self._show_safe_error(str(error))

    @Slot(str)
    def _open_memory_source(self, identifier: str) -> None:
        if self._service is None or self._chat_thread is not None:
            return
        try:
            source = self._service.open_memory_source(UUID(identifier))
        except (ValueError, ApplicationOpenError) as error:
            message = (
                str(error)
                if isinstance(error, ApplicationOpenError)
                else "The selected memory identifier is invalid."
            )
            self._show_safe_error(message)
            return
        self._chat.show_stored_conversation(
            source.conversation,
            highlight_sequence=source.source_sequence,
        )
        self._pages.setCurrentWidget(self._chat)
        self._refresh_history()

    @Slot(str)
    def _delete_memory(self, identifier: str) -> None:
        if self._service is None or self._chat_thread is not None:
            return
        answer = QMessageBox.question(
            self,
            WINDOW_TITLE,
            "Delete this memory from normal use? Its revision history and the "
            "audited deletion event will remain available for recovery.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self._service.delete_memory(UUID(identifier))
            page = self._service.list_memories_page()
            self._settings.set_memories(
                page.items,
                next_cursor=page.next_cursor,
            )
        except (ValueError, ApplicationOpenError) as error:
            message = (
                str(error)
                if isinstance(error, ApplicationOpenError)
                else "The selected memory identifier is invalid."
            )
            self._show_safe_error(message)

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
                backup_directory=self._factory.runtime_preferences.backup_directory,
                search_idle_seconds=(
                    self._factory.runtime_preferences.search_idle_seconds
                ),
                enabled_search_sources=(
                    self._factory.runtime_preferences.enabled_search_sources
                ),
            )
            self._factory.save_runtime_preferences(preferences)
        except (ValueError, ApplicationSettingsError) as error:
            self._show_safe_error(str(error))
            return
        self._apply_appearance(preferences)
        self._settings.show_saved()

    @Slot(str)
    def _save_communication_style(self, text: str) -> None:
        if self._service is None:
            return
        try:
            self._service.save_communication_style(text)
        except ApplicationSettingsError as error:
            self._show_safe_error(str(error))
            return
        self._settings.show_communication_saved()

    @Slot(bool)
    def _new_chat(self, private: bool) -> None:
        if self._service is None:
            return
        if self._chat_thread is not None:
            self._deferred_chat_destination = ("new", private)
            self._chat.show_new_conversation(private=private)
            self._chat.set_busy(True)
            self._chat.show_background_generation()
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
        if self._service is None:
            return
        try:
            conversation_id = UUID(identifier)
            if self._chat_thread is not None:
                conversation = self._service.view_conversation(conversation_id)
                self._deferred_chat_destination = ("stored", conversation_id)
            else:
                conversation = self._service.open_conversation(conversation_id)
        except (ValueError, ApplicationOpenError) as error:
            message = (
                str(error)
                if isinstance(error, ApplicationOpenError)
                else "The selected conversation identifier is invalid."
            )
            self._show_safe_error(message)
            return
        self._chat.show_stored_conversation(conversation)
        if self._chat_thread is not None:
            self._chat.set_busy(True)
            self._chat.show_background_generation()
        else:
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
        self._chat.set_busy(self._chat_thread is not None)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._closing = True
        if self._startup_worker is not None:
            self._startup_worker.cancel()
        if (
            self._startup_thread is not None
            or self._chat_thread is not None
            or self._backup_thread is not None
            or self._search_thread is not None
        ):
            if self._chat_thread is not None:
                self._pages.setCurrentWidget(self._chat)
                self._chat.show_closing()
            elif self._backup_thread is not None:
                self._pages.setCurrentWidget(self._settings)
                self._settings.show_backup_result(
                    "Finishing the backup operation safely before closing…"
                )
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
            and self._backup_thread is None
            and self._search_thread is None
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
                              margin: 0; }}
            #settingsNavigationTitle {{ font-size: {font_size + 5}pt;
                                        font-weight: 650; margin: 4px 8px; }}
            #settingsSubtitle {{ color: {colors['muted']}; }}
            #historyTitle {{ font-size: {font_size + 3}pt; font-weight: 650; }}
            #historySidebar, #settingsSidebar {{ background: {colors['sidebar']};
                                                border-right: 1px solid {colors['border']}; }}
            #conversationList {{ background: transparent; border: 0; padding: 2px; }}
            #conversationList::item {{ border-radius: 7px; padding: 8px; }}
            #conversationList::item:selected {{ background: {colors['selection']}; }}
            #settingsSectionList, #memoryCategoryList {{ background: transparent;
                                                        border: 0; padding: 2px; }}
            #settingsSectionList::item, #memoryCategoryList::item {{
                border-radius: 7px; padding: 9px 8px;
            }}
            #settingsSectionList::item:selected, #memoryCategoryList::item:selected {{
                background: {colors['selection']};
            }}
            #memoryCategoryPanel {{ background: {colors['sidebar']};
                                    border: 1px solid {colors['border']};
                                    border-radius: 10px; }}
            #memoryCategoryTitle {{ font-weight: 650; padding: 3px 6px; }}
            #memoryTable, #candidateTable, #backupTable, #auditTable {{ background: {colors['card']};
                                             alternate-background-color: {colors['sidebar']};
                                             border: 1px solid {colors['border']};
                                             border-radius: 10px; }}
            #memoryTable QHeaderView::section,
            #candidateTable QHeaderView::section,
            #backupTable QHeaderView::section,
            #auditTable QHeaderView::section {{ background: {colors['sidebar']};
                                                    border: 0;
                                                    border-bottom: 1px solid {colors['border']};
                                                    padding: 8px; font-weight: 650; }}
            #memoryTable::item, #candidateTable::item,
            #backupTable::item, #auditTable::item {{ padding: 5px 7px; }}
            #memoryRowActions {{ background: transparent; }}
            #tableAction, #tableDeleteAction {{ padding: 5px 6px; }}
            #tableDeleteAction {{ background: transparent;
                                  border: 1px solid {colors['secondary_border']}; }}
            #tableDeleteAction:hover {{ background: {colors['secondary_hover']}; }}
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
