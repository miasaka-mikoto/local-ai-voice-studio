from __future__ import annotations

import math
import os
import random
import sys
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .util import stable_hash


@dataclass(slots=True)
class GeneratedAudio:
    path: Path
    duration_ms: int
    sample_rate_hz: int
    bit_depth: int
    channels: int
    qc: dict[str, Any]


class MockEngine:
    id = "mock"
    version = "1.0"
    sample_rate = 48_000
    bit_depth = 24
    channels = 1

    def input_hash(self, line: dict[str, Any], seed: int, parameters: dict[str, Any]) -> str:
        return stable_hash(
            {
                "line_content_hash": line["content_hash"],
                "engine": self.id,
                "engine_version": self.version,
                "seed": seed,
                "parameters": parameters,
            }
        )

    def generate(
        self, line: dict[str, Any], seed: int, parameters: dict[str, Any], destination: Path
    ) -> GeneratedAudio:
        rng = random.Random(seed)
        requested = line.get("duration_budget_ms") or line.get("duration_limit_ms")
        if requested:
            duration_ms = min(10_000, max(250, int(requested * (0.90 + rng.random() * 0.08))))
        else:
            units = max(1, len(str(line.get("text", ""))))
            duration_ms = min(10_000, max(450, int(units * 105 + rng.randint(0, 160))))
        frequency = 180.0 + (int(stable_hash(line.get("text", ""))[:4], 16) % 240) + rng.randint(-12, 12)
        amplitude = float(parameters.get("amplitude", 0.075))
        amplitude = min(0.2, max(0.01, amplitude))
        frames = int(self.sample_rate * duration_ms / 1000)
        max_value = (1 << 23) - 1
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_suffix(destination.suffix + ".part")
        square_sum = 0.0
        peak = 0.0
        with wave.open(str(partial), "wb") as output:
            output.setnchannels(self.channels)
            output.setsampwidth(3)
            output.setframerate(self.sample_rate)
            chunk = bytearray()
            for index in range(frames):
                fade = min(1.0, index / 480.0, (frames - index) / 480.0)
                modulation = 0.88 + 0.12 * math.sin(2 * math.pi * 3.1 * index / self.sample_rate)
                sample = amplitude * fade * modulation * math.sin(2 * math.pi * frequency * index / self.sample_rate)
                peak = max(peak, abs(sample))
                square_sum += sample * sample
                integer = int(max(-1.0, min(1.0, sample)) * max_value)
                chunk.extend(integer.to_bytes(3, byteorder="little", signed=True))
                if len(chunk) >= 48_000:
                    output.writeframesraw(chunk)
                    chunk.clear()
            if chunk:
                output.writeframesraw(chunk)
        os.replace(partial, destination)
        rms = math.sqrt(square_sum / max(1, frames))
        return GeneratedAudio(
            path=destination,
            duration_ms=duration_ms,
            sample_rate_hz=self.sample_rate,
            bit_depth=self.bit_depth,
            channels=self.channels,
            qc={
                "kind": "mock_signal",
                "peak": round(peak, 6),
                "rms": round(rms, 6),
                "clipped": peak >= 0.999,
                "note": "确定性 mock 音频，仅用于流程测试，不代表语音质量",
            },
        )


class EngineCatalog:
    def __init__(self, voice_root: Path) -> None:
        self.voice_root = voice_root.resolve()
        configured_qwtts = os.getenv("VOICE_STUDIO_QWTTS_MANIFEST")
        self.qwtts_manifest = (
            Path(configured_qwtts).resolve()
            if configured_qwtts
            else None
        )
        self.warnings: list[str] = []
        self._catalog = self._load_catalog()

    def _load_catalog(self) -> list[dict[str, Any]]:
        """Load sanitized capabilities without importing any model runtime."""

        studio_root = Path(__file__).resolve().parents[2]
        studio_path = str(studio_root)
        if studio_path not in sys.path:
            sys.path.insert(0, studio_path)

        try:
            from adapters import EngineRegistry, MockEngineAdapter
        except ImportError as exc:
            self.warnings.append(f"统一适配层不可用：{exc.__class__.__name__}")
            return [self._mock_fallback()]

        registry = EngineRegistry()
        manifests = [("voice", self.voice_root / "deployment.json")]
        if self.qwtts_manifest is not None:
            manifests.append(("qwtts", self.qwtts_manifest))
        for label, manifest in manifests:
            if not manifest.is_file():
                self.warnings.append(f"{label} 能力清单不存在")
                continue
            try:
                imported = registry.import_manifest(manifest)
            except (OSError, ValueError) as exc:
                self.warnings.append(f"{label} 能力清单被拒绝：{exc.__class__.__name__}")
                continue
            self.warnings.extend(f"{label}: {warning}" for warning in imported.warnings)
        registry.register(MockEngineAdapter())
        return registry.backend_catalog()

    @staticmethod
    def _mock_fallback() -> dict[str, Any]:
        return {
            "id": "mock",
            "name": "Deterministic Mock",
            "role": "tests_and_offline_ui",
            "kinds": ["tts"],
            "languages": [],
            "cloning": False,
            "emotion_control": True,
            "training": False,
            "sample_rate_hz": 48_000,
            "vram_mb": 0,
            "license": "Local project code",
            "license_risk": "permissive",
            "status": "ready",
            "available_on_disk": True,
            "heavy_gpu": False,
            "executable_in_mvp": True,
        }

    def list(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._catalog]
