from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr

from adapters.cli import main


class CliTests(unittest.TestCase):
    def test_capability_snapshot_is_sanitized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            deployment = root / "deployment.json"
            deployment.write_text(json.dumps({
                "schema_version": "1.0",
                "hardware": {"policy": "one_engine_at_a_time"},
                "reference_audio_policy": "authorized_reference_only",
                "engines": [{
                    "id": "demo_tts", "role": "tts", "license": "MIT",
                    "api_key": "must-not-leak", "install": ["must-not-run"],
                }],
            }), encoding="utf-8")
            output = root / "capabilities.json"
            self.assertEqual(
                main(["capabilities", "--deployment", str(deployment), "--output", str(output)]),
                0,
            )
            value = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(len(value["engines"]), 1)
        self.assertTrue(value["manifests"][0]["policy"]["one_engine_at_a_time"])
        self.assertEqual(
            value["manifests"][0]["policy"]["reference_audio_policy"],
            "authorized_reference_only",
        )
        self.assertNotIn("api_key", json.dumps(value))
        self.assertNotIn('"install"', json.dumps(value))

    def test_normalize_and_export_game_commands(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.json"
            normalized = root / "normalized.jsonl"
            manifest = root / "unity.json"
            source.write_text(
                json.dumps([{"id": "l1", "character_id": "c1", "text": "hello"}]),
                encoding="utf-8",
            )
            with redirect_stdout(io.StringIO()):
                normalize_result = main(["normalize-game", str(source), str(normalized)])
                export_result = main(["export-game", "unity", str(normalized), str(manifest)])
            self.assertEqual(normalize_result, 0)
            self.assertEqual(export_result, 0)
            self.assertTrue(normalized.is_file())
            self.assertTrue(manifest.is_file())

    def test_mock_command_writes_audio(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with redirect_stdout(io.StringIO()):
                result = main(
                    [
                        "mock",
                        "--line-id",
                        "l1",
                        "--character-id",
                        "c1",
                        "--text",
                        "test",
                        "--output-dir",
                        directory,
                        "--duration",
                        "0.2",
                    ]
                )
            self.assertEqual(result, 0)
            self.assertEqual(len(list(Path(directory).glob("*.wav"))), 1)

    def test_cli_never_overwrites_its_input_and_requires_force_for_other_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.json"
            source.write_text(
                json.dumps([{"id": "l1", "character_id": "c1", "text": "hello"}]),
                encoding="utf-8",
            )
            original = source.read_bytes()
            with redirect_stderr(io.StringIO()):
                self.assertEqual(main(["normalize-game", str(source), str(source), "--force"]), 2)
            self.assertEqual(source.read_bytes(), original)

            hardlink = root / "source-hardlink.json"
            os.link(source, hardlink)
            with redirect_stderr(io.StringIO()):
                self.assertEqual(main(["normalize-game", str(source), str(hardlink), "--force"]), 2)
            self.assertEqual(source.read_bytes(), original)
            hardlink.unlink()

            output = root / "output.json"
            output.write_text("keep", encoding="utf-8")
            with redirect_stderr(io.StringIO()):
                self.assertEqual(main(["normalize-game", str(source), str(output)]), 2)
            self.assertEqual(output.read_text(encoding="utf-8"), "keep")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(
                    main(["normalize-game", str(source), str(output), "--force"]),
                    0,
                )
            self.assertIn('"schema_version"', output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
