from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.modules.japanese.adapters import (  # noqa: E402
    AdapterError,
    FallbackASRAdapter,
    MockASRAdapter,
    MockTTSAdapter,
    build_adapters_from_environment,
)


class _FailingASR:
    def transcribe(self, audio_path: Path, transcript_hint: str | None = None):
        raise AdapterError("sensitive primary failure")


class JapaneseAdapterTests(unittest.TestCase):
    def test_primary_asr_failure_uses_marked_mock_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "recording.wav"
            MockTTSAdapter().synthesize("日本語", audio, "standard_tokyo")
            adapter = FallbackASRAdapter(_FailingASR(), MockASRAdapter())
            result = adapter.transcribe(audio, "日本語です")
            self.assertTrue(result.fallback_used)
            self.assertEqual(result.text, "日本語です")
            self.assertNotIn("sensitive", " ".join(result.evidence))

    def test_empty_environment_builds_all_mock_fallbacks_without_network(self) -> None:
        relevant = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("VOICE_STUDIO_JP_") and not key.startswith("VOICE_STUDIO_TEACHER_")
        }
        with patch.dict(os.environ, relevant, clear=True):
            bundle = build_adapters_from_environment()
            with tempfile.TemporaryDirectory() as directory:
                audio = Path(directory) / "recording.wav"
                MockTTSAdapter().synthesize("テスト", audio, "standard_tokyo")
                result = bundle.asr.transcribe(audio, "テスト")
                self.assertEqual(result.provider, "mock-asr/1")
                self.assertFalse(result.fallback_used)


if __name__ == "__main__":
    unittest.main()
