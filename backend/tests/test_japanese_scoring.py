from __future__ import annotations

import math
import struct
import sys
import tempfile
import unittest
import wave
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.modules.japanese.adapters import MockTTSAdapter  # noqa: E402
from app.modules.japanese.models import SourceAudioKind  # noqa: E402
from app.modules.japanese.scoring import (  # noqa: E402
    ScoringError,
    analyze_content,
    analyze_shadowing,
    approximate_mora_count,
    approximate_mora_segments,
    extract_wave_features,
)


def write_contour(path: Path, frequencies: list[float], segment_seconds: float = 0.25) -> None:
    sample_rate = 16_000
    frames = bytearray()
    phase = 0.0
    for frequency in frequencies:
        for _ in range(round(segment_seconds * sample_rate)):
            phase += 2.0 * math.pi * frequency / sample_rate
            frames.extend(struct.pack("<h", round(math.sin(phase) * 5_000)))
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(frames)


def write_silence(path: Path, seconds: float = 1.0) -> None:
    sample_rate = 16_000
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\x00\x00" * round(sample_rate * seconds))


class JapaneseScoringTests(unittest.TestCase):
    def test_content_exposes_edits_and_asr_confidence(self) -> None:
        result = analyze_content("日本語を勉強します。", "日本語勉強します", 0.8)
        self.assertLess(result.value or 1.0, 1.0)
        self.assertIn("を", result.evidence["missing_characters"])
        self.assertEqual(result.evidence["asr_confidence"], 0.8)
        self.assertTrue(result.limitations)

    def test_mora_count_handles_small_kana_as_part_of_previous_mora(self) -> None:
        self.assertEqual(approximate_mora_count("きょう"), 2)
        self.assertEqual(approximate_mora_count("がっこう"), 4)
        self.assertEqual(approximate_mora_segments("きょう"), ["きょ", "う"])
        self.assertEqual(approximate_mora_segments("がっこう"), ["が", "っ", "こ", "う"])

    def test_shadowing_returns_separate_evidence_without_overall_score(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "reference.wav"
            recording = root / "recording.wav"
            write_contour(reference, [190, 220, 260, 210])
            write_contour(recording, [195, 225, 255, 215])
            feedback = analyze_shadowing(
                reference,
                recording,
                expected_text="おはようございます",
                actual_transcript="おはようございます",
                asr_confidence=0.88,
            )
            payload = feedback.to_dict()
            self.assertNotIn("overall_score", payload)
            self.assertGreater(feedback.content.value or 0.0, 0.95)
            self.assertIsNone(feedback.mora.value)
            self.assertIn("expected_segments_approx", feedback.mora.evidence)
            self.assertTrue(feedback.mora.limitations)
            self.assertGreater(feedback.rhythm.value or 0.0, 0.75)
            self.assertIsNotNone(feedback.pitch.value)
            self.assertIn("normalized_shape_correlation", feedback.pitch.evidence)
            self.assertEqual(
                len(feedback.pitch.evidence["normalized_reference_f0_semitones"]), 32
            )
            self.assertEqual(
                len(feedback.pitch.evidence["normalized_recording_f0_semitones"]), 32
            )
            self.assertLessEqual(len(feedback.priorities), 2)
            self.assertEqual(feedback.scoring_source_kind, SourceAudioKind.ORIGINAL_UNCOLORED)

    def test_colored_audio_is_rejected_as_scoring_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "reference.wav"
            recording = root / "recording.wav"
            write_contour(reference, [220, 220])
            write_contour(recording, [220, 220])
            with self.assertRaisesRegex(ScoringError, "染色前"):
                analyze_shadowing(
                    reference,
                    recording,
                    "はい",
                    "はい",
                    0.8,
                    SourceAudioKind.VOICE_COLORED,
                )

    def test_silence_with_matching_transcript_hint_has_no_scores(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "reference.wav"
            recording = root / "silence.wav"
            write_contour(reference, [220, 240, 210, 230])
            write_silence(recording)
            feedback = analyze_shadowing(
                reference,
                recording,
                expected_text="おはようございます",
                actual_transcript="おはようございます",
                asr_confidence=0.99,
            )
            for metric in (
                feedback.content,
                feedback.mora,
                feedback.rhythm,
                feedback.pitch,
            ):
                self.assertIsNone(metric.value)
                self.assertEqual(metric.confidence, 0.0)
                self.assertTrue(
                    metric.evidence["transcript_text_ignored_without_voice_evidence"]
                )
            self.assertEqual(len(feedback.priorities), 1)
            self.assertIn("重录", feedback.priorities[0])

    def test_pcm24_mock_audio_is_readable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "demo.wav"
            MockTTSAdapter().synthesize("標準東京語", output, "standard_tokyo")
            features = extract_wave_features(output)
            self.assertEqual(features.sample_rate, 48_000)
            self.assertGreater(features.duration_seconds, 0.4)
            with wave.open(str(output), "rb") as wav:
                self.assertEqual(wav.getsampwidth(), 3)


if __name__ == "__main__":
    unittest.main()
