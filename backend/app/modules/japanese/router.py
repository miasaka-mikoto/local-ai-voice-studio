from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .models import CoachMode, LearningMode, ProjectLessonMode, SourceAudioKind
from .service import JapaneseLearningService, JapaneseServiceError, build_default_service


class LearnerCreateRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    level: str = Field(default="beginner", max_length=80)
    goals: list[str] = Field(default_factory=list, max_length=100)
    interests: list[str] = Field(default_factory=list, max_length=100)


class LearnerUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    level: str | None = Field(default=None, max_length=80)
    goals: list[str] | None = Field(default=None, max_length=500)
    mastered_vocabulary: list[str] | None = Field(default=None, max_length=5_000)
    mastered_grammar: list[str] | None = Field(default=None, max_length=2_000)
    common_pronunciation_errors: list[str] | None = Field(default=None, max_length=500)
    interests: list[str] | None = Field(default=None, max_length=500)


class SessionCreateRequest(BaseModel):
    learner_id: str
    mode: LearningMode = LearningMode.CONVERSATION
    coach_mode: CoachMode = CoachMode.FLUENT
    scenario: str = Field(default="日常会话", max_length=500)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConversationTurnRequest(BaseModel):
    recording_id: str
    transcript_hint: str | None = Field(default=None, max_length=5_000)
    expected_text: str | None = Field(default=None, max_length=5_000)
    voice_role: str = Field(default="standard_tokyo", pattern="^(standard_tokyo|immersive_character)$")


class SentenceRepairRequest(BaseModel):
    learner_id: str
    original: str = Field(min_length=1, max_length=5_000)
    scenario: str = Field(default="日常会话", max_length=500)
    coach_mode: CoachMode = CoachMode.STRICT


class ShadowAttemptRequest(BaseModel):
    reference_audio_path: str
    recording_id: str
    expected_text: str = Field(min_length=1, max_length=5_000)
    transcript_hint: str | None = Field(default=None, max_length=5_000)


class ShadowReferenceRequest(BaseModel):
    expected_text: str = Field(min_length=1, max_length=5_000)
    voice_role: str = Field(default="standard_tokyo", pattern="^(standard_tokyo|immersive_character)$")


class ExistingShadowAttemptRequest(BaseModel):
    recording_id: str
    transcript_hint: str | None = Field(default=None, max_length=5_000)


class ReviewGradeRequest(BaseModel):
    quality: int = Field(ge=0, le=5)


class PronunciationPlanRequest(BaseModel):
    limit: int = Field(default=3, ge=1, le=6)


class ProjectLessonLineRequest(BaseModel):
    line_id: str | None = None
    scene_id: str | None = None
    text: str = Field(min_length=1, max_length=5_000)
    translation: str | None = Field(default=None, max_length=5_000)
    speaker: str | None = Field(default=None, max_length=200)
    listener: str | None = Field(default=None, max_length=200)
    context: str | None = Field(default=None, max_length=5_000)
    locale: str = Field(default="ja-JP", max_length=40)
    reference_audio_path: str | None = None


class ProjectLessonRequest(BaseModel):
    source_project_id: str
    lesson_mode: ProjectLessonMode
    scenario: str = Field(default="项目场景学习", max_length=500)
    coach_mode: CoachMode = CoachMode.STRICT
    reference_voice_role: str = Field(
        default="standard_tokyo", pattern="^(standard_tokyo|immersive_character)$"
    )
    lines: list[ProjectLessonLineRequest] = Field(min_length=1, max_length=100)


