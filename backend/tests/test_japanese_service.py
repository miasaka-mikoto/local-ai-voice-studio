from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
import wave
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.modules.japanese.adapters import (  # noqa: E402
    AdapterBundle,
    MockASRAdapter,
    MockTTSAdapter,
    MockTeacherAdapter,
)
from app.modules.japanese.models import (  # noqa: E402
    CoachMode,
    LearningMode,
    RecordingAsset,
    RecordingSourceType,
    SourceAudioKind,
)
from app.modules.japanese.repository import JapaneseRepository, JapaneseRepositoryError  # noqa: E402
from app.modules.japanese.service import JapaneseLearningService, JapaneseServiceError  # noqa: E402


class JapaneseServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.assets = root / "assets"
        self.service = JapaneseLearningService(
            JapaneseRepository(root / "studio.sqlite3"),
            self.assets,
            AdapterBundle(MockASRAdapter(), MockTeacherAdapter(), MockTTSAdapter()),
        )
        self.learner = self.service.create_learner("テスト", "N4", ["会話"], ["ゲーム"])
        self.session = self.service.start_session(
            self.learner.id,
            LearningMode.CONVERSATION,
            CoachMode.STRICT,
            "学校",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _audio(self, name: str, text: str = "日本語") -> Path:
        path = self.assets / "fixtures" / name
        MockTTSAdapter().synthesize(text, path, "standard_tokyo")
        return path

    def _uploaded(self, name: str, text: str = "日本語"):
        source = self._audio(f"source-{name}", text)
        return self.service.store_recording(
            self.session.id, name, source.read_bytes(), "audio/wav"
        )

    def test_half_duplex_turn_persists_original_hash_repair_and_demo(self) -> None:
        recording = self._uploaded("recording.wav")
        turn = self.service.process_turn(
            self.session.id,
            recording.id,
            transcript_hint="日本語勉強します",
        )
        self.assertEqual(turn.scoring_source_kind, SourceAudioKind.ORIGINAL_UNCOLORED)
        self.assertEqual(turn.recording_id, recording.id)
        self.assertEqual(turn.sequence, 1)
        self.assertIn("日本語を勉強します", turn.teacher.repair.minimal_correction)
        self.assertEqual(len(turn.original_audio_sha256), 64)
        demonstration = Path(turn.demonstration.audio_path)
        self.assertTrue(demonstration.is_file())
        self.assertEqual(self.service.turn_demonstration_path(turn.id), demonstration.resolve())
        with wave.open(str(demonstration), "rb") as wav:
            self.assertEqual((wav.getframerate(), wav.getsampwidth()), (48_000, 3))
        rows = self.service.repository.list_turn_rows(self.session.id)
        self.assertEqual(rows[0]["transcript"]["text"], "日本語勉強します")
        self.assertEqual(self.service.list_turns(self.session.id)[0]["id"], turn.id)
        self.assertEqual(self.service.list_sessions(self.learner.id)[0].id, self.session.id)
        self.assertEqual(self.service.repository.counts()["reviews"], 1)

    def test_silent_conversation_upload_cannot_create_a_turn_or_teacher_demo(self) -> None:
        silence = self.assets / "fixtures" / "silent-conversation.wav"
        silence.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(silence), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(3)
            wav.setframerate(48_000)
            wav.writeframes(b"\x00\x00\x00" * 48_000)
        recording = self.service.store_recording(
            self.session.id, "silent-conversation.wav", silence.read_bytes(), "audio/wav"
        )
        before = self.service.repository.counts()
        with (
            patch.object(self.service.adapters.asr, "transcribe", side_effect=AssertionError("ASR called")),
            patch.object(self.service.adapters.teacher, "teach", side_effect=AssertionError("teacher called")),
            patch.object(self.service.adapters.tts, "synthesize", side_effect=AssertionError("TTS called")),
        ):
            with self.assertRaisesRegex(JapaneseServiceError, "重录"):
                self.service.process_turn(
                    self.session.id, recording.id, transcript_hint="おはようございます"
                )
        self.assertEqual(self.service.repository.counts(), before)
        self.assertEqual(self.service.list_turns(self.session.id), [])
        self.assertFalse((self.assets / "japanese" / "sessions" / self.session.id / "turns").exists())

    def test_raw_pcm_wav_recording_is_stored_inside_session_assets(self) -> None:
        source = self._audio("upload-source.wav")
        stored = self.service.store_recording(self.session.id, "microphone.wav", source.read_bytes())
        stored_path = Path(stored.storage_path)
        self.assertTrue(stored_path.is_file())
        self.assertTrue(stored_path.is_relative_to(self.assets.resolve()))
        self.assertEqual(stored.source_type, RecordingSourceType.BROWSER_ORIGINAL_UPLOAD)
        self.assertEqual(self.service.repository.get_recording(stored.id).sha256, stored.sha256)
        with wave.open(str(stored_path), "rb") as wav:
            self.assertEqual((wav.getframerate(), wav.getsampwidth()), (48_000, 3))

    def test_shadowing_creates_ab_paths_feedback_and_review(self) -> None:
        reference = self._audio("reference.wav", "おはようございます")
        recording = self._uploaded("original.wav", "おはようございます")
        result = self.service.analyze_shadowing_attempt(
            self.session.id,
            reference,
            recording.id,
            "おはようございます",
            transcript_hint="おはようございま",
        )
        self.assertEqual(result["ab_playback"]["reference_audio_path"], str(reference.resolve()))
        self.assertEqual(
            result["feedback"]["scoring_source_kind"],
            SourceAudioKind.ORIGINAL_UNCOLORED.value,
        )
        self.assertNotIn("overall_score", result["feedback"])
        self.assertLessEqual(len(result["feedback"]["priorities"]), 2)
        counts = self.service.repository.counts()
        self.assertEqual(counts["exercises"], 1)
        self.assertEqual(counts["shadow_attempts"], 1)
        self.assertEqual(counts["reviews"], len(result["review_item_ids"]))
        progress = self.service.progress_snapshot(self.learner.id)
        self.assertNotIn("overall_score", progress)
        self.assertEqual(progress["metrics"]["content"]["sample_count"], 1)
        self.assertEqual(progress["policy"], "separate_metrics_only_no_overall_score")

    def test_failed_shadow_bundle_leaves_no_partial_records_or_files(self) -> None:
        reference = self._audio("atomic-reference.wav", "おはようございます")
        recording = self._uploaded("atomic-original.wav", "おはようございます")
        files_before = {
            path.relative_to(self.assets)
            for path in self.assets.rglob("*")
            if path.is_file()
        }

        with patch.object(
            self.service.repository,
            "save_shadow_submission_atomic",
            side_effect=JapaneseRepositoryError("forced shadow rollback"),
        ):
            with self.assertRaisesRegex(JapaneseServiceError, "forced shadow rollback"):
                self.service.analyze_shadowing_attempt(
                    self.session.id,
                    reference,
                    recording.id,
                    "おはようございます",
                    transcript_hint="おはようございま",
                )

        counts = self.service.repository.counts()
        self.assertEqual(counts["exercises"], 0)
        self.assertEqual(counts["shadow_attempts"], 0)
        self.assertEqual(counts["reviews"], 0)
        self.assertEqual(
            {
                path.relative_to(self.assets)
                for path in self.assets.rglob("*")
                if path.is_file()
            },
            files_before,
        )

    def test_generated_reference_is_streamable_and_reused_for_attempt(self) -> None:
        created = self.service.create_shadowing_reference(
            self.session.id, "新宿まで一枚お願いします。"
        )
        exercise_id = created["exercise"]["id"]
        reference = self.service.exercise_reference_path(exercise_id)
        self.assertTrue(reference.is_file())
        self.assertEqual(self.service.repository.counts()["exercises"], 1)
        recording = self._uploaded("reuse-original.wav", "新宿まで一枚お願いします。")
        result = self.service.analyze_shadowing_exercise_attempt(
            self.session.id,
            exercise_id,
            recording.id,
            transcript_hint="新宿まで一枚お願いします。",
        )
        self.assertEqual(result["exercise"]["id"], exercise_id)
        self.assertEqual(self.service.repository.counts()["exercises"], 1)
        self.assertEqual(Path(result["ab_playback"]["reference_audio_path"]), reference)

    def test_silent_uploaded_recording_ignores_hint_and_creates_no_learning_error(self) -> None:
        created = self.service.create_shadowing_reference(
            self.session.id, "おはようございます"
        )
        silence = self.assets / "fixtures" / "silence-upload.wav"
        silence.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(silence), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(3)
            wav.setframerate(48_000)
            wav.writeframes(b"\x00\x00\x00" * 48_000)
        recording = self.service.store_recording(
            self.session.id, "silence.wav", silence.read_bytes(), "audio/wav"
        )
        result = self.service.analyze_shadowing_exercise_attempt(
            self.session.id,
            created["exercise"]["id"],
            recording.id,
            transcript_hint="おはようございます",
        )
        for name in ("content", "mora", "rhythm", "pitch"):
            self.assertIsNone(result["feedback"][name]["value"])
            self.assertEqual(result["feedback"][name]["confidence"], 0.0)
        self.assertEqual(result["review_item_ids"], [])

    def test_spaced_review_and_anki_payload_do_not_call_anki(self) -> None:
        recording = self._uploaded("recording.wav")
        self.service.process_turn(self.session.id, recording.id, "日本語勉強します")
        due = self.service.due_reviews(self.learner.id, datetime.now(timezone.utc))
        self.assertEqual(len(due), 1)
        updated = self.service.grade_review(due[0].id, 5, datetime(2026, 8, 4, tzinfo=timezone.utc))
        self.assertEqual(updated.interval_days, 1)
        payload = self.service.anki_connect_payload(self.learner.id)
        self.assertEqual(payload["action"], "addNotes")
        self.assertEqual(len(payload["params"]["notes"]), 1)

    def test_provenance_forgery_cross_session_and_tampering_are_rejected(self) -> None:
        reference = self._audio("reference.wav")
        colored_path = self._audio("colored.wav")
        colored = self.service.repository.create_recording(
            RecordingAsset(
                session_id=self.session.id,
                storage_path=str(colored_path),
                sha256=hashlib.sha256(colored_path.read_bytes()).hexdigest(),
                source_type=RecordingSourceType.VOICE_COLORED,
                upload_entry="test:voice-color",
                original_filename="colored.wav",
                content_type="audio/wav",
                byte_size=colored_path.stat().st_size,
            )
        )
        with self.assertRaisesRegex(JapaneseServiceError, "上传入口"):
            self.service.analyze_shadowing_attempt(
                self.session.id,
                reference,
                colored.id,
                "日本語",
                "日本語",
            )
        uploaded = self._uploaded("tamper.wav")
        Path(uploaded.storage_path).write_bytes(Path(uploaded.storage_path).read_bytes() + b"tamper")
        with self.assertRaisesRegex(JapaneseServiceError, "哈希|字节数"):
            self.service.process_turn(self.session.id, uploaded.id, "外部")

        other = self.service.start_session(
            self.learner.id, LearningMode.CONVERSATION, CoachMode.STRICT, "别的会话"
        )
        valid = self._uploaded("cross-session.wav")
        with self.assertRaisesRegex(JapaneseServiceError, "不属于当前会话"):
            self.service.process_turn(other.id, valid.id, "外部")

    def test_profile_pronunciation_plan_progress_and_session_completion(self) -> None:
        updated = self.service.update_learner(
            self.learner.id,
            level="N3",
            mastered_vocabulary=["切符"],
            mastered_grammar=["〜まで"],
            common_pronunciation_errors=["促音が短い", "音高重音"],
        )
        self.assertEqual(updated.level, "N3")
        plan = self.service.create_pronunciation_plan(self.learner.id, limit=2)
        focuses = [exercise["metadata"]["focus"] for exercise in plan["exercises"]]
        self.assertEqual(focuses, ["sokuon", "pitch"])
        self.assertTrue(
            all(
                exercise["metadata"]["selection_evidence"] == "learner_profile_common_error"
                for exercise in plan["exercises"]
            )
        )
        progress = self.service.progress_snapshot(self.learner.id)
        self.assertEqual(progress["counts"]["exercises"], 2)
        self.assertLessEqual(len(progress["today_priorities"]), 2)
        uploaded = self._uploaded("after-complete.wav")
        completed = self.service.complete_session(self.session.id)
        self.assertEqual(completed.status.value, "completed")
        with self.assertRaisesRegex(JapaneseServiceError, "active"):
            self.service.process_turn(self.session.id, uploaded.id, "テスト")

    def test_concurrent_turns_allocate_unique_sequences_and_atomic_reviews(self) -> None:
        recordings = [self._uploaded(f"concurrent-{index}.wav") for index in range(6)]

        def create_turn(recording_id: str):
            return self.service.process_turn(
                self.session.id, recording_id, transcript_hint="日本語勉強します"
            )

        with ThreadPoolExecutor(max_workers=4) as executor:
            turns = list(executor.map(create_turn, [item.id for item in recordings]))
        self.assertEqual(sorted(turn.sequence for turn in turns), [1, 2, 3, 4, 5, 6])
        counts = self.service.repository.counts()
        self.assertEqual(counts["turns"], 6)
        self.assertEqual(counts["reviews"], 6)
        self.assertEqual(
            [row["sequence"] for row in self.service.repository.list_turn_rows(self.session.id)],
            [1, 2, 3, 4, 5, 6],
        )

    def test_failed_atomic_commit_removes_unreferenced_demonstration(self) -> None:
        recording = self._uploaded("rollback.wav")
        turns_root = self.assets / "japanese" / "sessions" / self.session.id / "turns"
        with patch.object(
            self.service.repository,
            "save_turn_with_reviews_atomic",
            side_effect=JapaneseRepositoryError("forced rollback"),
        ):
            with self.assertRaisesRegex(JapaneseServiceError, "forced rollback"):
                self.service.process_turn(
                    self.session.id, recording.id, transcript_hint="日本語勉強します"
                )
        self.assertEqual(self.service.repository.counts()["turns"], 0)
        self.assertEqual(self.service.repository.counts()["reviews"], 0)
        self.assertFalse(any(turns_root.rglob("demonstration.wav")) if turns_root.exists() else False)

    def test_project_lines_become_traceable_lesson_and_health_masks_secret(self) -> None:
        lesson = self.service.create_project_lesson(
            learner_id=self.learner.id,
            source_project_id="project-game-001",
            lesson_mode="shadowing",
            scenario="游戏第一章",
            lines=[
                {
                    "line_id": "line-10",
                    "scene_id": "scene-1",
                    "text": "ここから先は私が案内します。",
                    "speaker": "guide",
                    "listener": "player",
                    "context": "初次见面",
                },
                {
                    "line_id": "line-11",
                    "scene_id": "scene-1",
                    "text": "準備ができたら教えてください。",
                    "speaker": "guide",
                    "listener": "player",
                },
            ],
        )
        self.assertEqual(lesson["session"]["mode"], "project_lesson")
        self.assertEqual(len(lesson["exercises"]), 2)
        self.assertEqual(
            lesson["exercises"][0]["metadata"]["source_line_id"], "line-10"
        )
        self.assertTrue(
            all(Path(item["reference_audio_path"]).is_file() for item in lesson["exercises"])
        )
        with patch.dict(
            "os.environ",
            {
                "VOICE_STUDIO_TEACHER_BASE_URL": "https://example.invalid/v1",
                "VOICE_STUDIO_TEACHER_MODEL": "teacher-model",
                "VOICE_STUDIO_TEACHER_API_KEY": "super-secret-value",
            },
            clear=False,
        ):
            health = self.service.health()
        encoded = json.dumps(health)
        self.assertEqual(health["secrets"]["teacher_api_key"], "configured_masked")
        self.assertNotIn("super-secret-value", encoded)


if __name__ == "__main__":
    unittest.main()
