from __future__ import annotations

import csv
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import threading
import unittest

import adapters.game_manifest as game_manifest_module
from adapters import (
    AdapterCancelled,
    ExporterRegistry,
    GameLine,
    export_game_manifest,
    export_lines,
    import_lines,
)
from adapters.naming import stable_asset_name


class NamingTests(unittest.TestCase):
    def test_stable_name_is_ascii_and_generation_sensitive(self) -> None:
        first = stable_asset_name(
            line_id="台词-一",
            character_id="角色甲",
            locale="ja-JP",
            emotion="克制",
            seed=42,
            take_index=1,
        )
        same = stable_asset_name(
            line_id="台词-一",
            character_id="角色甲",
            locale="ja-JP",
            emotion="克制",
            seed=42,
            take_index=1,
        )
        changed = stable_asset_name(
            line_id="台词-一",
            character_id="角色甲",
            locale="ja-JP",
            emotion="克制",
            seed=43,
            take_index=1,
        )
        self.assertEqual(first, same)
        self.assertNotEqual(first, changed)
        self.assertEqual(first, first.encode("ascii").decode("ascii"))
        self.assertNotIn("/", first)
        self.assertNotIn("\\", first)

    def test_close_float_and_content_changes_do_not_collide(self) -> None:
        base = dict(line_id="l", character_id="c", text="one", emotion_intensity=0.5000001)
        first = stable_asset_name(**base)
        second = stable_asset_name(**{**base, "emotion_intensity": 0.5000002})
        third = stable_asset_name(**{**base, "text": "two"})
        self.assertEqual(len({first, second, third}), 3)


class GameManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lines = [
            GameLine(
                line_id="s01_l01",
                character_id="lin",
                text="门外是谁？",
                scene_id="s01",
                emotion="fear",
                emotion_intensity=0.7,
                context="隔着门",
                listener="father",
                variation=2,
                locale="zh-CN",
                duration_limit=2.4,
                seed=18,
                take_index=1,
                metadata={"quest": "intro"},
            )
        ]

    def test_csv_json_jsonl_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for suffix in ("csv", "json", "jsonl"):
                target = root / f"lines.{suffix}"
                export_lines(self.lines, target)
                imported = import_lines(target)
                self.assertEqual(len(imported), 1)
                self.assertEqual(imported[0].line_id, "s01_l01")
                self.assertEqual(imported[0].character_id, "lin")
                self.assertEqual(imported[0].asset_name, self.lines[0].ensure_asset_name().asset_name)

    def test_qwtts_nested_project_mapping(self) -> None:
        payload = {
            "title": "demo",
            "language": "Chinese",
            "scenes": [
                {
                    "id": "scene-a",
                    "dialogues": [
                        {
                            "id": "line-a",
                            "character_id": "hero",
                            "text": "你好",
                            "stage_direction": "低声",
                            "subtext": "试探",
                            "listener_targets": ["guard", "player"],
                        }
                    ],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "project.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            lines = import_lines(path)
        self.assertEqual(lines[0].scene_id, "scene-a")
        self.assertEqual(lines[0].locale, "zh-CN")
        self.assertIn("低声", lines[0].context)
        self.assertEqual(lines[0].metadata["subtext"], "试探")
        self.assertEqual(lines[0].listener, "guard,player")

    def test_top_level_locale_scene_metadata_and_scalar_metadata_are_preserved(self) -> None:
        payload = {
            "language": "Japanese",
            "scenes": [
                {
                    "id": "s1",
                    "title": "入口",
                    "synopsis": "警戒",
                    "dialogues": [
                        {"id": "l1", "character_id": "c1", "text": "止まれ", "metadata": "[1,2]"}
                    ],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "project.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            line = import_lines(path)[0]
        self.assertEqual(line.locale, "ja-JP")
        self.assertEqual(line.metadata["scene_title"], "入口")
        self.assertEqual(line.to_dict()["metadata"]["source_metadata_value"], [1, 2])

    def test_null_required_fields_and_non_object_records_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text(
                json.dumps({"lines": [{"line_id": None, "character_id": "c", "text": "x"}]}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "line_id"):
                import_lines(path)
            path.write_text(
                json.dumps({"lines": [{"line_id": "l", "character_id": "c", "text": "x"}, 7]}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, r"lines\[1\]"):
                import_lines(path)

    def test_supplied_asset_name_cannot_escape_directory(self) -> None:
        with self.assertRaisesRegex(ValueError, "filename"):
            GameLine(line_id="a", character_id="b", text="c", asset_name="../escape.wav")
        with self.assertRaisesRegex(ValueError, "reserved"):
            GameLine(line_id="a", character_id="b", text="c", asset_name="CON.wav")

    def test_all_export_targets_create_nonempty_manifests(self) -> None:
        registry = ExporterRegistry()
        self.assertEqual(set(registry.targets), {"fmod", "generic", "godot", "unity", "unreal", "wwise"})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for target in registry.targets:
                extension = ".csv" if target in {"wwise", "fmod", "unreal"} else ".json"
                path = root / f"{target}{extension}"
                export_game_manifest(target, self.lines, path)
                self.assertTrue(path.is_file())
                self.assertGreater(path.stat().st_size, 20)
            with (root / "wwise.csv").open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["LineId"], "s01_l01")

    def test_export_audio_root_cannot_escape_game_asset_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "relative game asset path"):
                export_game_manifest("generic", self.lines, Path(directory) / "manifest.json", audio_root="../escape")

    def test_multiple_takes_remain_unique_in_every_target(self) -> None:
        lines = [self.lines[0], replace(self.lines[0], asset_name="", take_index=2)]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for target in ExporterRegistry().targets:
                extension = ".csv" if target in {"wwise", "fmod", "unreal"} else ".json"
                path = root / f"{target}{extension}"
                export_game_manifest(target, lines, path)
                if extension == ".csv":
                    with path.open("r", encoding="utf-8", newline="") as handle:
                        records = list(csv.DictReader(handle))
                    self.assertEqual(len(records), 2, target)
                    unique_key = "ObjectPath" if target == "wwise" else ("event_path" if target == "fmod" else "Name")
                    self.assertEqual(len({row[unique_key] for row in records}), 2, target)
                else:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    assets = payload["assets"]
                    self.assertEqual(len(assets), 2, target)

    def test_duplicate_user_asset_names_are_rejected_case_insensitively(self) -> None:
        lines = [
            replace(self.lines[0], asset_name="Voice.wav"),
            replace(self.lines[0], take_index=2, asset_name="voice.WAV"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "duplicate"):
                export_game_manifest("generic", lines, Path(directory) / "manifest.json")

    def test_concurrent_atomic_writes_leave_one_valid_complete_document(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "same.json"

            def write(index: int) -> None:
                export_lines(
                    [replace(self.lines[0], text=f"line {index}", asset_name="")],
                    destination,
                )

            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(write, range(24)))
            payload = json.loads(destination.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["lines"]), 1)
            self.assertEqual(list(Path(directory).glob(".*.tmp")), [])

    def test_atomic_write_lock_storage_is_fixed_and_bounded(self) -> None:
        shards = game_manifest_module._WRITE_LOCK_SHARDS
        shard_ids = {id(lock) for lock in shards}
        selected_ids = {
            id(game_manifest_module._target_lock(Path(f"unique-manifest-{index}.json")))
            for index in range(4_096)
        }

        self.assertEqual(len(shards), game_manifest_module._WRITE_LOCK_SHARD_COUNT)
        self.assertEqual(len(shard_ids), game_manifest_module._WRITE_LOCK_SHARD_COUNT)
        self.assertLessEqual(selected_ids, shard_ids)
        self.assertIs(
            game_manifest_module._target_lock(Path("same-manifest.json")),
            game_manifest_module._target_lock(Path("same-manifest.json")),
        )

    def test_pre_cancelled_export_does_not_commit(self) -> None:
        event = threading.Event()
        event.set()
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "cancelled.json"
            with self.assertRaises(AdapterCancelled):
                export_lines(self.lines, destination, event)
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
