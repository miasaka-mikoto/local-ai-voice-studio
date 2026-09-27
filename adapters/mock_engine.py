"""Deterministic PCM-24 mock synthesis for UI, task, and export tests."""

from __future__ import annotations

from hashlib import sha256
import math
import os
from pathlib import Path
import tempfile
import threading
import wave

from .base import AdapterCancelled, EngineAdapter
from .models import (
    EngineCapability,
    EngineHealth,
    EngineKind,
    LicenseRisk,
    RuntimeWeight,
    SynthesisRequest,
    SynthesisResult,
)
from .naming import stable_asset_name


_TARGET_LOCK_SHARD_COUNT = 64
_TARGET_LOCK_SHARDS = tuple(threading.Lock() for _ in range(_TARGET_LOCK_SHARD_COUNT))


def _target_lock(path: Path) -> threading.Lock:
    key = os.path.normcase(os.path.abspath(path))
    return _TARGET_LOCK_SHARDS[hash(key) % _TARGET_LOCK_SHARD_COUNT]


def _pcm24(value: int) -> bytes:
    unsigned = value & 0xFFFFFF
    return bytes((unsigned & 0xFF, (unsigned >> 8) & 0xFF, (unsigned >> 16) & 0xFF))


class MockEngineAdapter(EngineAdapter):
    """Writes a quiet deterministic tone without importing an AI framework."""

    _CAPABILITY = EngineCapability(
        engine_id="mock",
        display_name="Deterministic Mock Engine",
        kinds=(EngineKind.TTS,),
        languages=(),
        supports_voice_cloning=False,
        supports_emotion_control=True,
        supports_training=False,
        output_sample_rates=(48_000,),
        minimum_vram_mb=0,
        minimum_system_ram_gb=0.05,
        runtime_weight=RuntimeWeight.LIGHT,
        license_name="Local project code",
        license_risk=LicenseRisk.PERMISSIVE,
        status="ready",
        available_on_disk=True,
        metadata={"purpose": "tests_and_offline_ui"},
    )

    @property
    def capability(self) -> EngineCapability:
        return self._CAPABILITY

    def health(self) -> EngineHealth:
        return EngineHealth(engine_id="mock", available=True, loaded=False, detail="ready")

    def synthesize(
        self,
        request: SynthesisRequest,
        output_dir: str | Path,
        cancel_event: threading.Event | None = None,
    ) -> SynthesisResult:
        if request.engine_id != "mock":
            raise ValueError(f"mock adapter cannot execute engine {request.engine_id!r}")
        if request.output_sample_rate not in self.capability.output_sample_rates:
            raise ValueError("mock engine currently supports only 48000 Hz output")
        if cancel_event is not None and cancel_event.is_set():
            raise AdapterCancelled("mock synthesis cancelled before start")

        duration = request.duration_budget_seconds
        if duration is None:
            duration = min(8.0, max(0.35, 0.24 + len(request.text.strip()) * 0.075))
        if duration > 10.0:
            raise ValueError("mock duration budget cannot exceed 10 seconds")
        sample_rate = request.output_sample_rate
        frame_count = max(1, int(round(duration * sample_rate)))
        digest = sha256(f"{request.input_hash}:{request.seed}".encode("utf-8")).digest()
        frequency = 170.0 + int.from_bytes(digest[:2], "big") % 260
        amplitude = 0.07 + (digest[2] / 255.0) * 0.025
        fade_frames = min(frame_count // 4, max(1, int(sample_rate * 0.012)))

        variation = int(request.metadata.get("variation", 0))
        locale = str(request.metadata.get("locale", request.language))
        name = stable_asset_name(
            line_id=request.line_id,
            character_id=request.character_id,
            locale=locale,
            emotion=request.emotion,
            emotion_intensity=request.emotion_intensity,
            variation=variation,
            seed=request.seed,
            take_index=request.take_index,
            text=request.text,
            engine_id=request.engine_id,
            voice_profile=request.voice_profile,
            model_revision=request.model_revision,
            input_hash=request.input_hash,
        )
        output_root = Path(output_dir)
        output_root.mkdir(parents=True, exist_ok=True)
        target = output_root / name
        frames = bytearray(frame_count * 3)
        maximum = (1 << 23) - 1
        for index in range(frame_count):
            if cancel_event is not None and index % 2048 == 0 and cancel_event.is_set():
                raise AdapterCancelled("mock synthesis cancelled")
            envelope = min(1.0, index / fade_frames, (frame_count - index - 1) / fade_frames)
            sample = int(maximum * amplitude * max(0.0, envelope) * math.sin(2 * math.pi * frequency * index / sample_rate))
            offset = index * 3
            frames[offset : offset + 3] = _pcm24(sample)

        with _target_lock(target):
            if cancel_event is not None and cancel_event.is_set():
                raise AdapterCancelled("mock synthesis cancelled before write")
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
            )
            os.close(descriptor)
            temporary = Path(temporary_name)
            try:
                with wave.open(str(temporary), "wb") as handle:
                    handle.setnchannels(1)
                    handle.setsampwidth(3)
                    handle.setframerate(sample_rate)
                    handle.writeframes(frames)
                if cancel_event is not None and cancel_event.is_set():
                    raise AdapterCancelled("mock synthesis cancelled before commit")
                os.replace(temporary, target)
            finally:
                if temporary.exists():
                    temporary.unlink()

        return SynthesisResult(
            engine_id="mock",
            line_id=request.line_id,
            take_index=request.take_index,
            audio_path=str(target),
            sample_rate=sample_rate,
            sample_width_bits=24,
            duration_seconds=frame_count / sample_rate,
            input_hash=request.input_hash,
            seed=request.seed,
            metadata={
                "mock": True,
                "frequency_hz": frequency,
                "asset_name": name,
                "pcm": "signed little-endian PCM-24 mono",
            },
        )

    def unload(self) -> None:
        return None