def _http_error(exc: JapaneseServiceError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


async def _bounded_body(request: Request, limit: int = 20 * 1024 * 1024) -> bytes:
    declared = request.headers.get("content-length")
    if declared:
        try:
            if int(declared) > limit:
                raise HTTPException(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    detail="单个录音不能超过 20 MB。",
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Content-Length 无效。") from exc
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > limit:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="单个录音不能超过 20 MB。",
            )
        content.extend(chunk)
    return bytes(content)


def create_router(service: JapaneseLearningService) -> APIRouter:
    router = APIRouter(prefix="/api/japanese", tags=["japanese-learning"])

    @router.get("/health")
    def health() -> dict[str, Any]:
        return service.health()

    @router.get("/curriculum")
    def curriculum() -> dict[str, Any]:
        return service.curriculum()

    @router.post("/learners", status_code=status.HTTP_201_CREATED)
    def create_learner(payload: LearnerCreateRequest) -> dict[str, Any]:
        try:
            return service.create_learner(
                display_name=payload.display_name,
                level=payload.level,
                goals=payload.goals,
                interests=payload.interests,
            ).to_dict()
        except JapaneseServiceError as exc:
            raise _http_error(exc) from exc

    @router.get("/learners/{learner_id}")
    def get_learner(learner_id: str) -> dict[str, Any]:
        try:
            return service.get_learner(learner_id).to_dict()
        except JapaneseServiceError as exc:
            raise _http_error(exc) from exc

    @router.patch("/learners/{learner_id}")
    def update_learner(learner_id: str, payload: LearnerUpdateRequest) -> dict[str, Any]:
        try:
            return service.update_learner(
                learner_id,
                display_name=payload.display_name,
                level=payload.level,
                goals=payload.goals,
                mastered_vocabulary=payload.mastered_vocabulary,
                mastered_grammar=payload.mastered_grammar,
                common_pronunciation_errors=payload.common_pronunciation_errors,
                interests=payload.interests,
            ).to_dict()
        except JapaneseServiceError as exc:
            raise _http_error(exc) from exc

    @router.post("/sessions", status_code=status.HTTP_201_CREATED)
    def create_session(payload: SessionCreateRequest) -> dict[str, Any]:
        try:
            return service.start_session(
                learner_id=payload.learner_id,
                mode=payload.mode,
                coach_mode=payload.coach_mode,
                scenario=payload.scenario,
                metadata=payload.metadata,
            ).to_dict()
        except JapaneseServiceError as exc:
            raise _http_error(exc) from exc

    @router.get("/sessions/{session_id}")
    def get_session(session_id: str) -> dict[str, Any]:
        try:
            return service.get_session(session_id).to_dict()
        except JapaneseServiceError as exc:
            raise _http_error(exc) from exc

    @router.post("/sessions/{session_id}/complete")
    def complete_session(session_id: str) -> dict[str, Any]:
        try:
            return service.complete_session(session_id).to_dict()
        except JapaneseServiceError as exc:
            raise _http_error(exc) from exc

    @router.get("/learners/{learner_id}/sessions")
    def list_sessions(learner_id: str) -> list[dict[str, Any]]:
        try:
            return [session.to_dict() for session in service.list_sessions(learner_id)]
        except JapaneseServiceError as exc:
            raise _http_error(exc) from exc

    @router.get("/sessions/{session_id}/turns")
    def list_turns(session_id: str) -> list[dict[str, Any]]:
        try:
            turns = service.list_turns(session_id)
            for turn in turns:
                turn.setdefault("demonstration", {})["audio_url"] = (
                    f"/api/japanese/turns/{turn['id']}/demonstration"
                )
            return turns
        except JapaneseServiceError as exc:
            raise _http_error(exc) from exc

    @router.get("/sessions/{session_id}/exercises")
    def list_session_exercises(session_id: str) -> list[dict[str, Any]]:
        try:
            exercises = service.list_session_exercises(session_id)
            return [
                {
                    **exercise.to_dict(),
                    "reference_audio_url": (
                        f"/api/japanese/exercises/{exercise.id}/reference"
                        if exercise.reference_audio_path else None
                    ),
                }
                for exercise in exercises
            ]
        except JapaneseServiceError as exc:
            raise _http_error(exc) from exc

    @router.post("/recordings", status_code=status.HTTP_201_CREATED)
    async def upload_recording(
        request: Request,
        session_id: str = Query(...),
        filename: str = Query(default="recording.wav", max_length=240),
    ) -> dict[str, Any]:
        content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
        if content_type not in {
            "audio/wav",
            "audio/x-wav",
            "application/octet-stream",
            "audio/webm",
            "video/webm",
            "audio/ogg",
            "audio/mp4",
            "audio/x-m4a",
        }:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="支持 WAV、WebM/Opus、Ogg 或 M4A 浏览器录音。",
            )
        try:
            recording = service.store_recording(
                session_id,
                filename,
                await _bounded_body(request),
                content_type=content_type,
            )
            result = recording.to_dict()
            result["recording_id"] = recording.id
            result["audio_path"] = recording.storage_path
            result["source_kind"] = SourceAudioKind.ORIGINAL_UNCOLORED.value
            return result
        except JapaneseServiceError as exc:
            raise _http_error(exc) from exc

    @router.post("/sessions/{session_id}/turns", status_code=status.HTTP_201_CREATED)
    def process_turn(session_id: str, payload: ConversationTurnRequest) -> dict[str, Any]:
        try:
            turn = service.process_turn(
                session_id=session_id,
                recording_id=payload.recording_id,
                transcript_hint=payload.transcript_hint,
                expected_text=payload.expected_text,
                voice_role=payload.voice_role,
            ).to_dict()
            turn["demonstration"]["audio_url"] = (
                f"/api/japanese/turns/{turn['id']}/demonstration"
            )
            return turn
        except JapaneseServiceError as exc:
            raise _http_error(exc) from exc

    @router.get("/turns/{turn_id}/demonstration", response_class=FileResponse)
    def turn_demonstration(turn_id: str) -> FileResponse:
        try:
            return FileResponse(service.turn_demonstration_path(turn_id), media_type="audio/wav")
        except JapaneseServiceError as exc:
            raise _http_error(exc) from exc

    @router.post("/sentence-repair")
    def sentence_repair(payload: SentenceRepairRequest) -> dict[str, Any]:
        try:
            return service.repair_sentence(
                learner_id=payload.learner_id,
                original=payload.original,
                scenario=payload.scenario,
                coach_mode=payload.coach_mode,
            )
        except (JapaneseServiceError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/sessions/{session_id}/shadowing", status_code=status.HTTP_201_CREATED)
    def shadowing(session_id: str, payload: ShadowAttemptRequest) -> dict[str, Any]:
        try:
            result = service.analyze_shadowing_attempt(
                session_id=session_id,
                reference_audio_path=payload.reference_audio_path,
                recording_id=payload.recording_id,
                expected_text=payload.expected_text,
                transcript_hint=payload.transcript_hint,
            )
            result["ab_playback"]["reference_audio_url"] = (
                f"/api/japanese/exercises/{result['exercise']['id']}/reference"
            )
            return result
        except JapaneseServiceError as exc:
            raise _http_error(exc) from exc

    @router.post("/sessions/{session_id}/shadowing/references", status_code=status.HTTP_201_CREATED)
    def create_shadowing_reference(
        session_id: str, payload: ShadowReferenceRequest
    ) -> dict[str, Any]:
        try:
            result = service.create_shadowing_reference(
                session_id, payload.expected_text, payload.voice_role
            )
            exercise_id = result["exercise"]["id"]
            result["synthesis"]["audio_url"] = (
                f"/api/japanese/exercises/{exercise_id}/reference"
            )
            return result
        except JapaneseServiceError as exc:
            raise _http_error(exc) from exc

    @router.post(
        "/sessions/{session_id}/shadowing/exercises/{exercise_id}/attempts",
        status_code=status.HTTP_201_CREATED,
    )
    def submit_shadowing_exercise(
        session_id: str, exercise_id: str, payload: ExistingShadowAttemptRequest
    ) -> dict[str, Any]:
        try:
            result = service.analyze_shadowing_exercise_attempt(
                session_id=session_id,
                exercise_id=exercise_id,
                recording_id=payload.recording_id,
                transcript_hint=payload.transcript_hint,
            )
            result["ab_playback"]["reference_audio_url"] = (
                f"/api/japanese/exercises/{exercise_id}/reference"
            )
            return result
        except JapaneseServiceError as exc:
            raise _http_error(exc) from exc

    @router.get("/exercises/{exercise_id}/reference", response_class=FileResponse)
    def exercise_reference(exercise_id: str) -> FileResponse:
        try:
            return FileResponse(service.exercise_reference_path(exercise_id), media_type="audio/wav")
        except JapaneseServiceError as exc:
            raise _http_error(exc) from exc

    @router.get("/learners/{learner_id}/reviews/due")
    def due_reviews(learner_id: str) -> list[dict[str, Any]]:
        try:
            return [item.to_dict() for item in service.due_reviews(learner_id)]
        except JapaneseServiceError as exc:
            raise _http_error(exc) from exc

    @router.get("/learners/{learner_id}/progress")
    def progress(learner_id: str) -> dict[str, Any]:
        try:
            return service.progress_snapshot(learner_id)
        except JapaneseServiceError as exc:
            raise _http_error(exc) from exc

    @router.get("/learners/{learner_id}/learning-path")
    def learning_path(learner_id: str) -> dict[str, Any]:
        try:
            return service.learning_path(learner_id)
        except JapaneseServiceError as exc:
            raise _http_error(exc) from exc

    @router.post("/learners/{learner_id}/pronunciation-plan", status_code=status.HTTP_201_CREATED)
    def pronunciation_plan(
        learner_id: str, payload: PronunciationPlanRequest
    ) -> dict[str, Any]:
        try:
            return service.create_pronunciation_plan(learner_id, payload.limit)
        except JapaneseServiceError as exc:
            raise _http_error(exc) from exc

    @router.post("/learners/{learner_id}/project-lessons", status_code=status.HTTP_201_CREATED)
    def project_lesson(learner_id: str, payload: ProjectLessonRequest) -> dict[str, Any]:
        try:
            return service.create_project_lesson(
                learner_id=learner_id,
                source_project_id=payload.source_project_id,
                lesson_mode=payload.lesson_mode,
                lines=[line.model_dump() for line in payload.lines],
                scenario=payload.scenario,
                coach_mode=payload.coach_mode,
                reference_voice_role=payload.reference_voice_role,
            )
        except JapaneseServiceError as exc:
            raise _http_error(exc) from exc

    @router.post("/reviews/{review_id}/grade")
    def grade_review(review_id: str, payload: ReviewGradeRequest) -> dict[str, Any]:
        try:
            return service.grade_review(review_id, payload.quality).to_dict()
        except JapaneseServiceError as exc:
            raise _http_error(exc) from exc

    @router.get("/learners/{learner_id}/anki-connect")
    def anki_connect_export(
        learner_id: str,
        deck_name: str = Query(default="Local AI Voice Studio::日本語", max_length=200),
    ) -> dict[str, Any]:
        try:
            return service.anki_connect_payload(learner_id, deck_name)
        except JapaneseServiceError as exc:
            raise _http_error(exc) from exc

    return router


def build_japanese_router(database_path: str | Path, asset_root: str | Path) -> APIRouter:
    """Factory used by the core FastAPI application during startup."""

    return create_router(build_default_service(database_path, asset_root))
