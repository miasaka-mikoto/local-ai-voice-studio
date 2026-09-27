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


if __name__ == "__main__":
    unittest.main()
