from __future__ import annotations

import hashlib
import html
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .adapters import AdapterBundle, build_adapters_from_environment
from .curriculum import SCENARIOS, STAGES, catalog as curriculum_catalog, scenario_index
from .models import (
    CoachMode,
    ConversationTurn,
    Exercise,
    ExerciseType,
    LearnerProfile,
    LearningMode,
    LearningSession,
    ProjectLessonMode,
    RecordingAsset,
    RecordingSourceType,
    ReviewItem,
    SessionStatus,
    SourceAudioKind,
    new_id,
    utc_now,
)
from .media import AudioNormalizationError, normalize_browser_audio, resolve_ffmpeg
from .repository import JapaneseRepository, JapaneseRepositoryError
from .scoring import ScoringError, analyze_shadowing


class JapaneseServiceError(RuntimeError):
    pass


_PRONUNCIATION_LIBRARY: dict[str, dict[str, str]] = {
    "long_vowel": {
        "label": "长音",
        "prompt": "区分长短音，先按 mora 慢读，再恢复自然语速。",
        "expected_text": "おばあさんは大阪へ行きます。",
    },
    "sokuon": {
        "label": "促音",
        "prompt": "在「っ」保留一个 mora 的闭塞，不要吞掉。",
        "expected_text": "切手を三枚買ってきました。",
    },
    "hatsuon": {
        "label": "拨音",
        "prompt": "保持「ん」的时值，并观察后续音造成的音色变化。",
        "expected_text": "新宿まで一枚お願いします。",
    },
    "voicing": {
        "label": "清浊音",
        "prompt": "交替练习清音与浊音，避免只靠提高音量。",
        "expected_text": "鍵をかけてから、学校へ行きます。",
    },
    "vowel_reduction": {
        "label": "元音弱化",
        "prompt": "自然弱化高元音，但先保证内容仍可辨识。",
        "expected_text": "よろしくお願いします。",
    },
    "mora": {
        "label": "mora 节奏",
        "prompt": "按 mora 对齐句长和自然停顿，不做整体暴力加速。",
        "expected_text": "東京まで電車でどのくらいかかりますか。",
    },
    "pitch": {
        "label": "音高重音",
        "prompt": "模仿归一化 F0 走势，重点听下降位置而非绝对音高。",
        "expected_text": "雨の日には、飴を一つ買います。",
    },
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class JapaneseLearningService:
    def __init__(
        self,
        repository: JapaneseRepository,
        asset_root: str | Path,
        adapters: AdapterBundle,
    ) -> None:
        self.repository = repository
        self.asset_root = Path(asset_root).resolve()
        self.asset_root.mkdir(parents=True, exist_ok=True)
        self.adapters = adapters

    def _asset_path(self, value: str | Path, *, must_exist: bool = True) -> Path:
        path = Path(value).resolve()
        if not path.is_relative_to(self.asset_root):
            raise JapaneseServiceError("音频路径必须位于 Studio 项目资产目录内。")
        if must_exist and not path.is_file():
            raise JapaneseServiceError(f"音频资产不存在：{path.name}")
        return path

    def create_learner(
        self,
        display_name: str,
        level: str = "beginner",
        goals: list[str] | None = None,
        interests: list[str] | None = None,
    ) -> LearnerProfile:
        display_name = display_name.strip()
        if not display_name:
            raise JapaneseServiceError("学习者名称不能为空。")
        return self.repository.create_profile(
            LearnerProfile(
                display_name=display_name,
                level=level.strip() or "beginner",
                goals=list(goals or []),
                interests=list(interests or []),
            )
        )

    def get_learner(self, learner_id: str) -> LearnerProfile:
        try:
            return self.repository.get_profile(learner_id)
        except JapaneseRepositoryError as exc:
            raise JapaneseServiceError(str(exc)) from exc

    def update_learner(
        self,
        learner_id: str,
        *,
        display_name: str | None = None,
        level: str | None = None,
        goals: list[str] | None = None,
        mastered_vocabulary: list[str] | None = None,
        mastered_grammar: list[str] | None = None,
        common_pronunciation_errors: list[str] | None = None,
        interests: list[str] | None = None,
    ) -> LearnerProfile:
        profile = self.get_learner(learner_id)
        if display_name is not None:
            if not display_name.strip():
                raise JapaneseServiceError("学习者名称不能为空。")
            profile.display_name = display_name.strip()
        if level is not None:
            profile.level = level.strip() or profile.level
        for attribute, value in (
            ("goals", goals),
            ("mastered_vocabulary", mastered_vocabulary),
            ("mastered_grammar", mastered_grammar),
            ("common_pronunciation_errors", common_pronunciation_errors),
            ("interests", interests),
        ):
            if value is not None:
                setattr(profile, attribute, [str(item).strip() for item in value if str(item).strip()])
        profile.updated_at = utc_now()
        try:
            return self.repository.update_profile(profile)
        except JapaneseRepositoryError as exc:
            raise JapaneseServiceError(str(exc)) from exc

    def start_session(
        self,
        learner_id: str,
        mode: LearningMode | str,
        coach_mode: CoachMode | str,
        scenario: str,
        metadata: dict[str, Any] | None = None,
    ) -> LearningSession:
        try:
            learning_mode = mode if isinstance(mode, LearningMode) else LearningMode(mode)
            coaching = coach_mode if isinstance(coach_mode, CoachMode) else CoachMode(coach_mode)
            session = LearningSession(
                learner_id=learner_id,
                mode=learning_mode,
                coach_mode=coaching,
                scenario=scenario.strip() or "日常会话",
                metadata=dict(metadata or {}),
            )
            return self.repository.create_session(session)
        except (ValueError, JapaneseRepositoryError) as exc:
            raise JapaneseServiceError(str(exc)) from exc

    def get_session(self, session_id: str) -> LearningSession:
        try:
            return self.repository.get_session(session_id)
        except JapaneseRepositoryError as exc:
            raise JapaneseServiceError(str(exc)) from exc

    def list_sessions(self, learner_id: str) -> list[LearningSession]:
        try:
            return self.repository.list_sessions(learner_id)
        except JapaneseRepositoryError as exc:
            raise JapaneseServiceError(str(exc)) from exc

    def list_turns(self, session_id: str) -> list[dict[str, Any]]:
        self.get_session(session_id)
        return self.repository.list_turn_rows(session_id)

    def complete_session(self, session_id: str) -> LearningSession:
        session = self.get_session(session_id)
        curriculum_scenario_id = str(session.metadata.get("curriculum_scenario_id", "")).strip()
        if curriculum_scenario_id:
            scenario = scenario_index().get(curriculum_scenario_id)
            if scenario is None:
                raise JapaneseServiceError("课程场景不存在或版本不兼容，不能写入完成状态。")
            minimum_turns = int(scenario["completion_policy"]["minimum_turns"])
            turn_count = len(self.list_turns(session_id))
            if turn_count < minimum_turns:
                raise JapaneseServiceError(
                    f"完成课程场景前至少需要 {minimum_turns} 轮持久化练习；当前 {turn_count} 轮。"
                )
        try:
            return self.repository.complete_session(session_id, utc_now())
        except JapaneseRepositoryError as exc:
            raise JapaneseServiceError(str(exc)) from exc

    def store_recording(
        self,
        session_id: str,
        filename: str,
        content: bytes,
        content_type: str = "audio/wav",
    ) -> RecordingAsset:
        self.get_session(session_id)
        if not content:
            raise JapaneseServiceError("录音内容为空。")
        if len(content) > 20 * 1024 * 1024:
            raise JapaneseServiceError("单个录音不能超过 20 MB。")
        safe_name = Path(filename).name
        if not safe_name or safe_name in {".", ".."}:
            raise JapaneseServiceError("录音文件名无效。")
        directory = self.asset_root / "japanese" / "sessions" / session_id / "recordings"
        directory.mkdir(parents=True, exist_ok=True)
        recording_id = new_id("recording")
        output = directory / f"{recording_id}.wav"
        try:
            normalize_browser_audio(content, content_type, output)
        except AudioNormalizationError as exc:
            output.unlink(missing_ok=True)
            raise JapaneseServiceError(str(exc)) from exc
        recording = RecordingAsset(
            id=recording_id,
            session_id=session_id,
            storage_path=str(output),
            sha256=_sha256(output),
            source_type=RecordingSourceType.BROWSER_ORIGINAL_UPLOAD,
            upload_entry="api:/api/japanese/recordings",
            original_filename=safe_name,
            content_type=content_type,
            byte_size=output.stat().st_size,
        )
        try:
            return self.repository.create_recording(recording)
        except Exception as exc:
            output.unlink(missing_ok=True)
            raise JapaneseServiceError("录音来源登记失败；未引用的规范化音频已清理。") from exc

    def _verified_original_recording(
        self, session_id: str, recording_id: str
    ) -> tuple[RecordingAsset, Path]:
        try:
            recording = self.repository.get_recording(recording_id)
        except JapaneseRepositoryError as exc:
            raise JapaneseServiceError(str(exc)) from exc
        if recording.session_id != session_id:
            raise JapaneseServiceError("录音来源记录不属于当前会话。")
        if (
            recording.source_type is not RecordingSourceType.BROWSER_ORIGINAL_UPLOAD
            or recording.upload_entry != "api:/api/japanese/recordings"
        ):
            raise JapaneseServiceError("评分只接受经录音上传入口登记的原始麦克风录音。")
        path = self._asset_path(recording.storage_path)
        if path.stat().st_size != recording.byte_size or _sha256(path) != recording.sha256:
            raise JapaneseServiceError("原始录音哈希或字节数与不可变来源记录不一致，请重新上传。")
        return recording, path

    @staticmethod
    def _cleanup_uncommitted_audio(path: Path) -> None:
        path.unlink(missing_ok=True)
        try:
            path.parent.rmdir()
        except OSError:
            pass

    def process_turn(
        self,
        session_id: str,
        recording_id: str,
        transcript_hint: str | None = None,
        expected_text: str | None = None,
        voice_role: str = "standard_tokyo",
    ) -> ConversationTurn:
        session = self.get_session(session_id)
        if session.status is not SessionStatus.ACTIVE:
            raise JapaneseServiceError("只有 active 会话可以新增轮次。")
        recording_asset, recording_path = self._verified_original_recording(
            session_id, recording_id
        )
        transcript = self.adapters.asr.transcribe(recording_path, transcript_hint)
        learner = self.get_learner(session.learner_id)
        teacher = self.adapters.teacher.teach(
            {
                "task": "half_duplex_conversation_turn",
                "learner": learner.to_dict(),
                "session_mode": session.mode.value,
                "coach_mode": session.coach_mode.value,
                "scenario": session.scenario,
                "transcript": transcript.text,
                "expected_text": expected_text,
            }
        )
        feedback_limit = 1 if session.coach_mode is CoachMode.FLUENT else 2
        teacher.feedback = teacher.feedback[:feedback_limit]
        if teacher.repair is not None:
            teacher.repair.issues = teacher.repair.issues[:feedback_limit]

        turn_id = new_id("turn")
        demonstration_path = (
            self.asset_root
            / "japanese"
            / "sessions"
            / session_id
            / "turns"
            / turn_id
            / "demonstration.wav"
        )
        reviews: list[ReviewItem] = []
        if teacher.repair and teacher.repair.issues:
            for index, issue in enumerate(teacher.repair.issues):
                reviews.append(
                    ReviewItem(
                        learner_id=session.learner_id,
                        error_key=f"sentence-repair:{index}:{hashlib.sha1(issue.encode('utf-8')).hexdigest()[:10]}",
                        prompt=teacher.repair.original,
                        answer=teacher.repair.natural_expression,
                        evidence={
                            "issue": issue,
                            "turn_id": turn_id,
                            "teacher_confidence": teacher.confidence,
                        },
                    )
                )
        try:
            demonstration = self.adapters.tts.synthesize(
                teacher.demonstration_text or teacher.reply_text,
                demonstration_path,
                voice_role,
            )
            turn = ConversationTurn(
                id=turn_id,
                session_id=session_id,
                recording_id=recording_asset.id,
                sequence=0,
                original_audio_path=str(recording_path),
                original_audio_sha256=recording_asset.sha256,
                transcript=transcript,
                teacher=teacher,
                demonstration=demonstration,
                scoring_source_kind=SourceAudioKind.ORIGINAL_UNCOLORED,
            )
            return self.repository.save_turn_with_reviews_atomic(turn, reviews)
        except JapaneseRepositoryError as exc:
            self._cleanup_uncommitted_audio(demonstration_path)
            raise JapaneseServiceError(str(exc)) from exc
        except Exception:
            self._cleanup_uncommitted_audio(demonstration_path)
            raise

    def turn_demonstration_path(self, turn_id: str) -> Path:
        try:
            turn = self.repository.get_turn_row(turn_id)
        except JapaneseRepositoryError as exc:
            raise JapaneseServiceError(str(exc)) from exc
        path = turn.get("demonstration", {}).get("audio_path")
        if not path:
            raise JapaneseServiceError("该轮次没有可播放的示范音频。")
        return self._asset_path(path)

    def repair_sentence(
        self,
        learner_id: str,
        original: str,
        scenario: str = "日常会话",
        coach_mode: CoachMode | str = CoachMode.STRICT,
    ) -> dict[str, Any]:
        learner = self.get_learner(learner_id)
        coaching = coach_mode if isinstance(coach_mode, CoachMode) else CoachMode(coach_mode)
        result = self.adapters.teacher.teach(
            {
                "task": "sentence_repair",
                "learner": learner.to_dict(),
                "scenario": scenario,
                "coach_mode": coaching.value,
                "transcript": original.strip(),
            }
        )
        limit = 1 if coaching is CoachMode.FLUENT else 2
        result.feedback = result.feedback[:limit]
        if result.repair is not None:
            result.repair.issues = result.repair.issues[:limit]
        return result.to_dict()

    def create_shadowing_reference(
        self,
        session_id: str,
        expected_text: str,
        voice_role: str = "standard_tokyo",
    ) -> dict[str, Any]:
        session = self.get_session(session_id)
        if session.status is not SessionStatus.ACTIVE:
            raise JapaneseServiceError("只有 active 会话可以创建跟读参考。")
        text = expected_text.strip()
        if not text:
            raise JapaneseServiceError("跟读参考文本不能为空。")
        exercise = Exercise(
            learner_id=session.learner_id,
            session_id=session.id,
            exercise_type=ExerciseType.SHADOWING,
            prompt="听参考音、录原声、A/B 复听并立即重说。",
            expected_text=text,
            metadata={
                "scoring_version": "lightweight-explainable/1",
                "reference_voice_role": voice_role,
            },
        )
        reference_path = (
            self.asset_root
            / "japanese"
            / "sessions"
            / session_id
            / "references"
            / f"{exercise.id}.wav"
        )
        synthesis = self.adapters.tts.synthesize(text, reference_path, voice_role)
        exercise.reference_audio_path = synthesis.audio_path
        try:
            self.repository.create_exercise(exercise)
        except Exception:
            reference_path.unlink(missing_ok=True)
            raise
        return {"exercise": exercise.to_dict(), "synthesis": synthesis.to_dict()}

    def exercise_reference_path(self, exercise_id: str) -> Path:
        try:
            exercise = self.repository.get_exercise(exercise_id)
        except JapaneseRepositoryError as exc:
            raise JapaneseServiceError(str(exc)) from exc
        if not exercise.reference_audio_path:
            raise JapaneseServiceError("该练习没有参考音频。")
        return self._asset_path(exercise.reference_audio_path)

    def analyze_shadowing_attempt(
        self,
        session_id: str,
        reference_audio_path: str | Path,
        recording_id: str,
        expected_text: str,
        transcript_hint: str | None = None,
        reuse_exercise_id: str | None = None,
    ) -> dict[str, Any]:
        session = self.get_session(session_id)
        if session.status is not SessionStatus.ACTIVE:
            raise JapaneseServiceError("只有 active 会话可以提交影子跟读。")
        exercise: Exercise | None = None
        if reuse_exercise_id:
            try:
                exercise = self.repository.get_exercise(reuse_exercise_id)
            except JapaneseRepositoryError as exc:
                raise JapaneseServiceError(str(exc)) from exc
            if exercise.learner_id != session.learner_id:
                raise JapaneseServiceError("练习不属于当前学习者。")
            if exercise.session_id not in {None, session.id}:
                raise JapaneseServiceError("练习不属于当前会话。")
            if exercise.exercise_type is not ExerciseType.SHADOWING:
                raise JapaneseServiceError("只有 shadowing 练习可以提交跟读录音。")
            if not exercise.reference_audio_path:
                raise JapaneseServiceError("练习没有参考音频。")
            reference_audio_path = exercise.reference_audio_path
            expected_text = exercise.expected_text
        reference = self._asset_path(reference_audio_path)
        recording_asset, recording_path = self._verified_original_recording(
            session_id, recording_id
        )
        transcript = self.adapters.asr.transcribe(recording_path, transcript_hint)
        try:
            feedback = analyze_shadowing(
                reference_audio_path=reference,
                original_recording_path=recording_path,
                expected_text=expected_text,
                actual_transcript=transcript.text,
                asr_confidence=transcript.confidence,
                source_kind=SourceAudioKind.ORIGINAL_UNCOLORED,
            )
        except ScoringError as exc:
            raise JapaneseServiceError(str(exc)) from exc

        create_exercise = exercise is None
        if exercise is None:
            exercise = Exercise(
                learner_id=session.learner_id,
                session_id=session.id,
                exercise_type=ExerciseType.SHADOWING,
                prompt="听参考音、录原声、A/B 复听并立即重说。",
                expected_text=expected_text,
                reference_audio_path=str(reference),
                metadata={"scoring_version": "lightweight-explainable/1"},
            )
        attempt_id = new_id("shadow")

        metrics = [feedback.content, feedback.rhythm, feedback.pitch]
        ranked = (
            []
            if all(metric.value is None for metric in metrics)
            else sorted(metrics, key=lambda item: -1.0 if item.value is None else item.value)
        )
        reviews: list[ReviewItem] = []
        for metric in ranked[:2]:
            if metric.value is not None and metric.value >= 0.88:
                continue
            reviews.append(
                ReviewItem(
                    learner_id=session.learner_id,
                    exercise_id=exercise.id,
                    error_key=f"shadowing:{metric.metric}",
                    prompt=expected_text,
                    answer=f"重新影子跟读并关注 {metric.metric}：{metric.summary}",
                    evidence=metric.to_dict(),
                )
            )
        try:
            self.repository.save_shadow_submission_atomic(
                exercise=exercise,
                create_exercise=create_exercise,
                attempt_id=attempt_id,
                recording_id=recording_asset.id,
                original_recording_path=str(recording_path),
                original_recording_sha256=recording_asset.sha256,
                transcript=transcript.to_dict(),
                feedback=feedback,
                created_at=utc_now(),
                reviews=reviews,
            )
        except JapaneseRepositoryError as exc:
            raise JapaneseServiceError(str(exc)) from exc
        return {
            "attempt_id": attempt_id,
            "exercise": exercise.to_dict(),
            "transcript": transcript.to_dict(),
            "feedback": feedback.to_dict(),
            "ab_playback": {
                "reference_audio_path": str(reference),
                "original_recording_path": str(recording_path),
                "recording_id": recording_asset.id,
            },
            "review_item_ids": [item.id for item in reviews],
        }

    def analyze_shadowing_exercise_attempt(
        self,
        session_id: str,
        exercise_id: str,
        recording_id: str,
        transcript_hint: str | None = None,
    ) -> dict[str, Any]:
        try:
            exercise = self.repository.get_exercise(exercise_id)
        except JapaneseRepositoryError as exc:
            raise JapaneseServiceError(str(exc)) from exc
        return self.analyze_shadowing_attempt(
            session_id=session_id,
            reference_audio_path=exercise.reference_audio_path or "",
            recording_id=recording_id,
            expected_text=exercise.expected_text,
            transcript_hint=transcript_hint,
            reuse_exercise_id=exercise_id,
        )

    def create_project_lesson(
        self,
        learner_id: str,
        source_project_id: str,
        lesson_mode: ProjectLessonMode | str,
        lines: list[dict[str, Any]],
        *,
        scenario: str = "项目场景学习",
        coach_mode: CoachMode | str = CoachMode.STRICT,
        reference_voice_role: str = "standard_tokyo",
    ) -> dict[str, Any]:
        self.get_learner(learner_id)
        try:
            mode = lesson_mode if isinstance(lesson_mode, ProjectLessonMode) else ProjectLessonMode(lesson_mode)
            coaching = coach_mode if isinstance(coach_mode, CoachMode) else CoachMode(coach_mode)
        except ValueError as exc:
            raise JapaneseServiceError("未知的项目课程模式或教练模式。") from exc
        if not lines:
            raise JapaneseServiceError("项目课程至少需要一条台词。")
        if len(lines) > 100:
            raise JapaneseServiceError("单次项目课程最多导入 100 条台词。")
        prepared: list[dict[str, Any]] = []
        for index, line in enumerate(lines):
            text = str(line.get("text", "")).strip()
            if not text:
                raise JapaneseServiceError(f"第 {index + 1} 条课程台词为空。")
            reference = line.get("reference_audio_path")
            prepared.append(
                {
                    **line,
                    "text": text,
                    "reference_audio_path": (
                        str(self._asset_path(str(reference))) if reference else None
                    ),
                }
            )

        session = self.start_session(
            learner_id=learner_id,
            mode=LearningMode.PROJECT_LESSON,
            coach_mode=coaching,
            scenario=scenario,
            metadata={
                "source_project_id": source_project_id,
                "lesson_mode": mode.value,
                "source_line_count": len(prepared),
            },
        )
        exercise_type = ExerciseType(mode.value)
        prompt_by_mode = {
            ProjectLessonMode.DICTATION: "先听参考音，再写出完整台词并核对证据。",
            ProjectLessonMode.SHADOWING: "A/B 听参考音与原声，按证据立即重说。",
            ProjectLessonMode.ROLE_PLAY: "根据 speaker/listener/context 进入角色并回应。",
        }
        exercises: list[dict[str, Any]] = []
        for index, line in enumerate(prepared):
            exercise = Exercise(
                learner_id=learner_id,
                session_id=session.id,
                exercise_type=exercise_type,
                prompt=prompt_by_mode[mode],
                expected_text=line["text"],
                reference_audio_path=line["reference_audio_path"],
                metadata={
                    "source_project_id": source_project_id,
                    "source_scene_id": line.get("scene_id"),
                    "source_line_id": line.get("line_id"),
                    "speaker": line.get("speaker"),
                    "listener": line.get("listener"),
                    "context": line.get("context"),
                    "translation": line.get("translation"),
                    "locale": line.get("locale", "ja-JP"),
                    "ordinal": index,
                    "derivation": "structured_project_line",
                },
            )
            if not exercise.reference_audio_path:
                reference_path = (
                    self.asset_root
                    / "japanese"
                    / "sessions"
                    / session.id
                    / "project-lesson-references"
                    / f"{exercise.id}.wav"
                )
                synthesis = self.adapters.tts.synthesize(
                    exercise.expected_text, reference_path, reference_voice_role
                )
                exercise.reference_audio_path = synthesis.audio_path
                exercise.metadata["reference_generated_by"] = synthesis.provider
                exercise.metadata["reference_voice_role"] = synthesis.voice_role
            saved = self.repository.create_exercise(exercise)
            item = saved.to_dict()
            item["reference_audio_url"] = f"/api/japanese/exercises/{saved.id}/reference"
            exercises.append(item)
        return {
            "session": session.to_dict(),
            "source_project_id": source_project_id,
            "lesson_mode": mode.value,
            "exercises": exercises,
            "policy": "structured_derivation_with_source_evidence",
        }

    def grade_review(
        self,
        review_id: str,
        quality: int,
        reviewed_at: datetime | None = None,
    ) -> ReviewItem:
        if quality < 0 or quality > 5:
            raise JapaneseServiceError("复习质量必须是 0 到 5 的整数。")
        try:
            item = self.repository.get_review_item(review_id)
        except JapaneseRepositoryError as exc:
            raise JapaneseServiceError(str(exc)) from exc
        now = reviewed_at or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        if quality < 3:
            item.repetitions = 0
            item.interval_days = 1
        else:
            item.repetitions += 1
            if item.repetitions == 1:
                item.interval_days = 1
            elif item.repetitions == 2:
                item.interval_days = 6
            else:
                item.interval_days = max(1, round(item.interval_days * item.ease_factor))
        delta = 5 - quality
        item.ease_factor = max(1.3, item.ease_factor + (0.1 - delta * (0.08 + delta * 0.02)))
        item.last_quality = quality
        item.due_at = (now + timedelta(days=item.interval_days)).isoformat(timespec="seconds")
        item.updated_at = now.isoformat(timespec="seconds")
        return self.repository.update_review_item(item)

    def due_reviews(self, learner_id: str, at: datetime | None = None) -> list[ReviewItem]:
        self.get_learner(learner_id)
        now = at or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return self.repository.list_due_reviews(learner_id, now.isoformat(timespec="seconds"))

    def anki_connect_payload(self, learner_id: str, deck_name: str = "Local AI Voice Studio::日本語") -> dict[str, Any]:
        self.get_learner(learner_id)
        notes = []
        for item in self.repository.list_review_items(learner_id):
            evidence = html.escape(str(item.evidence), quote=True)
            notes.append(
                {
                    "deckName": deck_name,
                    "modelName": "Basic",
                    "fields": {
                        "Front": html.escape(item.prompt, quote=True),
                        "Back": html.escape(item.answer, quote=True) + f"<hr><small>{evidence}</small>",
                    },
                    "options": {"allowDuplicate": False},
                    "tags": ["local-ai-voice-studio", "japanese", item.error_key.replace(":", "-")],
                }
            )
        return {"action": "addNotes", "version": 6, "params": {"notes": notes}}

    def progress_snapshot(self, learner_id: str) -> dict[str, Any]:
        profile = self.get_learner(learner_id)
        counts = self.repository.progress_counts(learner_id)
        due = self.due_reviews(learner_id)
        attempts = self.repository.recent_shadow_feedback(learner_id, limit=20)
        metrics: dict[str, dict[str, Any]] = {}
        for metric_name in ("content", "rhythm", "pitch"):
            values: list[float] = []
            confidences: list[float] = []
            for row in attempts:
                metric = row["feedback"].get(metric_name, {})
                value = metric.get("value")
                confidence = metric.get("confidence")
                if isinstance(value, (int, float)):
                    values.append(float(value))
                if isinstance(confidence, (int, float)):
                    confidences.append(float(confidence))
            if values:
                recent = values[: min(5, len(values))]
                previous = values[min(5, len(values)) : min(10, len(values))]
                recent_mean = sum(recent) / len(recent)
                previous_mean = sum(previous) / len(previous) if previous else None
                if previous_mean is None:
                    direction = "insufficient_history"
                elif recent_mean > previous_mean + 0.03:
                    direction = "improving"
                elif recent_mean < previous_mean - 0.03:
                    direction = "needs_attention"
                else:
                    direction = "stable"
                metrics[metric_name] = {
                    "recent_mean": round(recent_mean, 4),
                    "mean_confidence": round(
                        sum(confidences[: len(recent)]) / max(len(confidences[: len(recent)]), 1), 4
                    ),
                    "sample_count": len(values),
                    "direction": direction,
                    "evidence_window": "latest_5_vs_previous_5_attempts",
                }
            else:
                metrics[metric_name] = {
                    "recent_mean": None,
                    "mean_confidence": 0.0,
                    "sample_count": 0,
                    "direction": "insufficient_evidence",
                    "evidence_window": "no_scored_shadow_attempt",
                }

        ranked = sorted(
            metrics.items(),
            key=lambda item: -1.0 if item[1]["recent_mean"] is None else item[1]["recent_mean"],
        )
        priorities: list[dict[str, Any]] = []
        for metric_name, metric in ranked:
            if len(priorities) == 2:
                break
            priorities.append(
                {
                    "kind": "metric",
                    "metric": metric_name,
                    "reason": (
                        "证据不足，先完成一次原声影子跟读。"
                        if metric["recent_mean"] is None
                        else "近期分项均值较低，优先安排针对性重说。"
                    ),
                    "evidence": metric,
                }
            )
        if due:
            priorities = [
                {
                    "kind": "review",
                    "review_id": due[0].id,
                    "reason": "错项已到复习时间。",
                    "evidence": {"due_at": due[0].due_at, "error_key": due[0].error_key},
                },
                *priorities,
            ][:2]
        return {
            "learner_id": learner_id,
            "level": profile.level,
            "counts": counts,
            "due_review_count": len(due),
            "metrics": metrics,
            "today_priorities": priorities,
            "policy": "separate_metrics_only_no_overall_score",
            "generated_at": utc_now(),
        }

    def curriculum(self) -> dict[str, Any]:
        return curriculum_catalog()

    def learning_path(self, learner_id: str) -> dict[str, Any]:
        profile = self.get_learner(learner_id)
        sessions = self.list_sessions(learner_id)
        due = self.due_reviews(learner_id)
        index = scenario_index()
        title_to_id = {item["title"]: item["id"] for item in SCENARIOS}
        evidence_by_scenario: dict[str, dict[str, Any]] = {}

        for session in sessions:
            scenario_id = str(session.metadata.get("curriculum_scenario_id", "")).strip()
            if not scenario_id:
                scenario_id = title_to_id.get(session.scenario, "")
            if scenario_id not in index:
                continue
            try:
                turn_count = len(self.list_turns(session.id))
            except JapaneseServiceError:
                turn_count = 0
            evidence = evidence_by_scenario.setdefault(
                scenario_id,
                {
                    "session_ids": [],
                    "completed_session_count": 0,
                    "active_session_count": 0,
                    "turn_count": 0,
                    "last_started_at": session.started_at,
                },
            )
            evidence["session_ids"].append(session.id)
            evidence["turn_count"] += turn_count
            evidence["last_started_at"] = max(evidence["last_started_at"], session.started_at)
            if session.status is SessionStatus.COMPLETED:
                evidence["completed_session_count"] += 1
            elif session.status is SessionStatus.ACTIVE:
                evidence["active_session_count"] += 1

        completed_ids = {
            scenario_id
            for scenario_id, evidence in evidence_by_scenario.items()
            if evidence["completed_session_count"] > 0
        }
        in_progress_ids = {
            scenario_id
            for scenario_id, evidence in evidence_by_scenario.items()
            if scenario_id not in completed_ids
            and (evidence["active_session_count"] > 0 or evidence["turn_count"] > 0)
        }
        level_rank = {"beginner": 0, "N5": 0, "N4": 1, "N3": 2, "N2": 3, "N1": 4}
        placement = profile.level.upper() if profile.level.upper() in level_rank else profile.level
        placement_rank = level_rank.get(placement, 0)

        stage_rows: list[dict[str, Any]] = []
        available_ids: set[str] = set()
        locked_ids: set[str] = set()
        for stage in STAGES:
            scenario_rows: list[dict[str, Any]] = []
            for scenario in (item for item in SCENARIOS if item["stage_id"] == stage["id"]):
                scenario_level_rank = level_rank.get(scenario["level"], 4)
                prerequisite_ids = set(scenario["prerequisites"])
                prerequisite_complete = prerequisite_ids.issubset(completed_ids)
                placement_available = scenario_level_rank <= placement_rank
                if scenario["id"] in completed_ids:
                    status = "completed"
                elif scenario["id"] in in_progress_ids:
                    status = "in_progress"
                elif placement_available or prerequisite_complete or not prerequisite_ids:
                    status = "available"
                    available_ids.add(scenario["id"])
                else:
                    status = "locked"
                    locked_ids.add(scenario["id"])
                scenario_rows.append(
                    {
                        **scenario,
                        "status": status,
                        "missing_prerequisites": sorted(prerequisite_ids - completed_ids),
                        "evidence": evidence_by_scenario.get(
                            scenario["id"],
                            {
                                "session_ids": [],
                                "completed_session_count": 0,
                                "active_session_count": 0,
                                "turn_count": 0,
                                "last_started_at": None,
                            },
                        ),
                    }
                )
            completed_count = sum(item["status"] == "completed" for item in scenario_rows)
            stage_rows.append(
                {
                    **stage,
                    "scenarios": scenario_rows,
                    "completion": {
                        "completed": completed_count,
                        "total": len(scenario_rows),
                        "ratio": round(completed_count / max(len(scenario_rows), 1), 4),
                        "meaning": "场景练习完成比例，不是语言能力总分。",
                    },
                }
            )

        recommendations: list[dict[str, Any]] = []
        if due:
            recommendations.append(
                {
                    "kind": "review",
                    "review_id": due[0].id,
                    "title": "先清理到期错项",
                    "reason": "间隔复习已到期，优先于继续堆叠新场景。",
                    "evidence": {"due_count": len(due), "due_at": due[0].due_at},
                }
            )
        for scenario_id in sorted(
            in_progress_ids,
            key=lambda value: evidence_by_scenario[value]["last_started_at"],
            reverse=True,
        ):
            if len(recommendations) >= 3:
                break
            recommendations.append(
                {
                    "kind": "continue_scenario",
                    "scenario_id": scenario_id,
                    "title": f"继续：{index[scenario_id]['title']}",
                    "reason": "已有未完成会话，先完成再开启新主题。",
                    "evidence": evidence_by_scenario[scenario_id],
                }
            )
        candidates = [
            item
            for item in SCENARIOS
            if item["id"] in available_ids and item["id"] not in completed_ids
        ]
        candidates.sort(
            key=lambda item: (
                abs(level_rank.get(item["level"], 4) - placement_rank),
                list(index).index(item["id"]),
            )
        )
        for scenario in candidates:
            if len(recommendations) >= 3:
                break
            recommendations.append(
                {
                    "kind": "new_scenario",
                    "scenario_id": scenario["id"],
                    "title": f"下一场：{scenario['title']}",
                    "reason": "符合当前等级且先修条件已满足，建议完成至少三轮后手动结束。",
                    "evidence": {
                        "level": scenario["level"],
                        "prerequisites": scenario["prerequisites"],
                    },
                }
            )

        return {
            "catalog_version": curriculum_catalog()["version"],
            "learner_id": learner_id,
            "placement_level": profile.level,
            "summary": {
                "completed": len(completed_ids),
                "in_progress": len(in_progress_ids),
                "available": len(available_ids),
                "locked": len(locked_ids),
                "total": len(SCENARIOS),
                "due_review_count": len(due),
            },
            "stages": stage_rows,
            "recommendations": recommendations,
            "curve": [
                {
                    "stage_id": stage["id"],
                    "label": stage["title"],
                    "completed": stage["completion"]["completed"],
                    "total": stage["completion"]["total"],
                    "ratio": stage["completion"]["ratio"],
                }
                for stage in stage_rows
            ],
            "policy": {
                "unlocking": "declared_level_or_completed_prerequisites",
                "completion": "manual_session_completion_with_persisted_session_evidence",
                "assessment": "separate_metrics_only_no_overall_language_score",
                "recommendation_order": "due_review_then_in_progress_then_level_matched_available",
            },
            "generated_at": utc_now(),
        }

    def create_pronunciation_plan(self, learner_id: str, limit: int = 3) -> dict[str, Any]:
        profile = self.get_learner(learner_id)
        bounded_limit = max(1, min(limit, 6))
        text = " ".join(profile.common_pronunciation_errors).lower()
        aliases = {
            "long_vowel": ("长音", "長音", "long"),
            "sokuon": ("促音", "っ", "sokuon"),
            "hatsuon": ("拨音", "撥音", "ん", "hatsuon"),
            "voicing": ("清浊", "清濁", "浊音", "濁音", "voicing"),
            "vowel_reduction": ("弱化", "母音", "vowel"),
            "mora": ("mora", "节奏", "節奏"),
            "pitch": ("音高", "重音", "pitch", "アクセント"),
        }
        matched = [
            key for key, keywords in aliases.items() if any(keyword.lower() in text for keyword in keywords)
        ]
        selected = list(matched)
        for fallback in ("mora", "long_vowel", "pitch", "sokuon", "hatsuon"):
            if fallback not in selected:
                selected.append(fallback)
        exercises: list[dict[str, Any]] = []
        for focus in selected[:bounded_limit]:
            template = _PRONUNCIATION_LIBRARY[focus]
            exercise = self.repository.create_exercise(
                Exercise(
                    learner_id=learner_id,
                    session_id=None,
                    exercise_type=ExerciseType.PRONUNCIATION,
                    prompt=template["prompt"],
                    expected_text=template["expected_text"],
                    metadata={
                        "focus": focus,
                        "label": template["label"],
                        "selection_evidence": (
                            "learner_profile_common_error" if focus in matched else "default_mvp_plan"
                        ),
                        "selection_confidence": 0.55 if text else 0.35,
                    },
                )
            )
            exercises.append(exercise.to_dict())
        return {
            "learner_id": learner_id,
            "exercises": exercises,
            "selection_policy": "profile_keywords_then_default_foundation",
            "limitations": ["首版计划是透明规则，不代表教师诊断或经过标定的个性化推荐。"],
        }

    def health(self) -> dict[str, Any]:
        ffmpeg = resolve_ffmpeg()
        teacher_fields = (
            os.getenv("VOICE_STUDIO_TEACHER_BASE_URL"),
            os.getenv("VOICE_STUDIO_TEACHER_API_KEY"),
            os.getenv("VOICE_STUDIO_TEACHER_MODEL"),
        )
        return {
            "status": "ok",
            "counts": self.repository.counts(),
            "scoring_policy": "original_uncolored_only",
            "score_shape": "separate_metrics_with_evidence_and_confidence_no_overall_score",
            "adapters": {
                "asr": (
                    "configured_local_subprocess"
                    if os.getenv("VOICE_STUDIO_JP_ASR_COMMAND_JSON")
                    else "mock"
                ),
                "teacher": "configured_openai_compatible" if all(teacher_fields) else "mock",
                "tts": (
                    "configured_local_subprocess"
                    if os.getenv("VOICE_STUDIO_JP_TTS_COMMAND_JSON")
                    else "mock"
                ),
                "ffmpeg_available": ffmpeg is not None,
            },
            "secrets": {
                "teacher_api_key": (
                    "configured_masked" if os.getenv("VOICE_STUDIO_TEACHER_API_KEY") else "not_configured"
                )
            },
        }


def build_default_service(database_path: str | Path, asset_root: str | Path) -> JapaneseLearningService:
    return JapaneseLearningService(
        repository=JapaneseRepository(database_path),
        asset_root=asset_root,
        adapters=build_adapters_from_environment(),
    )
