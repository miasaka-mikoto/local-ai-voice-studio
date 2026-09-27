from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.modules.japanese.adapters import MockTTSAdapter  # noqa: E402
from app.modules.japanese.media import (  # noqa: E402
    AudioNormalizationError,
    normalize_browser_audio,
    resolve_ffmpeg,
    validate_reference_audio,
)


class JapaneseMediaTests(unittest.TestCase):
    def test_existing_pcm24_master_is_kept_as_target_format(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.wav"
            output = root / "normalized.wav"
            MockTTSAdapter().synthesize("ブラウザー録音", source, "standard_tokyo")
            normalize_browser_audio(source.read_bytes(), "application/octet-stream", output)
            with wave.open(str(output), "rb") as wav:
                self.assertEqual(
                    (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()),
                    (48_000, 1, 3),
                )

    def test_browser_webm_opus_is_normalized_with_bundled_ffmpeg(self) -> None:
        ffmpeg = resolve_ffmpeg()
        if ffmpeg is None:
            self.skipTest("本机没有可用 FFmpeg")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.wav"
            webm = root / "microphone.webm"
            output = root / "normalized.wav"
            MockTTSAdapter().synthesize("新宿までお願いします", source, "standard_tokyo")
            completed = subprocess.run(
                [
                    str(ffmpeg),
                    "-nostdin",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(source),
                    "-c:a",
                    "libopus",
                    str(webm),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=30,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self.assertEqual(completed.returncode, 0)
            normalize_browser_audio(webm.read_bytes(), "audio/webm;codecs=opus", output)
            with wave.open(str(output), "rb") as wav:
                self.assertEqual(
                    (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()),
                    (48_000, 1, 3),
                )
                self.assertGreater(wav.getnframes(), 0)

    def test_unsupported_upload_type_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(AudioNormalizationError, "不支持"):
                normalize_browser_audio(b"not audio", "text/plain", Path(directory) / "x.wav")

    def test_truncated_pcm24_payload_is_rejected_before_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "declared-frames.wav"
            output = root / "normalized.wav"
            MockTTSAdapter().synthesize("截断测试", source, "standard_tokyo")
            header_only = source.read_bytes()[:44]
            with self.assertRaisesRegex(AudioNormalizationError, "截断"):
                normalize_browser_audio(header_only, "audio/wav", output)
            self.assertFalse(output.exists())

    def test_reference_audio_accepts_complete_pcm16_and_pcm24(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            for sample_width in (2, 3):
                with self.subTest(sample_width=sample_width):
                    source = Path(directory) / f"pcm{sample_width * 8}.wav"
                    with wave.open(str(source), "wb") as wav:
                        wav.setnchannels(1)
                        wav.setsampwidth(sample_width)
                        wav.setframerate(48_000)
                        wav.writeframes(b"\x01" * (sample_width * 480))
                    self.assertEqual(
                        validate_reference_audio(source), (1, sample_width, 48_000, 480)
                    )

    def test_reference_audio_rejects_non_wav_and_declared_but_missing_frames(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            invalid = root / "not-a-wave.wav"
            invalid.write_bytes(b"not a PCM WAV")
            with self.assertRaisesRegex(AudioNormalizationError, "PCM WAV"):
                validate_reference_audio(invalid)

            complete = root / "complete.wav"
            with wave.open(str(complete), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(3)
                wav.setframerate(48_000)
                wav.writeframes(b"\x01\x00\x00" * 480)
            truncated = root / "truncated.wav"
            truncated.write_bytes(complete.read_bytes()[:44])
            with self.assertRaisesRegex(AudioNormalizationError, "截断"):
                validate_reference_audio(truncated)


if __name__ == "__main__":
    unittest.main()
