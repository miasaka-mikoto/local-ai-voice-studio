from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import Settings
from app.database import Database
from app.engines import EngineCatalog
from app.repository import Repository
from app.snapshot import SnapshotBuilder


class EngineRegistryIntegrationTests(unittest.TestCase):
    @staticmethod
    def _write_manifest(root: Path) -> None:
        (root / "deployment.json").write_text(
            json.dumps({
                "schema_version": "1.0",
                "engines": [
                    {"id": "seed_vc_v2", "role": "voice conversion", "license": "GPL-3.0"},
                    {"id": "indextts2", "role": "tts", "license": "CC BY-NC 4.0"},
                    {"id": "higgs", "role": "tts", "license": "noncommercial"},
                ],
            }),
            encoding="utf-8",
        )

    def test_standalone_manifest_and_mock_share_one_sanitized_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"VOICE_STUDIO_QWTTS_MANIFEST": ""}):
            root = Path(directory)
            self._write_manifest(root)
            catalog = EngineCatalog(root)
        rows = {item["id"]: item for item in catalog.list()}

        self.assertEqual(4, len(rows))
        self.assertEqual([], catalog.warnings)
        self.assertEqual("permissive", rows["mock"]["license_risk"])
        self.assertEqual("copyleft_review", rows["seed_vc_v2"]["license_risk"])
        self.assertEqual("noncommercial", rows["indextts2"]["license_risk"])
        self.assertEqual("noncommercial", rows["higgs"]["license_risk"])
        self.assertIn("voice_conversion", rows["seed_vc_v2"]["kinds"])
        self.assertFalse(rows["higgs"]["executable_in_mvp"])

    def test_missing_optional_manifests_keep_mock_available(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"VOICE_STUDIO_QWTTS_MANIFEST": ""}):
            catalog = EngineCatalog(Path(directory))
        self.assertEqual(["mock"], [item["id"] for item in catalog.list()])
        self.assertTrue(any("voice" in warning for warning in catalog.warnings))

    def test_frontend_snapshot_uses_registry_risk_and_percentage_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings.load(
                data_root=root / "data",
                database_path=root / "data" / "catalog.sqlite3",
                worker_enabled=False,
            )
            settings.ensure_directories()
            database = Database(settings.database_path)
            database.initialize()
            repository = Repository(database, settings)
            project = repository.create_project("Catalog", "game")

            self._write_manifest(root)
            with patch.dict(os.environ, {"VOICE_STUDIO_QWTTS_MANIFEST": ""}):
                snapshot = SnapshotBuilder(repository, root).build()
            engines = {item["id"]: item for item in snapshot["engines"]}

            self.assertEqual(0, snapshot["projects"][0]["progress"])
            self.assertEqual(project["id"], snapshot["projects"][0]["id"])
            self.assertEqual("restricted", engines["indextts2"]["licenseRisk"])
            self.assertEqual("restricted", engines["higgs"]["licenseRisk"])
            self.assertEqual("review", engines["seed_vc_v2"]["licenseRisk"])
            self.assertEqual("low", engines["mock"]["licenseRisk"])
            self.assertFalse(snapshot["system"]["ffmpegReady"])


if __name__ == "__main__":
    unittest.main()
