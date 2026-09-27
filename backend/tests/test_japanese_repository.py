from __future__ import annotations

import sys
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.modules.japanese.models import (  # noqa: E402
    CoachMode,
    ConversationTurn,
    Exercise,
    ExerciseType,
    LearnerProfile,
    LearningMode,
    LearningSession,
    MetricFeedback,
    RecordingAsset,
    RecordingSourceType,
    ReviewItem,
    ShadowingFeedback,
    SourceAudioKind,
    SynthesisResult,
    TeacherResult,
    TranscriptResult,
)
from app.modules.japanese.repository import (  # noqa: E402
    JapaneseRepository,
    JapaneseRepositoryError,
)


class JapaneseRepositoryTests(unittest.TestCase):
    @staticmethod
    def _shadow_feedback(reference: Path, recording: Path) -> ShadowingFeedback:
        def metric(name: str) -> MetricFeedback:
            return MetricFeedback(
                metric=name,
                value=0.5,
                confidence=0.75,
                summary=f"{name} evidence",
                evidence={"source": "test"},
            )

        return ShadowingFeedback(
            content=metric("content"),
            mora=metric("mora"),
            rhythm=metric("rhythm"),
            pitch=metric("pitch"),
            priorities=["retry"],
            scoring_source_path=str(recording),
            scoring_source_kind=SourceAudioKind.ORIGINAL_UNCOLORED,
            reference_audio_path=str(reference),
        )

    def test_profile_session_exercise_and_review_survive_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "studio.sqlite3"
            repository = JapaneseRepository(database)
            profile = repository.create_profile(
                LearnerProfile(
                    display_name="学習者",
                    level="N4",
                    goals=["旅行会話"],
                    interests=["アニメ"],
                )
            )
            session = repository.create_session(
                LearningSession(
                    learner_id=profile.id,
                    mode=LearningMode.SHADOWING,
                    coach_mode=CoachMode.STRICT,
                    scenario="駅で切符を買う",
                )
            )
            exercise = repository.create_exercise(
                Exercise(
                    learner_id=profile.id,
                    session_id=session.id,
                    exercise_type=ExerciseType.SHADOWING,
                    prompt="聞いて繰り返す",
                    expected_text="東京までお願いします。",
                )
            )
            review = repository.create_review_item(
                ReviewItem(
                    learner_id=profile.id,
                    exercise_id=exercise.id,
                    error_key="shadowing:rhythm",
                    prompt="東京までお願いします。",
                    answer="mora 节奏をそろえる",
                    evidence={"confidence": 0.6},
                )
            )

            reopened = JapaneseRepository(database)
            self.assertEqual(reopened.get_profile(profile.id).goals, ["旅行会話"])
            self.assertEqual(reopened.get_session(session.id).scenario, "駅で切符を買う")
            self.assertEqual(reopened.get_exercise(exercise.id).exercise_type, ExerciseType.SHADOWING)
            self.assertEqual(reopened.get_review_item(review.id).evidence["confidence"], 0.6)
            self.assertEqual(
                reopened.counts(),
                {
                    "learners": 1,
                    "sessions": 1,
                    "recordings": 0,
                    "turns": 0,
                    "exercises": 1,
                    "shadow_attempts": 0,
                    "reviews": 1,
                },
            )

    def test_legacy_tables_receive_additive_recording_provenance_migration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "legacy.sqlite3"
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.executescript(
                    """
                    CREATE TABLE jp_sessions (
                        id TEXT PRIMARY KEY, learner_id TEXT NOT NULL, mode TEXT NOT NULL,
                        coach_mode TEXT NOT NULL, scenario TEXT NOT NULL, status TEXT NOT NULL,
                        metadata_json TEXT NOT NULL, started_at TEXT NOT NULL, ended_at TEXT
                    );
                    CREATE TABLE jp_turns (
                        id TEXT PRIMARY KEY, session_id TEXT NOT NULL, sequence INTEGER NOT NULL,
                        original_audio_path TEXT NOT NULL, original_audio_sha256 TEXT NOT NULL,
                        scoring_source_kind TEXT NOT NULL, transcript_json TEXT NOT NULL,
                        teacher_json TEXT NOT NULL, demonstration_json TEXT NOT NULL,
                        created_at TEXT NOT NULL, UNIQUE(session_id, sequence)
                    );
                    CREATE TABLE jp_exercises (
                        id TEXT PRIMARY KEY, learner_id TEXT NOT NULL, session_id TEXT,
                        exercise_type TEXT NOT NULL, prompt TEXT NOT NULL, expected_text TEXT NOT NULL,
                        reference_audio_path TEXT, status TEXT NOT NULL, metadata_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    CREATE TABLE jp_shadow_attempts (
                        id TEXT PRIMARY KEY, exercise_id TEXT NOT NULL,
                        original_recording_path TEXT NOT NULL,
                        original_recording_sha256 TEXT NOT NULL,
                        transcript_json TEXT NOT NULL, feedback_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    """
                )
            JapaneseRepository(database)
            with closing(sqlite3.connect(database)) as connection:
                turn_columns = {
                    row[1] for row in connection.execute("PRAGMA table_info(jp_turns)")
                }
                attempt_columns = {
                    row[1] for row in connection.execute("PRAGMA table_info(jp_shadow_attempts)")
                }
                migration = connection.execute(
                    "SELECT name FROM jp_schema_migrations WHERE version = 2"
                ).fetchone()
            self.assertIn("recording_id", turn_columns)
            self.assertIn("recording_id", attempt_columns)
            self.assertEqual(migration[0], "immutable_recording_provenance_and_atomic_turns")

    def test_atomic_turn_rolls_back_when_review_insert_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JapaneseRepository(Path(directory) / "atomic.sqlite3")
            profile = repository.create_profile(LearnerProfile(display_name="atomic"))
            session = repository.create_session(
                LearningSession(
                    learner_id=profile.id,
                    mode=LearningMode.CONVERSATION,
                    coach_mode=CoachMode.STRICT,
                    scenario="并发",
                )
            )
            recording = repository.create_recording(
                RecordingAsset(
                    session_id=session.id,
                    storage_path=str(Path(directory) / "recording.wav"),
                    sha256="0" * 64,
                    source_type=RecordingSourceType.BROWSER_ORIGINAL_UPLOAD,
                    upload_entry="api:/api/japanese/recordings",
                    original_filename="recording.wav",
                    content_type="audio/wav",
                    byte_size=1,
                )
            )
            with closing(sqlite3.connect(repository.database_path)) as connection:
                with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
                    connection.execute(
                        "UPDATE jp_recordings SET sha256 = ? WHERE id = ?",
                        ("f" * 64, recording.id),
                    )
            turn = ConversationTurn(
                session_id=session.id,
                recording_id=recording.id,
                sequence=0,
                original_audio_path=recording.storage_path,
                original_audio_sha256=recording.sha256,
                transcript=TranscriptResult("日本語", 0.5, "mock"),
                teacher=TeacherResult("はい", "はい", [], None, "mock", 0.5),
                demonstration=SynthesisResult("demo.wav", "mock", "standard_tokyo", 48_000, "PCM_24"),
                scoring_source_kind=SourceAudioKind.ORIGINAL_UNCOLORED,
            )
            duplicated_id = "review_duplicate"
            reviews = [
                ReviewItem(
                    id=duplicated_id,
                    learner_id=profile.id,
                    error_key=f"error:{index}",
                    prompt="prompt",
                    answer="answer",
                )
                for index in range(2)
            ]
            with self.assertRaises(sqlite3.IntegrityError):
                repository.save_turn_with_reviews_atomic(turn, reviews)
            self.assertEqual(repository.counts()["turns"], 0)
            self.assertEqual(repository.counts()["reviews"], 0)

    def test_shadow_submission_commits_new_exercise_attempt_and_reviews_together(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = JapaneseRepository(root / "shadow-success.sqlite3")
            profile = repository.create_profile(LearnerProfile(display_name="shadow-success"))
            session = repository.create_session(
                LearningSession(
                    learner_id=profile.id,
                    mode=LearningMode.SHADOWING,
                    coach_mode=CoachMode.STRICT,
                    scenario="atomic success",
                )
            )
            recording_path = root / "recording.wav"
            reference_path = root / "reference.wav"
            recording_path.write_bytes(b"recording")
            reference_path.write_bytes(b"reference")
            recording = repository.create_recording(
                RecordingAsset(
                    session_id=session.id,
                    storage_path=str(recording_path),
                    sha256="1" * 64,
                    source_type=RecordingSourceType.BROWSER_ORIGINAL_UPLOAD,
                    upload_entry="api:/api/japanese/recordings",
                    original_filename="recording.wav",
                    content_type="audio/wav",
                    byte_size=recording_path.stat().st_size,
                )
            )
            exercise = Exercise(
                learner_id=profile.id,
                session_id=session.id,
                exercise_type=ExerciseType.SHADOWING,
                prompt="repeat",
                expected_text="日本語",
                reference_audio_path=str(reference_path),
            )
            review = ReviewItem(
                learner_id=profile.id,
                exercise_id=exercise.id,
                error_key="shadowing:rhythm",
                prompt="日本語",
                answer="retry",
            )

            repository.save_shadow_submission_atomic(
                exercise=exercise,
                create_exercise=True,
                attempt_id="shadow_atomic_success",
                recording_id=recording.id,
                original_recording_path=str(recording_path),
                original_recording_sha256=recording.sha256,
                transcript={"text": "日本語"},
                feedback=self._shadow_feedback(reference_path, recording_path),
                created_at=review.created_at,
                reviews=[review],
            )

            self.assertEqual(repository.get_exercise(exercise.id).id, exercise.id)
            self.assertEqual(repository.get_review_item(review.id).exercise_id, exercise.id)
            self.assertEqual(
                repository.counts(),
                {
                    "learners": 1,
                    "sessions": 1,
                    "recordings": 1,
                    "turns": 0,
                    "exercises": 1,
                    "shadow_attempts": 1,
                    "reviews": 1,
                },
            )

    def test_shadow_submission_failure_rolls_back_new_bundle_and_preserves_reused_exercise(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = JapaneseRepository(root / "shadow-rollback.sqlite3")
            profile = repository.create_profile(LearnerProfile(display_name="shadow-rollback"))
            session = repository.create_session(
                LearningSession(
                    learner_id=profile.id,
                    mode=LearningMode.SHADOWING,
                    coach_mode=CoachMode.STRICT,
                    scenario="atomic rollback",
                )
            )
            recording_path = root / "recording.wav"
            reference_path = root / "reference.wav"
            recording_path.write_bytes(b"recording")
            reference_path.write_bytes(b"reference")
            recording = repository.create_recording(
                RecordingAsset(
                    session_id=session.id,
                    storage_path=str(recording_path),
                    sha256="2" * 64,
                    source_type=RecordingSourceType.BROWSER_ORIGINAL_UPLOAD,
                    upload_entry="api:/api/japanese/recordings",
                    original_filename="recording.wav",
                    content_type="audio/wav",
                    byte_size=recording_path.stat().st_size,
                )
            )

            def submission(exercise: Exercise, create_exercise: bool, attempt_id: str) -> None:
                review = ReviewItem(
                    learner_id=profile.id,
                    exercise_id=exercise.id,
                    error_key="shadowing:pitch",
                    prompt="日本語",
                    answer="retry",
                )
                repository.save_shadow_submission_atomic(
                    exercise=exercise,
                    create_exercise=create_exercise,
                    attempt_id=attempt_id,
                    recording_id=recording.id,
                    original_recording_path=str(recording_path),
                    original_recording_sha256=recording.sha256,
                    transcript={"text": "日本語"},
                    feedback=self._shadow_feedback(reference_path, recording_path),
                    created_at=review.created_at,
                    reviews=[review],
                )

            new_exercise = Exercise(
                learner_id=profile.id,
                session_id=session.id,
                exercise_type=ExerciseType.SHADOWING,
                prompt="new",
                expected_text="日本語",
                reference_audio_path=str(reference_path),
            )
            with patch.object(
                repository,
                "_insert_review",
                side_effect=JapaneseRepositoryError("forced review failure"),
            ):
                with self.assertRaisesRegex(JapaneseRepositoryError, "forced review failure"):
                    submission(new_exercise, True, "shadow_new_failure")
            self.assertEqual(repository.counts()["exercises"], 0)
            self.assertEqual(repository.counts()["shadow_attempts"], 0)
            self.assertEqual(repository.counts()["reviews"], 0)

            reused_exercise = repository.create_exercise(
                Exercise(
                    learner_id=profile.id,
                    session_id=session.id,
                    exercise_type=ExerciseType.SHADOWING,
                    prompt="reused",
                    expected_text="日本語",
                    reference_audio_path=str(reference_path),
                )
            )
            with patch.object(
                repository,
                "_insert_review",
                side_effect=JapaneseRepositoryError("forced review failure"),
            ):
                with self.assertRaisesRegex(JapaneseRepositoryError, "forced review failure"):
                    submission(reused_exercise, False, "shadow_reused_failure")
            self.assertEqual(repository.get_exercise(reused_exercise.id).id, reused_exercise.id)
            self.assertEqual(repository.counts()["exercises"], 1)
            self.assertEqual(repository.counts()["shadow_attempts"], 0)
            self.assertEqual(repository.counts()["reviews"], 0)


if __name__ == "__main__":
    unittest.main()
