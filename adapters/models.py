"""Shared, serialization-friendly adapter data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
import json
import math
import re
from types import MappingProxyType
from typing import Any, Mapping


_ENGINE_ID = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,127}$")
_AUTHORIZED_REFERENCE = {"not_applicable", "owned", "authorized", "licensed"}


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("metadata keys must be strings")
            frozen[key] = _freeze_json(item)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("metadata numbers must be finite")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError(f"metadata value is not JSON-compatible: {type(value).__name__}")


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


class EngineKind(StrEnum):
    TTS = "tts"
    VOICE_CONVERSION = "voice_conversion"
    DIRECTOR = "director"
    ASR = "asr"
    QUALITY = "quality"
    TRAINING = "training"
    LIP_SYNC = "lip_sync"


class LicenseRisk(StrEnum):
    PERMISSIVE = "permissive"
    COPYLEFT_REVIEW = "copyleft_review"
    NONCOMMERCIAL = "noncommercial"
    CUSTOM_REVIEW = "custom_review"
    UNKNOWN = "unknown"


class RuntimeWeight(StrEnum):
    LIGHT = "light"
    MEDIUM = "medium"
    HEAVY = "heavy"


@dataclass(frozen=True, slots=True)
class EngineCapability:
    """Static engine facts; never implies that the engine is currently loaded."""

    engine_id: str
    display_name: str
    kinds: tuple[EngineKind, ...]
    languages: tuple[str, ...] = ()
    supports_voice_cloning: bool = False
    supports_emotion_control: bool = False
    supports_training: bool = False
    output_sample_rates: tuple[int, ...] = ()
    minimum_vram_mb: int | None = None
    minimum_system_ram_gb: float | None = None
    runtime_weight: RuntimeWeight = RuntimeWeight.HEAVY
    license_name: str = "unknown"
    license_risk: LicenseRisk = LicenseRisk.UNKNOWN
    source_url: str | None = None
    model_id: str | None = None
    model_revision: str | None = None
    local_paths: tuple[str, ...] = ()
    local_path_roles: Mapping[str, str] = field(default_factory=dict)
    endpoint: str | None = None
    status: str = "unknown"
    available_on_disk: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not _ENGINE_ID.fullmatch(self.engine_id):
            raise ValueError(f"invalid engine_id: {self.engine_id!r}")
        if not self.display_name.strip():
            raise ValueError("display_name must not be empty")
        if not self.kinds:
            raise ValueError("at least one engine kind is required")
        if any(rate <= 0 for rate in self.output_sample_rates):
            raise ValueError("sample rates must be positive")
        if self.minimum_vram_mb is not None and self.minimum_vram_mb < 0:
            raise ValueError("minimum_vram_mb must be non-negative")
        object.__setattr__(self, "metadata", _freeze_json(self.metadata))
        object.__setattr__(self, "local_path_roles", _freeze_json(self.local_path_roles))

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine_id": self.engine_id,
            "display_name": self.display_name,
            "kinds": [str(value) for value in self.kinds],
            "languages": list(self.languages),
            "supports_voice_cloning": self.supports_voice_cloning,
            "supports_emotion_control": self.supports_emotion_control,
            "supports_training": self.supports_training,
            "output_sample_rates": list(self.output_sample_rates),
            "minimum_vram_mb": self.minimum_vram_mb,
            "minimum_system_ram_gb": self.minimum_system_ram_gb,
            "runtime_weight": str(self.runtime_weight),
            "license_name": self.license_name,
            "license_risk": str(self.license_risk),
            "source_url": self.source_url,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "local_paths": list(self.local_paths),
            "local_path_roles": dict(self.local_path_roles),
            "endpoint": self.endpoint,
            "status": self.status,
            "available_on_disk": self.available_on_disk,
            "metadata": _thaw_json(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class EngineHealth:
    engine_id: str
    available: bool
    loaded: bool = False
    detail: str = ""


@dataclass(frozen=True, slots=True)
class SynthesisRequest:
    line_id: str
    text: str
    character_id: str
    language: str = "und"
    speaker: str = ""
    listener: str = ""
    scene: str = ""
    intent: str = ""
    subtext: str = ""
    emotion: str = "neutral"
    emotion_intensity: float = 0.5
    pace: str = "medium"
    pitch: str = "medium"
    volume: str = "medium"
    breath: str = ""
    pause: str = ""
    pronunciation: Mapping[str, str] = field(default_factory=dict)
    duration_budget_seconds: float | None = None
    voice_profile: str = ""
    engine_id: str = "mock"
    engine_version: str = ""
    model_revision: str = ""
    seed: int = 0
    take_index: int = 0
    output_sample_rate: int = 48_000
    reference_audio: str | None = None
    reference_audio_sha256: str | None = None
    reference_authorization: str = "not_applicable"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.line_id, str) or not isinstance(self.character_id, str):
            raise ValueError("line_id and character_id must be strings")
        if not self.line_id.strip() or not self.character_id.strip():
            raise ValueError("line_id and character_id are required")
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("text must not be empty")
        if not math.isfinite(self.emotion_intensity) or not 0.0 <= self.emotion_intensity <= 1.0:
            raise ValueError("emotion_intensity must be between 0 and 1")
        if self.duration_budget_seconds is not None and (
            not math.isfinite(self.duration_budget_seconds) or self.duration_budget_seconds <= 0
        ):
            raise ValueError("duration_budget_seconds must be positive")
        if self.take_index < 0 or self.output_sample_rate <= 0:
            raise ValueError("take_index and output_sample_rate are invalid")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("seed must be an integer")
        if self.reference_authorization not in _AUTHORIZED_REFERENCE:
            raise ValueError("invalid reference_authorization")
        if self.reference_audio and self.reference_authorization == "not_applicable":
            raise ValueError("reference audio requires owned/authorized/licensed metadata")
        if self.reference_audio and not self.reference_audio_sha256:
            raise ValueError("reference audio requires reference_audio_sha256 for provenance")
        if self.reference_audio_sha256 and not re.fullmatch(r"[0-9a-fA-F]{64}", self.reference_audio_sha256):
            raise ValueError("reference_audio_sha256 must be a 64-character hexadecimal digest")
        if not _ENGINE_ID.fullmatch(self.engine_id):
            raise ValueError("invalid engine_id")
        if any(not isinstance(key, str) or not isinstance(value, str) for key, value in self.pronunciation.items()):
            raise ValueError("pronunciation must map strings to strings")
        object.__setattr__(self, "pronunciation", MappingProxyType(dict(self.pronunciation)))
        object.__setattr__(self, "metadata", _freeze_json(self.metadata))

    @property
    def input_hash(self) -> str:
        payload = {
            "line_id": self.line_id,
            "text": self.text,
            "character_id": self.character_id,
            "language": self.language,
            "speaker": self.speaker,
            "listener": self.listener,
            "scene": self.scene,
            "intent": self.intent,
            "subtext": self.subtext,
            "emotion": self.emotion,
            "emotion_intensity": self.emotion_intensity,
            "pace": self.pace,
            "pitch": self.pitch,
            "volume": self.volume,
            "breath": self.breath,
            "pause": self.pause,
            "pronunciation": dict(sorted(self.pronunciation.items())),
            "duration_budget_seconds": self.duration_budget_seconds,
            "voice_profile": self.voice_profile,
            "engine_id": self.engine_id,
            "engine_version": self.engine_version,
            "model_revision": self.model_revision,
            "seed": self.seed,
            "take_index": self.take_index,
            "output_sample_rate": self.output_sample_rate,
            "reference_audio": self.reference_audio,
            "reference_audio_sha256": self.reference_audio_sha256,
            "reference_authorization": self.reference_authorization,
            "generation_parameters": _thaw_json(self.metadata),
        }
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class SynthesisResult:
    engine_id: str
    line_id: str
    take_index: int
    audio_path: str
    sample_rate: int
    sample_width_bits: int
    duration_seconds: float
    input_hash: str
    seed: int
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", _freeze_json(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine_id": self.engine_id,
            "line_id": self.line_id,
            "take_index": self.take_index,
            "audio_path": self.audio_path,
            "sample_rate": self.sample_rate,
            "sample_width_bits": self.sample_width_bits,
            "duration_seconds": self.duration_seconds,
            "input_hash": self.input_hash,
            "seed": self.seed,
            "metadata": _thaw_json(self.metadata),
        }
