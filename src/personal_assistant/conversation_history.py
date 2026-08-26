"""Encrypted transcript persistence behind bounded typed operations."""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import re
from time import monotonic
from typing import Any, Callable
from uuid import UUID, uuid4

from personal_assistant.audit import (
    AuditComponent,
    AuditEvent,
    AuditMetadataItem,
    AuditMetadataKey,
    AuditOperation,
    AuditOutcome,
    AuditReasonCode,
    AuditSink,
)
from personal_assistant.encrypted_database import EncryptedConnectionProvider
from personal_assistant.session_memory import ConversationTurn


MAX_CONVERSATION_TITLE_CHARS = 160
MAX_HISTORY_MESSAGE_CHARS = 262_144
MAX_HISTORY_NOTICES_PER_TURN = 16
MAX_HISTORY_LIST_ITEMS = 200
MAX_HISTORY_LOAD_MESSAGES = 2_000
MAX_RECALL_QUERY_CHARS = 8_192
MAX_RECALL_CONVERSATIONS = 3
MAX_RECALL_MESSAGES_PER_CONVERSATION = 4
MAX_RECALL_MESSAGE_CHARS = 2_000
MAX_RECALL_SCAN_HITS = 96
_RECALL_TERM = re.compile(r"[\w'-]+", re.UNICODE)
_RECALL_STOP_WORDS = {
    "about",
    "ago",
    "and",
    "can",
    "chat",
    "conversation",
    "continue",
    "could",
    "did",
    "discuss",
    "discussed",
    "do",
    "from",
    "here",
    "in",
    "is",
    "it",
    "last",
    "left",
    "let's",
    "me",
    "month",
    "my",
    "off",
    "of",
    "on",
    "our",
    "past",
    "pick",
    "please",
    "previous",
    "remember",
    "talk",
    "talked",
    "that",
    "the",
    "then",
    "this",
    "to",
    "up",
    "was",
    "we",
    "week",
    "when",
    "where",
    "with",
    "you",
}


class ConversationHistoryError(RuntimeError):
    """A safe expected failure at the transcript repository boundary."""


class ConversationNotFoundError(ConversationHistoryError):
    pass


class ConversationRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    NOTICE = "notice"


@dataclass(frozen=True)
class ConversationSummary:
    conversation_id: UUID
    title: str
    updated_at: datetime


@dataclass(frozen=True)
class StoredConversationMessage:
    role: ConversationRole
    content: str
    sequence: int


@dataclass(frozen=True)
class ConversationResponseMessage:
    """One assistant or fixed-notice message in its visible order."""

    role: ConversationRole
    content: str

    def __post_init__(self) -> None:
        if self.role not in {ConversationRole.ASSISTANT, ConversationRole.NOTICE}:
            raise ConversationHistoryError("Conversation response role is invalid.")


@dataclass(frozen=True)
class StoredConversation:
    summary: ConversationSummary
    messages: tuple[StoredConversationMessage, ...]

    def completed_turns(self) -> tuple[ConversationTurn, ...]:
        """Return only adjacent completed exchanges suitable for model context."""

        turns: list[ConversationTurn] = []
        pending_user: str | None = None
        for message in self.messages:
            if message.role is ConversationRole.USER:
                pending_user = message.content
            elif (
                message.role is ConversationRole.ASSISTANT
                and pending_user is not None
            ):
                turns.append(ConversationTurn(pending_user, message.content))
                pending_user = None
        return tuple(turns)


@dataclass(frozen=True)
class ConversationRecallMatch:
    """One bounded transcript neighborhood returned by encrypted search."""

    summary: ConversationSummary
    messages: tuple[StoredConversationMessage, ...]


