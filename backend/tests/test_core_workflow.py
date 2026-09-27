from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path

from app.config import Settings
from app.database import Database
from app.importers import parse_import
from app.errors import DomainError
from app.repository import Repository
from app.task_runner import TaskRunner


class CoreWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.settings = Settings.load(
            data_root=root / "data",
            database_path=root / "data" / "studio.sqlite3",
            worker_enabled=False,
        )
        self.settings.ensure_directories()
        self.database = Database(self.settings.database_path)
        self.database.initialize()
        self.repository = Repository(self.database, self.settings)
        self.runner = TaskRunner(self.repository, "test-worker")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_full_mock_project_restart_and_export(self) -> None:
        project = self.repository.create_project("Game smoke", "game", default_locale="ja-JP")
        source = """line_id,scene_id,character_id,text,emotion,locale,duration_limit,asset_name
L001,S01,C01,開始します,focused,ja-JP,900,voice_001
L002,S01,C02,了解しました,calm,ja-JP,1100,voice_002
"""
        parsed = parse_import("csv", source)
        imported = self.repository.import_lines(
            project["id"], "csv", "lines.csv", source, parsed.lines, parsed.warnings
        )
        self.assertEqual(2, imported["row_count"])
        self.assertEqual(2, len(self.repository.list_characters(project["id"])))

        task = self.repository.create_task(
            "generate_takes",
            {"engine_id": "mock", "take_count": 2, "seed": 100, "parameters": {}},
            project_id=project["id"],
        )
        completed = self.runner.run_once()
        self.assertEqual(task["id"], completed["id"])
        self.assertEqual("completed", completed["status"])
        lines = self.repository.list_lines(project["id"])
        takes = self.repository.list_takes(lines[0]["id"])
        self.assertEqual(2, len(takes))
        audio = self.repository.take_audio_path(takes[0]["id"])
        with wave.open(str(audio), "rb") as handle:
            self.assertEqual(48_000, handle.getframerate())
            self.assertEqual(3, handle.getsampwidth())
            self.assertEqual(1, handle.getnchannels())

        selected = self.repository.select_take(lines[0]["id"], takes[0]["id"], lines[0]["revision"])
        self.assertTrue(selected["selection_locked"])
        changed = self.repository.update_line(
            lines[0]["id"], {"text": "すぐ開始します"}, selected["revision"]
        )
        self.assertEqual(takes[0]["id"], changed["selected_take_id"])
        self.assertTrue(self.repository.get_take(takes[0]["id"])["is_stale"])

        export_task = self.repository.create_task(
            "export_project", {"format": "project_json"}, project_id=project["id"]
        )
        exported = self.runner.run_once()
        self.assertEqual(export_task["id"], exported["id"])
        self.assertEqual("completed", exported["status"])
        manifest = Path(exported["result"]["manifest_path"])
        self.assertTrue(manifest.is_file())

        reopened = Repository(Database(self.settings.database_path), self.settings)
        self.assertEqual(1, reopened.get_project(project["id"])["revision"] >= 1)
        self.assertEqual(takes[0]["id"], reopened.get_line(lines[0]["id"])["selected_take_id"])

    def test_task_controls_retry_and_crash_recovery(self) -> None:
        project = self.repository.create_project("Tasks", "video")
        paused = self.repository.create_task("unknown", {}, project_id=project["id"])
        self.assertEqual("paused", self.repository.request_pause(paused["id"])["status"])
        self.assertEqual("queued", self.repository.resume_task(paused["id"])["status"])
        failed = self.runner.run_once()
        self.assertEqual("failed", failed["status"])
        self.assertEqual("queued", self.repository.retry_task(failed["id"])["status"])

        running_task = self.repository.create_task("unknown", {}, project_id=project["id"])
        claimed = self.repository.claim_next_task("crashed-worker", lease_seconds=30)
        self.assertIsNotNone(claimed)
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE tasks SET lease_expires_at='2000-01-01T00:00:00.000Z' WHERE id=?",
                (claimed["id"],),
            )
        recovered = self.repository.recover_expired_tasks()
        self.assertIn(claimed["id"], recovered)
        self.assertEqual("queued", self.repository.get_task(claimed["id"])["status"])
        transitions = [event["to_status"] for event in self.repository.list_task_events(task_id=claimed["id"])]
        self.assertIn("stale", transitions)

        cancelled = self.repository.create_task("unknown", {}, project_id=project["id"])
        self.assertEqual("cancelled", self.repository.request_cancel(cancelled["id"])["status"])

    def test_revision_history_restore_and_mapping(self) -> None:
        project = self.repository.create_project("Mapping", "video")
        voice = self.repository.create_voice(
            "Tokyo standard", project_id=project["id"], authorization_status="verified"
        )
        character = self.repository.create_character(
            project["id"], "Aki", external_id="aki", default_voice_id=voice["id"],
            profile={"timbre": "clear"}, authorization_status="verified",
        )
        line = self.repository.create_line(
            project["id"], {"text": "最初", "source_text": "最初", "speaker": "Aki",
                            "character_id": character["id"], "voice_id": voice["id"], "ordinal": 1}
        )
        updated = self.repository.update_line(line["id"], {"text": "変更後"}, line["revision"])
        restored = self.repository.restore_line(line["id"], 1, updated["revision"])
        self.assertEqual("最初", restored["text"])
        self.assertEqual(3, restored["revision"])
        self.assertEqual(3, len(self.repository.line_history(line["id"])))

    def test_duplicate_import_rolls_back_database_and_staging_file(self) -> None:
        project = self.repository.create_project("Atomic import", "game")
        source = '[{"line_id":"same","text":"one"},{"line_id":"same","text":"two"}]'
        parsed = parse_import("json", source)
        with self.assertRaises(DomainError) as raised:
            self.repository.import_lines(
                project["id"], "json", "duplicate.json", source, parsed.lines, parsed.warnings
            )
        self.assertEqual("duplicate_external_id", raised.exception.code)
        self.assertEqual([], self.repository.list_lines(project["id"]))
        imports = self.settings.data_root / "projects" / project["id"] / "imports"
        self.assertEqual([], list(imports.iterdir()))

    def test_gpu_heavy_tasks_are_serialized_by_sqlite_lease(self) -> None:
        project = self.repository.create_project("GPU lease", "video")
        first = self.repository.create_task(
            "future_engine", {}, project_id=project["id"], resource_class="gpu_heavy"
        )
        second = self.repository.create_task(
            "future_engine", {}, project_id=project["id"], resource_class="gpu_heavy"
        )
        claimed = self.repository.claim_next_task("worker-a")
        self.assertEqual(first["id"], claimed["id"])
        self.assertEqual(first["id"], self.repository.gpu_lease()["task_id"])
        self.assertIsNone(self.repository.claim_next_task("worker-b"))
        self.repository.finish_task(first["id"], {"mock": True})
        claimed_second = self.repository.claim_next_task("worker-b")
        self.assertEqual(second["id"], claimed_second["id"])


if __name__ == "__main__":
    unittest.main()
