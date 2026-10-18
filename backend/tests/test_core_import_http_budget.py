"""Real ASGI/SQLite import-budget regression; no listener, worker or model runtime."""
from __future__ import annotations

import asyncio
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


class ImportHttpBudgetTests(unittest.TestCase):
    def run_case(self, case: str) -> None:
        # Fresh interpreters prevent app.main's module-level create_app() from
        # touching default data, and make collection order irrelevant.
        with tempfile.TemporaryDirectory(prefix="import-http-") as directory:
            env = {
                key: value for key, value in os.environ.items()
                if key.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "LANG", "LC_ALL"}
            }
            env.update(TMPDIR=directory, TMP=directory, TEMP=directory, HOME=directory,
                       USERPROFILE=directory, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
            result = subprocess.run(
                [sys.executable, "-B", str(Path(__file__).resolve()), "--case", case],
                cwd=directory, env=env, capture_output=True, text=True,
                encoding="utf-8", timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_lines_and_jsonl_utf8_boundaries_persist(self) -> None:
        self.run_case("boundaries")

    def test_rejection_preserves_existing_database_and_files(self) -> None:
        self.run_case("existing")

    def test_lines_charge_stored_json_not_compact_http_body(self) -> None:
        self.run_case("serialization")


def run_isolated(case: str) -> None:
    backend = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(backend), str(backend / "tests")]
    from app.config import Settings
    from app.engines import EngineCatalog
    from app.modules.japanese.adapters import (
        AdapterBundle, MockASRAdapter, MockTeacherAdapter, MockTTSAdapter,
    )
    from test_japanese_http_flow import asgi_request

    check = unittest.TestCase()

    def request(app, path, payload):
        status, headers, body = runner.run(asgi_request(
            app, "POST", path,
            body=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            content_type="application/json",
        ))
        check.assertIn("application/json", headers["content-type"])
        return status, json.loads(body)

    def persisted(settings):
        # A separate real connection verifies committed state, including revisions,
        # timestamps, scenes/characters and every other table, not just row counts.
        with closing(sqlite3.connect(settings.database_path)) as connection:
            database = tuple(connection.iterdump())
        projects = settings.data_root / "projects"
        files = {str(p.relative_to(projects)): p.read_bytes()
                 for p in projects.rglob("*") if p.is_file()}
        directories = sorted(str(p.relative_to(projects))
                             for p in projects.rglob("*") if p.is_dir())
        return database, files, directories

    with tempfile.TemporaryDirectory(prefix="isolated-app-") as directory, asyncio.Runner() as runner:
        # Windows ProactorEventLoop creates an internal socketpair on startup.
        # Initialize it before blocking connects; all app requests reuse this loop
        # under the strict guard, and Runner closes after the patches exit.
        runner.get_loop()
        root = Path(directory)
        bootstrap = Settings(root / "backend", root / "data", root / "db.sqlite3",
                             worker_enabled=False, max_import_bytes=256)
        adapters = AdapterBundle(MockASRAdapter(), MockTeacherAdapter(), MockTTSAdapter())
        with (
            patch.object(Settings, "load", return_value=bootstrap),
            patch.object(EngineCatalog, "_load_catalog",
                         lambda self: [self._mock_fallback()]),
            patch("app.snapshot._gpu", return_value=("test GPU", 0, 0)),
            patch("app.snapshot._memory", return_value=(0.0, 0.0)),
            patch("app.snapshot.platform.platform", return_value="isolated-test"),
            patch("app.modules.japanese.service.build_adapters_from_environment", return_value=adapters),
            patch("socket.socket.connect", side_effect=AssertionError("network forbidden")),
            patch("subprocess.Popen", side_effect=AssertionError("process launch forbidden")),
        ):
            # This first import also creates the module-level app in temporary data.
            from app.main import create_app

            def new_app(budget):
                index = len(list(root.glob("case-*")))
                folder = root / f"case-{index}"
                settings = Settings(folder / "backend", folder / "data", folder / "db.sqlite3",
                                    worker_enabled=False, max_import_bytes=budget)
                app = create_app(settings)
                status, response = request(app, "/api/v1/projects", {"name": "预算测试", "kind": "game"})
                check.assertEqual(status, 201)
                return app, settings, response["projects"][0]["id"]

            def reject(app, settings, project, payload):
                before = persisted(settings)
                status, response = request(app, f"/api/v1/projects/{project}/imports", payload)
                check.assertEqual(status, 400, response)
                check.assertEqual(response, {
                    "code": "import_too_large", "message": "台词导入内容超过大小上限",
                    "details": {}, "recoverable": False,
                })
                check.assertEqual(persisted(settings), before)

            def accept(app, settings, project, payload, content, source_format, filename):
                with closing(sqlite3.connect(settings.database_path)) as connection:
                    revision = connection.execute("SELECT revision FROM projects WHERE id=?", (project,)).fetchone()[0]
                status, response = request(app, f"/api/v1/projects/{project}/imports", payload)
                check.assertEqual(status, 200, response)
                check.assertEqual([line["text"] for line in response["lines"]], ["こんにちは🌸"])
                check.assertEqual(response["projects"][0]["lineCount"], 1)
                with closing(sqlite3.connect(settings.database_path)) as connection:
                    check.assertEqual(connection.execute("SELECT text FROM lines").fetchall(), [("こんにちは🌸",)])
                    check.assertEqual(connection.execute("SELECT count(*) FROM line_revisions").fetchone(), (1,))
                    check.assertEqual(connection.execute("SELECT source_format,filename,row_count FROM import_runs").fetchall(),
                                      [(source_format, filename, 1)])
                    check.assertEqual(connection.execute("SELECT revision FROM projects WHERE id=?", (project,)).fetchone(), (revision + 1,))
                files = list((settings.data_root / "projects" / project / "imports").iterdir())
                check.assertEqual(len(files), 1)
                check.assertTrue(files[0].name.endswith("_" + filename))
                check.assertEqual(files[0].read_bytes(), content.encode("utf-8"))

            lines = [{"text": "こんにちは🌸"}]
            serialized = json.dumps(lines, ensure_ascii=False)
            jsonl = json.dumps(lines[0], ensure_ascii=False) + "\n"
            if case == "boundaries":
                for source_format, payload, content, filename in (
                    ("json", {"lines": lines}, serialized, "frontend-lines.json"),
                    ("jsonl", {"format": "jsonl", "content": jsonl}, jsonl, "import.jsonl"),
                ):
                    size = len(content.encode("utf-8"))
                    check.assertGreater(size, len(content))
                    for offset in (-1, 0, 1):
                        app, settings, project = new_app(size + offset)
                        if offset < 0:
                            reject(app, settings, project, payload)
                        else:
                            accept(app, settings, project, payload, content, source_format, filename)
            elif case == "existing":
                app, settings, project = new_app(128)
                accept(app, settings, project, {"lines": lines}, serialized, "json", "frontend-lines.json")
                # Valid records and invalid records must both reject before writes;
                # unknown fields still contribute to the archived content budget.
                for payload in (
                    {"lines": [{"text": "large", "unused": "界" * 128}]},
                    {"lines": [{"text": "", "unused": "界" * 128}]},
                    {"format": "jsonl", "content": json.dumps({"text": "界" * 128}, ensure_ascii=False)},
                ):
                    reject(app, settings, project, payload)
            elif case == "serialization":
                records = [{"text": "x"}] * 32
                payload = {"lines": records}
                wire = json.dumps(payload, separators=(",", ":")).encode("utf-8")
                stored = json.dumps(records, ensure_ascii=False).encode("utf-8")
                check.assertGreater(len(stored), len(wire))
                app, settings, project = new_app(len(stored) - 1)
                check.assertLess(len(wire), settings.max_import_bytes)
                reject(app, settings, project, payload)
            else:
                raise AssertionError(case)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--case":
        run_isolated(sys.argv[2])
    else:
        unittest.main()