class ConversationHistoryRepository:
    """Store full transcripts without exposing connections to the UI or model."""

    def __init__(
        self,
        connection_provider: EncryptedConnectionProvider,
        audit_sink: AuditSink,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        if not isinstance(connection_provider, EncryptedConnectionProvider):
            raise TypeError("Conversation history requires an encrypted database.")
        if not isinstance(audit_sink, AuditSink):
            raise TypeError("Conversation history requires an audit sink.")
        self._connections = connection_provider
        self._audit_sink = audit_sink
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory

    def begin_turn(
        self,
        conversation_id: UUID | None,
        user_text: str,
        correlation_id: UUID,
    ) -> UUID:
        """Durably append a user message, creating its conversation if needed."""

        content = self._validated_content(user_text)
        active_id = self._new_id() if conversation_id is None else conversation_id
        self._require_uuid(active_id)
        timestamp = self._now().isoformat()
        started = self._start_audit(correlation_id, "conversation_turn_begin")
        try:
            with self._connections.connect(correlation_id) as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    if conversation_id is None:
                        connection.execute(
                            "INSERT INTO conversations (conversation_id, title, "
                            "created_at, updated_at, archived) VALUES (?, ?, ?, ?, 0)",
                            (
                                str(active_id),
                                self._title_for(content),
                                timestamp,
                                timestamp,
                            ),
                        )
                    else:
                        self._require_active(connection, active_id)
                    sequence = self._next_sequence(connection, active_id)
                    message_id = str(self._new_id())
                    connection.execute(
                        "INSERT INTO conversation_messages (message_id, "
                        "conversation_id, sequence, role, content, created_at) "
                        "VALUES (?, ?, ?, 'user', ?, ?)",
                        (
                            message_id,
                            str(active_id),
                            sequence,
                            content,
                            timestamp,
                        ),
                    )
                    connection.execute(
                        "INSERT INTO conversation_search (message_id, "
                        "conversation_id, sequence, role, content, created_at) "
                        "VALUES (?, ?, ?, 'user', ?, ?)",
                        (
                            message_id,
                            str(active_id),
                            sequence,
                            content,
                            timestamp,
                        ),
                    )
                    connection.execute(
                        "UPDATE conversations SET updated_at = ? "
                        "WHERE conversation_id = ?",
                        (timestamp, str(active_id)),
                    )
                    self._finish_audit(
                        correlation_id,
                        "conversation_turn_begin",
                        AuditOutcome.SUCCEEDED,
                        AuditReasonCode.NORMAL,
                        started,
                    )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
        except ConversationHistoryError:
            self._failed_audit(correlation_id, "conversation_turn_begin", started)
            raise
        except Exception as error:
            self._failed_audit(correlation_id, "conversation_turn_begin", started)
            raise ConversationHistoryError(
                "Conversation history could not be saved safely."
            ) from error
        return active_id

    def finish_turn(
        self,
        conversation_id: UUID,
        responses: tuple[ConversationResponseMessage, ...],
        correlation_id: UUID,
    ) -> None:
        """Durably append visible response content before reporting completion."""

        self._require_uuid(conversation_id)
        if not isinstance(responses, tuple) or not all(
            isinstance(response, ConversationResponseMessage)
            for response in responses
        ):
            raise ConversationHistoryError("Conversation responses are invalid.")
        if (
            sum(
                response.role is ConversationRole.NOTICE
                for response in responses
            )
            > MAX_HISTORY_NOTICES_PER_TURN
        ):
            raise ConversationHistoryError("Conversation notices are invalid.")
        safe_responses = tuple(
            ConversationResponseMessage(
                response.role,
                self._validated_content(response.content),
            )
            for response in responses
        )
        if not safe_responses:
            return
        timestamp = self._now().isoformat()
        started = self._start_audit(correlation_id, "conversation_turn_finish")
        try:
            with self._connections.connect(correlation_id) as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    self._require_active(connection, conversation_id)
                    sequence = self._next_sequence(connection, conversation_id)
                    values: list[tuple[str, str, int, str, str, str]] = []
                    search_values: list[tuple[str, str, int, str, str, str]] = []
                    for response in safe_responses:
                        value = (
                            str(self._new_id()),
                            str(conversation_id),
                            sequence,
                            response.role.value,
                            response.content,
                            timestamp,
                        )
                        values.append(value)
                        if response.role is ConversationRole.ASSISTANT:
                            search_values.append(value)
                        sequence += 1
                    connection.executemany(
                        "INSERT INTO conversation_messages (message_id, "
                        "conversation_id, sequence, role, content, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        values,
                    )
                    if search_values:
                        connection.executemany(
                            "INSERT INTO conversation_search (message_id, "
                            "conversation_id, sequence, role, content, created_at) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                            search_values,
                        )
                    connection.execute(
                        "UPDATE conversations SET updated_at = ? "
                        "WHERE conversation_id = ?",
                        (timestamp, str(conversation_id)),
                    )
                    self._finish_audit(
                        correlation_id,
                        "conversation_turn_finish",
                        AuditOutcome.SUCCEEDED,
                        AuditReasonCode.NORMAL,
                        started,
                    )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
        except ConversationHistoryError:
            self._failed_audit(correlation_id, "conversation_turn_finish", started)
            raise
        except Exception as error:
            self._failed_audit(correlation_id, "conversation_turn_finish", started)
            raise ConversationHistoryError(
                "Conversation history could not be saved safely."
            ) from error

    def list_conversations(
        self,
        correlation_id: UUID,
        *,
        limit: int = MAX_HISTORY_LIST_ITEMS,
    ) -> tuple[ConversationSummary, ...]:
        if isinstance(limit, bool) or not 1 <= limit <= MAX_HISTORY_LIST_ITEMS:
            raise ValueError("Conversation list limit is invalid.")
        started = self._start_audit(correlation_id, "conversation_list")
        try:
            with self._connections.connect(correlation_id) as connection:
                rows = connection.execute(
                    "SELECT conversation_id, title, updated_at FROM conversations "
                    "WHERE archived = 0 ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            results = tuple(self._summary_from_row(row) for row in rows)
            self._finish_audit(
                correlation_id,
                "conversation_list",
                AuditOutcome.SUCCEEDED,
                AuditReasonCode.NORMAL,
                started,
                len(results),
            )
            return results
        except ConversationHistoryError:
            self._failed_audit(correlation_id, "conversation_list", started)
            raise
        except Exception as error:
            self._failed_audit(correlation_id, "conversation_list", started)
            raise ConversationHistoryError(
                "Conversation history could not be read safely."
            ) from error

    def search_conversations(
        self,
        query: str,
        correlation_id: UUID,
        *,
        exclude_conversation_id: UUID | None = None,
        limit: int = MAX_RECALL_CONVERSATIONS,
    ) -> tuple[ConversationRecallMatch, ...]:
        """Return bounded neighborhoods from explicitly requested prior chats."""

        if (
            not isinstance(query, str)
            or not query.strip()
            or len(query) > MAX_RECALL_QUERY_CHARS
        ):
            raise ConversationHistoryError("Conversation search query is invalid.")
        self._require_uuid(correlation_id)
        if exclude_conversation_id is not None:
            self._require_uuid(exclude_conversation_id)
        if isinstance(limit, bool) or not 1 <= limit <= MAX_RECALL_CONVERSATIONS:
            raise ValueError("Conversation search limit is invalid.")
        terms = self._search_terms(query)
        started = self._start_audit(correlation_id, "conversation_search")
        try:
            with self._connections.connect(correlation_id) as connection:
                hits = self._search_hits(
                    connection,
                    terms,
                    exclude_conversation_id,
                )
                selected: list[tuple[str, int]] = []
                seen: set[str] = set()
                for conversation_id, sequence in hits:
                    if conversation_id in seen:
                        continue
                    seen.add(conversation_id)
                    selected.append((conversation_id, int(sequence)))
                    if len(selected) >= limit:
                        break
                results = tuple(
                    self._load_recall_match(connection, conversation_id, sequence)
                    for conversation_id, sequence in selected
                )
            self._finish_audit(
                correlation_id,
                "conversation_search",
                AuditOutcome.SUCCEEDED,
                AuditReasonCode.NORMAL,
                started,
                len(results),
            )
            return results
        except ConversationHistoryError:
            self._failed_audit(correlation_id, "conversation_search", started)
            raise
        except Exception as error:
            self._failed_audit(correlation_id, "conversation_search", started)
            raise ConversationHistoryError(
                "Conversation history could not be searched safely."
            ) from error

    def load_conversation(
        self,
        conversation_id: UUID,
        correlation_id: UUID,
    ) -> StoredConversation:
        self._require_uuid(conversation_id)
        started = self._start_audit(correlation_id, "conversation_load")
        try:
            with self._connections.connect(correlation_id) as connection:
                row = connection.execute(
                    "SELECT conversation_id, title, updated_at FROM conversations "
                    "WHERE conversation_id = ? AND archived = 0",
                    (str(conversation_id),),
                ).fetchone()
                if row is None:
                    raise ConversationNotFoundError("Conversation was not found.")
                message_rows = connection.execute(
                    "SELECT role, content, sequence FROM conversation_messages "
                    "WHERE conversation_id = ? ORDER BY sequence DESC LIMIT ?",
                    (str(conversation_id), MAX_HISTORY_LOAD_MESSAGES),
                ).fetchall()
            messages = tuple(
                StoredConversationMessage(
                    ConversationRole(message_row[0]),
                    message_row[1],
                    message_row[2],
                )
                for message_row in reversed(message_rows)
            )
            result = StoredConversation(self._summary_from_row(row), messages)
            self._finish_audit(
                correlation_id,
                "conversation_load",
                AuditOutcome.SUCCEEDED,
                AuditReasonCode.NORMAL,
                started,
                len(messages),
            )
            return result
        except ConversationHistoryError:
            self._failed_audit(correlation_id, "conversation_load", started)
            raise
        except Exception as error:
            self._failed_audit(correlation_id, "conversation_load", started)
            raise ConversationHistoryError(
                "Conversation history could not be read safely."
            ) from error

    def delete_conversation(
        self,
        conversation_id: UUID,
        correlation_id: UUID,
    ) -> None:
        self._require_uuid(conversation_id)
        started = self._start_audit(correlation_id, "conversation_delete")
        try:
            with self._connections.connect(correlation_id) as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    connection.execute(
                        "DELETE FROM conversation_search "
                        "WHERE conversation_id = ?",
                        (str(conversation_id),),
                    )
                    result = connection.execute(
                        "DELETE FROM conversations WHERE conversation_id = ?",
                        (str(conversation_id),),
                    )
                    if result.rowcount != 1:
                        raise ConversationNotFoundError("Conversation was not found.")
                    self._finish_audit(
                        correlation_id,
                        "conversation_delete",
                        AuditOutcome.SUCCEEDED,
                        AuditReasonCode.NORMAL,
                        started,
                    )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
        except ConversationHistoryError:
            self._failed_audit(correlation_id, "conversation_delete", started)
            raise
        except Exception as error:
            self._failed_audit(correlation_id, "conversation_delete", started)
            raise ConversationHistoryError(
                "Conversation history could not be deleted safely."
            ) from error

    def _start_audit(self, correlation_id: UUID, action: str) -> float:
        self._require_uuid(correlation_id)
        started = monotonic()
        try:
            self._finish_audit(
                correlation_id,
                action,
                AuditOutcome.STARTED,
                AuditReasonCode.NORMAL,
                started,
            )
        except Exception as error:
            raise ConversationHistoryError(
                "Conversation history auditing is unavailable."
            ) from error
        return started

    def _failed_audit(self, correlation_id: UUID, action: str, started: float) -> None:
        try:
            self._finish_audit(
                correlation_id,
                action,
                AuditOutcome.FAILED,
                AuditReasonCode.SAFE_INTERNAL_FAILURE,
                started,
            )
        except Exception:
            pass

    def _finish_audit(
        self,
        correlation_id: UUID,
        action: str,
        outcome: AuditOutcome,
        reason: AuditReasonCode,
        started: float,
        item_count: int | None = None,
    ) -> None:
        metadata = [
            AuditMetadataItem(AuditMetadataKey.ACTION_KIND, action),
            AuditMetadataItem(AuditMetadataKey.TARGET_CLASS, "conversation_history"),
        ]
        if item_count is not None:
            metadata.append(AuditMetadataItem(AuditMetadataKey.ITEM_COUNT, item_count))
        self._audit_sink.write(
            AuditEvent(
                correlation_id=correlation_id,
                component=AuditComponent.APPLICATION,
                operation=(
                    AuditOperation.REPOSITORY_READ
                    if action in {
                        "conversation_list",
                        "conversation_load",
                        "conversation_search",
                    }
                    else AuditOperation.REPOSITORY_WRITE
                ),
                outcome=outcome,
                reason_code=reason,
                metadata=tuple(metadata),
                duration_ms=max(0, int((monotonic() - started) * 1_000)),
            )
        )

    def _new_id(self) -> UUID:
        value = self._id_factory()
        if not isinstance(value, UUID):
            raise ConversationHistoryError("Conversation identifier is invalid.")
        return value

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ConversationHistoryError("Conversation timestamp is invalid.")
        if value.utcoffset() is None:
            raise ConversationHistoryError("Conversation timestamp is invalid.")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _require_uuid(value: UUID) -> None:
        if not isinstance(value, UUID):
            raise ConversationHistoryError("Conversation identifier is invalid.")

    @staticmethod
    def _validated_content(content: str) -> str:
        if not isinstance(content, str) or not content:
            raise ConversationHistoryError("Conversation content is invalid.")
        if "\x00" in content or len(content) > MAX_HISTORY_MESSAGE_CHARS:
            raise ConversationHistoryError("Conversation content is invalid.")
        return content

    @staticmethod
    def _title_for(content: str) -> str:
        normalized = " ".join(content.split())
        if len(normalized) > MAX_CONVERSATION_TITLE_CHARS:
            normalized = normalized[: MAX_CONVERSATION_TITLE_CHARS - 1].rstrip() + "…"
        return normalized or "New conversation"

    @staticmethod
    def _next_sequence(connection: Any, conversation_id: UUID) -> int:
        row = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM conversation_messages "
            "WHERE conversation_id = ?",
            (str(conversation_id),),
        ).fetchone()
        return int(row[0])

    @staticmethod
    def _require_active(connection: Any, conversation_id: UUID) -> None:
        row = connection.execute(
            "SELECT 1 FROM conversations WHERE conversation_id = ? AND archived = 0",
            (str(conversation_id),),
        ).fetchone()
        if row is None:
            raise ConversationNotFoundError("Conversation was not found.")

    @staticmethod
    def _search_terms(query: str) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                term
                for term in _RECALL_TERM.findall(query.casefold())
                if len(term) >= 2 and term not in _RECALL_STOP_WORDS
            )
        )[:12]

    @staticmethod
    def _search_hits(
        connection: Any,
        terms: tuple[str, ...],
        excluded_id: UUID | None,
    ) -> tuple[tuple[Any, ...], ...]:
        exclusion = None if excluded_id is None else str(excluded_id)
        if not terms:
            return tuple(
                connection.execute(
                    "SELECT c.conversation_id, COALESCE(MAX(m.sequence), 1) "
                    "FROM conversations c JOIN conversation_messages m "
                    "ON m.conversation_id = c.conversation_id "
                    "WHERE c.archived = 0 AND (? IS NULL OR c.conversation_id <> ?) "
                    "GROUP BY c.conversation_id, c.updated_at "
                    "ORDER BY c.updated_at DESC LIMIT ?",
                    (exclusion, exclusion, MAX_RECALL_CONVERSATIONS),
                ).fetchall()
            )
        expressions = [" AND ".join(f'"{term}"*' for term in terms)]
        if len(terms) > 1:
            expressions.append(" OR ".join(f'"{term}"*' for term in terms))
        for expression in expressions:
            rows = tuple(
                connection.execute(
                    "SELECT conversation_search.conversation_id, "
                    "conversation_search.sequence FROM conversation_search "
                    "JOIN conversations c ON c.conversation_id = "
                    "conversation_search.conversation_id "
                    "WHERE conversation_search MATCH ? AND c.archived = 0 "
                    "AND (? IS NULL OR c.conversation_id <> ?) "
                    "ORDER BY bm25(conversation_search), c.updated_at DESC "
                    "LIMIT ?",
                    (
                        expression,
                        exclusion,
                        exclusion,
                        MAX_RECALL_SCAN_HITS,
                    ),
                ).fetchall()
            )
            if rows:
                return rows
        return ()

    @staticmethod
    def _load_recall_match(
        connection: Any,
        conversation_id: str,
        hit_sequence: int,
    ) -> ConversationRecallMatch:
        row = connection.execute(
            "SELECT conversation_id, title, updated_at FROM conversations "
            "WHERE conversation_id = ? AND archived = 0",
            (conversation_id,),
        ).fetchone()
        if row is None:
            raise ConversationHistoryError("Conversation search result is invalid.")
        message_rows = connection.execute(
            "SELECT role, substr(content, 1, ?), sequence "
            "FROM conversation_messages WHERE conversation_id = ? "
            "AND role IN ('user', 'assistant') "
            "ORDER BY abs(sequence - ?), sequence LIMIT ?",
            (
                MAX_RECALL_MESSAGE_CHARS,
                conversation_id,
                hit_sequence,
                MAX_RECALL_MESSAGES_PER_CONVERSATION,
            ),
        ).fetchall()
        messages = tuple(
            StoredConversationMessage(
                ConversationRole(message_row[0]),
                message_row[1],
                int(message_row[2]),
            )
            for message_row in sorted(message_rows, key=lambda item: int(item[2]))
        )
        return ConversationRecallMatch(
            ConversationHistoryRepository._summary_from_row(row),
            messages,
        )

    @staticmethod
    def _summary_from_row(row: tuple[Any, ...]) -> ConversationSummary:
        try:
            identifier = UUID(row[0])
            title = row[1]
            updated_at = datetime.fromisoformat(row[2])
            if (
                not isinstance(title, str)
                or not title
                or updated_at.tzinfo is None
                or updated_at.utcoffset() is None
            ):
                raise ValueError
        except (TypeError, ValueError, IndexError) as error:
            raise ConversationHistoryError(
                "Stored conversation metadata is invalid."
            ) from error
        return ConversationSummary(identifier, title, updated_at)
