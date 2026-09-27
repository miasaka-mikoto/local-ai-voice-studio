from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .models import (
    CoachMode,
    ConversationTurn,
    Exercise,
    ExerciseType,
    LearnerProfile,
    LearningMode,
    LearningSession,
    RecordingAsset,
    RecordingSourceType,
    ReviewItem,
    SessionStatus,
    ShadowingFeedback,
)


class JapaneseRepositoryError(RuntimeError):
    pass


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


class JapaneseRepository:
    """SQLite persistence for the Japanese learning module.

    All table names use the ``jp_`` prefix so this repository can safely share
    the core Studio database.  Connections are short-lived, WAL-enabled, and
    foreign keys are always enforced.
    """

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path).resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_lock = threading.Lock()
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @contextmanager
    def _immediate_connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection, table: str, column: str, definition: str
    ) -> None:
        columns = {
            str(row["name"])
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def initialize(self) -> None:
        with self._init_lock, self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS jp_schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS jp_learner_profiles (
                    id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    level TEXT NOT NULL,
                    goals_json TEXT NOT NULL,
                    mastered_vocabulary_json TEXT NOT NULL,
                    mastered_grammar_json TEXT NOT NULL,
                    common_errors_json TEXT NOT NULL,
                    interests_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS jp_sessions (
                    id TEXT PRIMARY KEY,
                    learner_id TEXT NOT NULL REFERENCES jp_learner_profiles(id),
                    mode TEXT NOT NULL,
                    coach_mode TEXT NOT NULL,
                    scenario TEXT NOT NULL,
                    status TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT
                );

                CREATE TABLE IF NOT EXISTS jp_recordings (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES jp_sessions(id),
                    storage_path TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    source_type TEXT NOT NULL CHECK(source_type IN (
                        'browser_original_upload','imported_original',
                        'generated_reference','voice_colored'
                    )),
                    upload_entry TEXT NOT NULL,
                    original_filename TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    byte_size INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(session_id, id)
                );

                CREATE TRIGGER IF NOT EXISTS jp_recordings_immutable_update
                BEFORE UPDATE ON jp_recordings
                BEGIN
                    SELECT RAISE(ABORT, 'jp_recordings is immutable');
                END;

                CREATE TRIGGER IF NOT EXISTS jp_recordings_immutable_delete
                BEFORE DELETE ON jp_recordings
                BEGIN
                    SELECT RAISE(ABORT, 'jp_recordings is immutable');
                END;

                CREATE TABLE IF NOT EXISTS jp_turns (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES jp_sessions(id),
                    recording_id TEXT NOT NULL REFERENCES jp_recordings(id),
                    sequence INTEGER NOT NULL,
                    original_audio_path TEXT NOT NULL,
                    original_audio_sha256 TEXT NOT NULL,
                    scoring_source_kind TEXT NOT NULL,
                    transcript_json TEXT NOT NULL,
                    teacher_json TEXT NOT NULL,
                    demonstration_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(session_id, sequence)
                );

                CREATE TABLE IF NOT EXISTS jp_exercises (
                    id TEXT PRIMARY KEY,
                    learner_id TEXT NOT NULL REFERENCES jp_learner_profiles(id),
                    session_id TEXT REFERENCES jp_sessions(id),
                    exercise_type TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    expected_text TEXT NOT NULL,
                    reference_audio_path TEXT,
                    status TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS jp_shadow_attempts (
                    id TEXT PRIMARY KEY,
                    exercise_id TEXT NOT NULL REFERENCES jp_exercises(id),
                    recording_id TEXT NOT NULL REFERENCES jp_recordings(id),
                    original_recording_path TEXT NOT NULL,
                    original_recording_sha256 TEXT NOT NULL,
                    transcript_json TEXT NOT NULL,
                    feedback_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS jp_review_items (
                    id TEXT PRIMARY KEY,
                    learner_id TEXT NOT NULL REFERENCES jp_learner_profiles(id),
                    exercise_id TEXT REFERENCES jp_exercises(id),
                    error_key TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    ease_factor REAL NOT NULL,
                    interval_days INTEGER NOT NULL,
                    repetitions INTEGER NOT NULL,
                    due_at TEXT NOT NULL,
                    last_quality INTEGER,
                    evidence_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_jp_sessions_learner
                    ON jp_sessions(learner_id, started_at);
                CREATE INDEX IF NOT EXISTS idx_jp_recordings_session
                    ON jp_recordings(session_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_jp_turns_session
                    ON jp_turns(session_id, sequence);
                CREATE INDEX IF NOT EXISTS idx_jp_exercises_learner
                    ON jp_exercises(learner_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_jp_reviews_due
                    ON jp_review_items(learner_id, due_at);
                """
            )
            # Forward-only additive migration for databases created by 0.1/0.2.
            # Existing historical rows remain readable with NULL provenance;
            # every new turn/attempt is required by repository code to provide it.
            self._ensure_column(
                connection,
                "jp_turns",
                "recording_id",
                "TEXT REFERENCES jp_recordings(id)",
            )
            self._ensure_column(
                connection,
                "jp_shadow_attempts",
                "recording_id",
                "TEXT REFERENCES jp_recordings(id)",
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_jp_turns_recording ON jp_turns(recording_id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_jp_shadow_recording ON jp_shadow_attempts(recording_id)"
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO jp_schema_migrations(version, name, applied_at)
                VALUES (2, 'immutable_recording_provenance_and_atomic_turns', datetime('now'))
                """
            )

    def create_profile(self, profile: LearnerProfile) -> LearnerProfile:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO jp_learner_profiles (
                    id, display_name, level, goals_json,
                    mastered_vocabulary_json, mastered_grammar_json,
                    common_errors_json, interests_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile.id,
                    profile.display_name,
                    profile.level,
                    _dump(profile.goals),
                    _dump(profile.mastered_vocabulary),
                    _dump(profile.mastered_grammar),
                    _dump(profile.common_pronunciation_errors),
                    _dump(profile.interests),
                    profile.created_at,
                    profile.updated_at,
                ),
            )
        return profile

    def update_profile(self, profile: LearnerProfile) -> LearnerProfile:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE jp_learner_profiles SET
                    display_name = ?, level = ?, goals_json = ?,
                    mastered_vocabulary_json = ?, mastered_grammar_json = ?,
                    common_errors_json = ?, interests_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    profile.display_name,
                    profile.level,
                    _dump(profile.goals),
                    _dump(profile.mastered_vocabulary),
                    _dump(profile.mastered_grammar),
                    _dump(profile.common_pronunciation_errors),
                    _dump(profile.interests),
                    profile.updated_at,
                    profile.id,
                ),
            )
            if cursor.rowcount != 1:
                raise JapaneseRepositoryError(f"学习者不存在：{profile.id}")
        return profile

    def get_profile(self, learner_id: str) -> LearnerProfile:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM jp_learner_profiles WHERE id = ?", (learner_id,)
            ).fetchone()
        if row is None:
            raise JapaneseRepositoryError(f"学习者不存在：{learner_id}")
        return LearnerProfile(
            id=row["id"],
            display_name=row["display_name"],
            level=row["level"],
            goals=_load(row["goals_json"], []),
            mastered_vocabulary=_load(row["mastered_vocabulary_json"], []),
            mastered_grammar=_load(row["mastered_grammar_json"], []),
            common_pronunciation_errors=_load(row["common_errors_json"], []),
            interests=_load(row["interests_json"], []),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def create_session(self, session: LearningSession) -> LearningSession:
        self.get_profile(session.learner_id)
        with self._connection() as connection:
            self._insert_session(connection, session)
        return session

    @staticmethod
    def _insert_session(connection: sqlite3.Connection, session: LearningSession) -> None:
        connection.execute(
            """
            INSERT INTO jp_sessions (
                id, learner_id, mode, coach_mode, scenario, status,
                metadata_json, started_at, ended_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session.id,
                session.learner_id,
                session.mode.value,
                session.coach_mode.value,
                session.scenario,
                session.status.value,
                _dump(session.metadata),
                session.started_at,
                session.ended_at,
            ),
        )

    def create_project_lesson_bundle_atomic(
        self, session: LearningSession, exercises: list[Exercise]
    ) -> None:
        """Publish a complete project lesson or leave no session/exercise rows."""

        if not exercises:
            raise JapaneseRepositoryError("项目课程至少需要一条练习。")
        if session.mode is not LearningMode.PROJECT_LESSON:
            raise JapaneseRepositoryError("项目课程会话模式无效。")
        if any(
            exercise.learner_id != session.learner_id or exercise.session_id != session.id
            for exercise in exercises
        ):
            raise JapaneseRepositoryError("项目课程练习与会话归属不一致。")
        with self._immediate_connection() as connection:
            if connection.execute(
                "SELECT 1 FROM jp_learner_profiles WHERE id = ?", (session.learner_id,)
            ).fetchone() is None:
                raise JapaneseRepositoryError("学习者不存在。")
            self._insert_session(connection, session)
            for exercise in exercises:
                self._insert_exercise(connection, exercise)

    def get_session(self, session_id: str) -> LearningSession:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM jp_sessions WHERE id = ?", (session_id,)
            ).fetchone()
        if row is None:
            raise JapaneseRepositoryError(f"学习会话不存在：{session_id}")
        return LearningSession(
            id=row["id"],
            learner_id=row["learner_id"],
            mode=LearningMode(row["mode"]),
            coach_mode=CoachMode(row["coach_mode"]),
            scenario=row["scenario"],
            status=SessionStatus(row["status"]),
            metadata=_load(row["metadata_json"], {}),
            started_at=row["started_at"],
            ended_at=row["ended_at"],
        )

    def list_sessions(self, learner_id: str) -> list[LearningSession]:
        self.get_profile(learner_id)
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT id FROM jp_sessions WHERE learner_id = ? ORDER BY started_at DESC",
                (learner_id,),
            ).fetchall()
        return [self.get_session(row["id"]) for row in rows]

    def complete_session(self, session_id: str, ended_at: str) -> LearningSession:
        session = self.get_session(session_id)
        if session.status is SessionStatus.COMPLETED:
            return session
        with self._connection() as connection:
            connection.execute(
                "UPDATE jp_sessions SET status = ?, ended_at = ? WHERE id = ?",
                (SessionStatus.COMPLETED.value, ended_at, session_id),
            )
        return self.get_session(session_id)

    def create_recording(self, recording: RecordingAsset) -> RecordingAsset:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO jp_recordings (
                    id, session_id, storage_path, sha256, source_type,
                    upload_entry, original_filename, content_type,
                    byte_size, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    recording.id,
                    recording.session_id,
                    recording.storage_path,
                    recording.sha256,
                    recording.source_type.value,
                    recording.upload_entry,
                    recording.original_filename,
                    recording.content_type,
                    recording.byte_size,
                    recording.created_at,
                ),
            )
        return recording

    def get_recording(self, recording_id: str) -> RecordingAsset:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM jp_recordings WHERE id = ?", (recording_id,)
            ).fetchone()
        if row is None:
            raise JapaneseRepositoryError(f"录音来源记录不存在：{recording_id}")
        return RecordingAsset(
            id=row["id"],
            session_id=row["session_id"],
            storage_path=row["storage_path"],
            sha256=row["sha256"],
            source_type=RecordingSourceType(row["source_type"]),
            upload_entry=row["upload_entry"],
            original_filename=row["original_filename"],
            content_type=row["content_type"],
            byte_size=int(row["byte_size"]),
            created_at=row["created_at"],
        )

    @staticmethod
    def _insert_turn(connection: sqlite3.Connection, turn: ConversationTurn) -> None:
        connection.execute(
            """
            INSERT INTO jp_turns (
                id, session_id, recording_id, sequence, original_audio_path,
                original_audio_sha256, scoring_source_kind,
                transcript_json, teacher_json, demonstration_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                turn.id,
                turn.session_id,
                turn.recording_id,
                turn.sequence,
                turn.original_audio_path,
                turn.original_audio_sha256,
                turn.scoring_source_kind.value,
                _dump(turn.transcript.to_dict()),
                _dump(turn.teacher.to_dict()),
                _dump(turn.demonstration.to_dict()),
                turn.created_at,
            ),
        )

    @staticmethod
    def _insert_review(connection: sqlite3.Connection, item: ReviewItem) -> None:
        connection.execute(
            """
            INSERT INTO jp_review_items (
                id, learner_id, exercise_id, error_key, prompt, answer,
                ease_factor, interval_days, repetitions, due_at,
                last_quality, evidence_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.id,
                item.learner_id,
                item.exercise_id,
                item.error_key,
                item.prompt,
                item.answer,
                item.ease_factor,
                item.interval_days,
                item.repetitions,
                item.due_at,
                item.last_quality,
                _dump(item.evidence),
                item.created_at,
                item.updated_at,
            ),
        )

    def save_turn_with_reviews_atomic(
        self, turn: ConversationTurn, reviews: list[ReviewItem]
    ) -> ConversationTurn:
        """Allocate sequence and commit the turn plus reviews in one IMMEDIATE transaction."""

        with self._immediate_connection() as connection:
            session = connection.execute(
                "SELECT status FROM jp_sessions WHERE id = ?", (turn.session_id,)
            ).fetchone()
            if session is None:
                raise JapaneseRepositoryError(f"学习会话不存在：{turn.session_id}")
            if session["status"] != SessionStatus.ACTIVE.value:
                raise JapaneseRepositoryError("只有 active 会话可以新增轮次。")
            row = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 AS value FROM jp_turns WHERE session_id = ?",
                (turn.session_id,),
            ).fetchone()
            turn.sequence = int(row["value"])
            self._insert_turn(connection, turn)
            for item in reviews:
                self._insert_review(connection, item)
        return turn

    def list_turn_rows(self, session_id: str) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM jp_turns WHERE session_id = ? ORDER BY sequence", (session_id,)
            ).fetchall()
        return [
            {
                **dict(row),
                "transcript": _load(row["transcript_json"], {}),
                "teacher": _load(row["teacher_json"], {}),
                "demonstration": _load(row["demonstration_json"], {}),
            }
            for row in rows
        ]

    def get_turn_row(self, turn_id: str) -> dict[str, Any]:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM jp_turns WHERE id = ?", (turn_id,)).fetchone()
        if row is None:
            raise JapaneseRepositoryError(f"会话轮次不存在：{turn_id}")
        return {
            **dict(row),
            "transcript": _load(row["transcript_json"], {}),
            "teacher": _load(row["teacher_json"], {}),
            "demonstration": _load(row["demonstration_json"], {}),
        }

    def create_exercise(self, exercise: Exercise) -> Exercise:
        with self._connection() as connection:
            self._insert_exercise(connection, exercise)
        return exercise

    @staticmethod
    def _insert_exercise(connection: sqlite3.Connection, exercise: Exercise) -> None:
        connection.execute(
            """
            INSERT INTO jp_exercises (
                id, learner_id, session_id, exercise_type, prompt,
                expected_text, reference_audio_path, status,
                metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                exercise.id,
                exercise.learner_id,
                exercise.session_id,
                exercise.exercise_type.value,
                exercise.prompt,
                exercise.expected_text,
                exercise.reference_audio_path,
                exercise.status,
                _dump(exercise.metadata),
                exercise.created_at,
            ),
        )

    def get_exercise(self, exercise_id: str) -> Exercise:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM jp_exercises WHERE id = ?", (exercise_id,)
            ).fetchone()
        if row is None:
            raise JapaneseRepositoryError(f"练习不存在：{exercise_id}")
        return Exercise(
            id=row["id"],
            learner_id=row["learner_id"],
            session_id=row["session_id"],
            exercise_type=ExerciseType(row["exercise_type"]),
            prompt=row["prompt"],
            expected_text=row["expected_text"],
            reference_audio_path=row["reference_audio_path"],
            status=row["status"],
            metadata=_load(row["metadata_json"], {}),
            created_at=row["created_at"],
        )

    def save_shadow_attempt(
        self,
        attempt_id: str,
        exercise_id: str,
        recording_id: str,
        original_recording_path: str,
        original_recording_sha256: str,
        transcript: dict[str, Any],
        feedback: ShadowingFeedback,
        created_at: str,
    ) -> None:
        with self._connection() as connection:
            self._insert_shadow_attempt(
                connection,
                attempt_id=attempt_id,
                exercise_id=exercise_id,
                recording_id=recording_id,
                original_recording_path=original_recording_path,
                original_recording_sha256=original_recording_sha256,
                transcript=transcript,
                feedback=feedback,
                created_at=created_at,
            )

    @staticmethod
    def _insert_shadow_attempt(
        connection: sqlite3.Connection,
        *,
        attempt_id: str,
        exercise_id: str,
        recording_id: str,
        original_recording_path: str,
        original_recording_sha256: str,
        transcript: dict[str, Any],
        feedback: ShadowingFeedback,
        created_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO jp_shadow_attempts (
                id, exercise_id, recording_id, original_recording_path,
                original_recording_sha256, transcript_json,
                feedback_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attempt_id,
                exercise_id,
                recording_id,
                original_recording_path,
                original_recording_sha256,
                _dump(transcript),
                _dump(feedback.to_dict()),
                created_at,
            ),
        )

    def save_shadow_submission_atomic(
        self,
        *,
        exercise: Exercise,
        create_exercise: bool,
        attempt_id: str,
        recording_id: str,
        original_recording_path: str,
        original_recording_sha256: str,
        transcript: dict[str, Any],
        feedback: ShadowingFeedback,
        created_at: str,
        reviews: list[ReviewItem],
    ) -> None:
        """Commit one shadowing exercise/attempt/review bundle atomically.

        For a reused exercise, the existing row is checked while the IMMEDIATE
        transaction owns the write lock.  For a new exercise, its insert is part
        of the same transaction as the attempt and every generated review.
        """

        with self._immediate_connection() as connection:
            if create_exercise:
                self._insert_exercise(connection, exercise)
            else:
                row = connection.execute(
                    "SELECT id FROM jp_exercises WHERE id = ?", (exercise.id,)
                ).fetchone()
                if row is None:
                    raise JapaneseRepositoryError(f"练习不存在：{exercise.id}")
            self._insert_shadow_attempt(
                connection,
                attempt_id=attempt_id,
                exercise_id=exercise.id,
                recording_id=recording_id,
                original_recording_path=original_recording_path,
                original_recording_sha256=original_recording_sha256,
                transcript=transcript,
                feedback=feedback,
                created_at=created_at,
            )
            for item in reviews:
                self._insert_review(connection, item)

    def create_review_item(self, item: ReviewItem) -> ReviewItem:
        with self._connection() as connection:
            self._insert_review(connection, item)
        return item

    def get_review_item(self, review_id: str) -> ReviewItem:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM jp_review_items WHERE id = ?", (review_id,)
            ).fetchone()
        if row is None:
            raise JapaneseRepositoryError(f"复习项不存在：{review_id}")
        return self._review_from_row(row)

    def update_review_item(self, item: ReviewItem) -> ReviewItem:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE jp_review_items SET
                    ease_factor = ?, interval_days = ?, repetitions = ?,
                    due_at = ?, last_quality = ?, evidence_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    item.ease_factor,
                    item.interval_days,
                    item.repetitions,
                    item.due_at,
                    item.last_quality,
                    _dump(item.evidence),
                    item.updated_at,
                    item.id,
                ),
            )
            if cursor.rowcount != 1:
                raise JapaneseRepositoryError(f"复习项不存在：{item.id}")
        return item

    def list_due_reviews(self, learner_id: str, due_before: str) -> list[ReviewItem]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM jp_review_items
                WHERE learner_id = ? AND due_at <= ?
                ORDER BY due_at, created_at
                """,
                (learner_id, due_before),
            ).fetchall()
        return [self._review_from_row(row) for row in rows]

    def list_review_items(self, learner_id: str) -> list[ReviewItem]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM jp_review_items WHERE learner_id = ? ORDER BY created_at",
                (learner_id,),
            ).fetchall()
        return [self._review_from_row(row) for row in rows]

    def progress_counts(self, learner_id: str) -> dict[str, int]:
        self.get_profile(learner_id)
        with self._connection() as connection:
            sessions = int(
                connection.execute(
                    "SELECT COUNT(*) FROM jp_sessions WHERE learner_id = ?", (learner_id,)
                ).fetchone()[0]
            )
            turns = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM jp_turns AS t
                    JOIN jp_sessions AS s ON s.id = t.session_id
                    WHERE s.learner_id = ?
                    """,
                    (learner_id,),
                ).fetchone()[0]
            )
            exercises = int(
                connection.execute(
                    "SELECT COUNT(*) FROM jp_exercises WHERE learner_id = ?", (learner_id,)
                ).fetchone()[0]
            )
            shadow_attempts = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM jp_shadow_attempts AS a
                    JOIN jp_exercises AS e ON e.id = a.exercise_id
                    WHERE e.learner_id = ?
                    """,
                    (learner_id,),
                ).fetchone()[0]
            )
            reviews = int(
                connection.execute(
                    "SELECT COUNT(*) FROM jp_review_items WHERE learner_id = ?", (learner_id,)
                ).fetchone()[0]
            )
        return {
            "sessions": sessions,
            "turns": turns,
            "exercises": exercises,
            "shadow_attempts": shadow_attempts,
            "reviews": reviews,
        }

    def recent_shadow_feedback(self, learner_id: str, limit: int = 20) -> list[dict[str, Any]]:
        self.get_profile(learner_id)
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT a.feedback_json, a.created_at
                FROM jp_shadow_attempts AS a
                JOIN jp_exercises AS e ON e.id = a.exercise_id
                WHERE e.learner_id = ?
                ORDER BY a.created_at DESC
                LIMIT ?
                """,
                (learner_id, max(1, min(limit, 100))),
            ).fetchall()
        return [
            {"feedback": _load(row["feedback_json"], {}), "created_at": row["created_at"]}
            for row in rows
        ]

    @staticmethod
    def _review_from_row(row: sqlite3.Row) -> ReviewItem:
        return ReviewItem(
            id=row["id"],
            learner_id=row["learner_id"],
            exercise_id=row["exercise_id"],
            error_key=row["error_key"],
            prompt=row["prompt"],
            answer=row["answer"],
            ease_factor=float(row["ease_factor"]),
            interval_days=int(row["interval_days"]),
            repetitions=int(row["repetitions"]),
            due_at=row["due_at"],
            last_quality=row["last_quality"],
            evidence=_load(row["evidence_json"], {}),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def counts(self) -> dict[str, int]:
        tables = {
            "learners": "jp_learner_profiles",
            "sessions": "jp_sessions",
            "recordings": "jp_recordings",
            "turns": "jp_turns",
            "exercises": "jp_exercises",
            "shadow_attempts": "jp_shadow_attempts",
            "reviews": "jp_review_items",
        }
        with self._connection() as connection:
            return {
                name: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for name, table in tables.items()
            }
