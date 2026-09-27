from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class LearningMode(StrEnum):
    CONVERSATION = "conversation"
    SHADOWING = "shadowing"
    PRONUNCIATION_CLINIC = "pronunciation_clinic"
    SENTENCE_REPAIR = "sentence_repair"
    PROJECT_LESSON = "project_lesson"
    SELF_VOICE_DEMO = "self_voice_demo"


class CoachMode(StrEnum):
    FLUENT = "fluent"
    STRICT = "strict"


class SessionStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ExerciseType(StrEnum):
    SHADOWING = "shadowing"
    PRONUNCIATION = "pronunciation"
    SENTENCE_REPAIR = "sentence_repair"
    DICTATION = "dictation"
    ROLE_PLAY = "role_play"


class ProjectLessonMode(StrEnum):
    DICTATION = "dictation"
    SHADOWING = "shadowing"
    ROLE_PLAY = "role_play"


class SourceAudioKind(StrEnum):
    ORIGINAL_UNCOLORED = "original_uncolored"
    VOICE_COLORED = "voice_colored"


class RecordingSourceType(StrEnum):
    BROWSER_ORIGINAL_UPLOAD = "browser_original_upload"
    IMPORTED_ORIGINAL = "imported_original"
    GENERATED_REFERENCE = "generated_reference"
    VOICE_COLORED = "voice_colored"


@dataclass(slots=True)
class LearnerProfile:
    display_name: str
    level: str = "beginner"
    goals: list[str] = field(default_factory=list)
    mastered_vocabulary: list[str] = field(default_factory=list)
    mastered_grammar: list[str] = field(default_factory=list)
    common_pronunciation_errors: list[str] = field(default_factory=list)
    interests: list[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: new_id("learner"))
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class LearningSession:
    learner_id: str
    mode: LearningMode
    coach_mode: CoachMode
    scenario: str
    id: str = field(default_factory=lambda: new_id("session"))
    status: SessionStatus = SessionStatus.ACTIVE
    metadata: dict[str, Any] = field(default_factory=dict)
    started_at: str = field(default_factory=utc_now)
    ended_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["mode"] = self.mode.value
        value["coach_mode"] = self.coach_mode.value
        value["status"] = self.status.value
        return value


@dataclass(slots=True)
class TranscriptResult:
    text: str
    confidence: float
    provider: str
    segments: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    fallback_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SentenceRepair:
    original: str
    minimal_correction: str
    natural_expression: str
    model_answer: str
    issues: list[str] = field(default_factory=list)
    confidence: float = 0.5
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TeacherResult:
    reply_text: str
    demonstration_text: str
    feedback: list[str]
    repair: SentenceRepair | None
    provider: str
    confidence: float
    fallback_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        return value


@dataclass(slots=True)
class SynthesisResult:
    audio_path: str
    provider: str
    voice_role: str
    sample_rate: int
    subtype: str
    fallback_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RecordingAsset:
    session_id: str
    storage_path: str
    sha256: str
    source_type: RecordingSourceType
    upload_entry: str
    original_filename: str
    content_type: str
    byte_size: int
    id: str = field(default_factory=lambda: new_id("recording"))
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["source_type"] = self.source_type.value
        return value


@dataclass(slots=True)
class MetricFeedback:
    metric: str
    value: float | None
    confidence: float
    summary: str
    evidence: dict[str, Any]
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ShadowingFeedback:
    content: MetricFeedback
    mora: MetricFeedback
    rhythm: MetricFeedback
    pitch: MetricFeedback
    priorities: list[str]
    scoring_source_path: str
    scoring_source_kind: SourceAudioKind
    reference_audio_path: str
    analyzed_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["scoring_source_kind"] = self.scoring_source_kind.value
        return value


@dataclass(slots=True)
class ConversationTurn:
    session_id: str
    recording_id: str
    sequence: int
    original_audio_path: str
    original_audio_sha256: str
    transcript: TranscriptResult
    teacher: TeacherResult
    demonstration: SynthesisResult
    exercise_id: str | None = None
    id: str = field(default_factory=lambda: new_id("turn"))
    scoring_source_kind: SourceAudioKind = SourceAudioKind.ORIGINAL_UNCOLORED
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["scoring_source_kind"] = self.scoring_source_kind.value
        return value


@dataclass(slots=True)
class Exercise:
    learner_id: str
    session_id: str | None
    exercise_type: ExerciseType
    prompt: str
    expected_text: str
    reference_audio_path: str | None = None
    id: str = field(default_factory=lambda: new_id("exercise"))
    status: str = "active"
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["exercise_type"] = self.exercise_type.value
        return value


@dataclass(slots=True)
class ReviewItem:
    learner_id: str
    error_key: str
    prompt: str
    answer: str
    exercise_id: str | None = None
    id: str = field(default_factory=lambda: new_id("review"))
    ease_factor: float = 2.5
    interval_days: int = 0
    repetitions: int = 0
    due_at: str = field(default_factory=utc_now)
    last_quality: int | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
