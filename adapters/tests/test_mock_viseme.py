from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
import math
from pathlib import Path
import tempfile
import threading
import unittest
import wave

import adapters.mock_engine as mock_engine_module
from adapters import (
    AdapterCancelled,
    AdapterUnavailable,
    DisabledVisemePlugin,
    MockEngineAdapter,
    SynthesisRequest,
    VisemeCue,
    VisemeRegistry,
    VisemeResult,
)


class MockEngineTests(unittest.TestCase):
    def request(self) -> SynthesisRequest:
        return SynthesisRequest(
            line_id="line-1",
            character_id="hero",
            text="これは軽量テストです。",
            language="ja-JP",
            emotion="calm",
            emotion_intensity=0.4,
            duration_budget_seconds=0.4,
            engine_id="mock",
            seed=123,
            take_index=2,
            metadata={"locale": "ja-JP", "variation": 1},
        )

    def test_pcm24_output_is_deterministic(self) -> None:
        engine = MockEngineAdapter()
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            first = engine.synthesize(self.request(), first_dir)
            second = engine.synthesize(self.request(), second_dir)
            first_bytes = Path(first.audio_path).read_bytes()
            second_bytes = Path(second.audio_path).read_bytes()
            self.assertEqual(sha256(first_bytes).digest(), sha256(second_bytes).digest())
            with wave.open(first.audio_path, "rb") as handle:
                self.assertEqual(handle.getframerate(), 48_000)
                self.assertEqual(handle.getsampwidth(), 3)
                self.assertEqual(handle.getnchannels(), 1)
            self.assertEqual(first.sample_width_bits, 24)
            self.assertEqual(first.input_hash, self.request().input_hash)

    def test_same_target_concurrent_writes_are_deterministic_and_leave_no_temp_files(self) -> None:
        engine = MockEngineAdapter()
        request = self.request()
        with tempfile.TemporaryDirectory() as directory:
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(lambda _: engine.synthesize(request, directory), range(24)))
            paths = {result.audio_path for result in results}
            self.assertEqual(len(paths), 1)
            target = Path(results[0].audio_path)
            self.assertTrue(target.is_file())
            self.assertEqual(list(Path(directory).glob(f".{target.name}.*.tmp")), [])
            with wave.open(str(target), "rb") as handle:
                self.assertEqual(handle.getframerate(), 48_000)
                self.assertEqual(handle.getsampwidth(), 3)
                self.assertGreater(handle.getnframes(), 0)

    def test_target_lock_storage_is_fixed_and_bounded(self) -> None:
        shards = mock_engine_module._TARGET_LOCK_SHARDS
        shard_ids = {id(lock) for lock in shards}
        selected_ids = {
            id(mock_engine_module._target_lock(Path(f"unique-target-{index}.wav")))
            for index in range(4_096)
        }

        self.assertEqual(len(shards), mock_engine_module._TARGET_LOCK_SHARD_COUNT)
        self.assertEqual(len(shard_ids), mock_engine_module._TARGET_LOCK_SHARD_COUNT)
        self.assertLessEqual(selected_ids, shard_ids)
        self.assertIs(
            mock_engine_module._target_lock(Path("same-target.wav")),
            mock_engine_module._target_lock(Path("same-target.wav")),
        )

    def test_pre_cancelled_request_creates_no_file(self) -> None:
        event = threading.Event()
        event.set()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(AdapterCancelled):
                MockEngineAdapter().synthesize(self.request(), directory, event)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_reference_audio_requires_authorization_metadata(self) -> None:
        with self.assertRaisesRegex(ValueError, "reference audio"):
            SynthesisRequest(
                line_id="a",
                character_id="b",
                text="c",
                reference_audio="voice.wav",
            )
        with self.assertRaisesRegex(ValueError, "reference_audio_sha256"):
            SynthesisRequest(
                line_id="a",
                character_id="b",
                text="c",
                reference_audio="voice.wav",
                reference_authorization="owned",
            )

    def test_mock_duration_is_bounded_for_lightweight_execution(self) -> None:
        request = SynthesisRequest(
            line_id="a",
            character_id="b",
            text="c",
            engine_id="mock",
            duration_budget_seconds=10.1,
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "cannot exceed"):
                MockEngineAdapter().synthesize(request, directory)

    def test_non_finite_request_numbers_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "emotion_intensity"):
            SynthesisRequest(
                line_id="a",
                character_id="b",
                text="c",
                emotion_intensity=math.nan,
            )

    def test_input_hash_covers_speaker_generation_parameters_and_model_revision(self) -> None:
        base = dict(line_id="a", character_id="b", text="c", engine_id="mock")
        first = SynthesisRequest(**base, speaker="one", model_revision="r1", metadata={"variation": 1})
        speaker = SynthesisRequest(**base, speaker="two", model_revision="r1", metadata={"variation": 1})
        parameters = SynthesisRequest(**base, speaker="one", model_revision="r1", metadata={"variation": 2})
        model = SynthesisRequest(**base, speaker="one", model_revision="r2", metadata={"variation": 1})
        self.assertEqual(len({first.input_hash, speaker.input_hash, parameters.input_hash, model.input_hash}), 4)
        with self.assertRaises(TypeError):
            first.metadata["variation"] = 9  # type: ignore[index]
        reference_one = SynthesisRequest(
            **base,
            reference_audio="voice.wav",
            reference_audio_sha256="1" * 64,
            reference_authorization="owned",
        )
        reference_two = SynthesisRequest(
            **base,
            reference_audio="voice.wav",
            reference_audio_sha256="2" * 64,
            reference_authorization="owned",
        )
        self.assertNotEqual(reference_one.input_hash, reference_two.input_hash)


class VisemeTests(unittest.TestCase):
    def test_protocol_stays_disabled_until_explicit_plugin_registration(self) -> None:
        registry = VisemeRegistry()
        self.assertEqual(registry.available_plugins(), ())
        with self.assertRaises(AdapterUnavailable):
            registry.get("disabled").generate("audio.wav", "hello")
        self.assertIsInstance(registry.get("disabled"), DisabledVisemePlugin)

    def test_invalid_cue_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            VisemeCue(start_seconds=1.0, end_seconds=0.5, viseme="A")
        with self.assertRaises(ValueError):
            VisemeCue(start_seconds=math.nan, end_seconds=1.0, viseme="A")

    def test_viseme_result_has_versioned_atomic_json_contract(self) -> None:
        result = VisemeResult(
            plugin_id="test",
            plugin_version="1.2.3",
            viseme_set="rhubarb-basic",
            audio_path="voice.wav",
            audio_sha256="a" * 64,
            cues=(VisemeCue(0.0, 0.1, "A", 0.9), VisemeCue(0.1, 0.2, "B", 0.8)),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = result.write_json(Path(directory) / "visemes.json")
            payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["audio_sha256"], "a" * 64)
        self.assertEqual(len(payload["cues"]), 2)

    def test_overlapping_viseme_cues_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-overlapping"):
            VisemeResult(
                plugin_id="test",
                audio_path="voice.wav",
                cues=(VisemeCue(0.0, 0.2, "A"), VisemeCue(0.1, 0.3, "B")),
            )


if __name__ == "__main__":
    unittest.main()
