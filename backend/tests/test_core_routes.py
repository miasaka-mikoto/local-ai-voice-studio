from __future__ import annotations

import builtins
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import Settings
from app.main import create_app


class RouteContractTests(unittest.TestCase):
    def test_openapi_and_websocket_contract_exist_without_httpx(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings.load(
                data_root=root / "data", database_path=root / "data" / "api.sqlite3", worker_enabled=False
            )
            application = create_app(settings)
            schema = application.openapi()
            paths = schema["paths"]
            expected = {
                "/api/v1/health",
                "/api/v1/bootstrap",
                "/api/v1/projects",
                "/api/v1/projects/{project_id}/imports",
                "/api/v1/projects/{project_id}/generations",
                "/api/v1/lines/{line_id}/takes/{take_id}/select",
                "/api/v1/projects/{project_id}/exports",
                "/api/v1/tasks/{task_id}/{action}",
                "/api/japanese/health",
                "/api/japanese/curriculum",
                "/api/japanese/recordings",
                "/api/japanese/learners/{learner_id}/progress",
                "/api/japanese/learners/{learner_id}/learning-path",
                "/api/japanese/learners/{learner_id}/pronunciation-plan",
                "/api/japanese/sessions/{session_id}/shadowing/references",
                "/api/japanese/sessions/{session_id}/shadowing/exercises/{exercise_id}/attempts",
                "/api/japanese/turns/{turn_id}/demonstration",
                "/api/japanese/exercises/{exercise_id}/reference",
            }
            self.assertTrue(expected.issubset(paths))
            websocket_paths = {route.path for route in application.routes if route.__class__.__name__ == "APIWebSocketRoute"}
            self.assertIn("/api/v1/ws/tasks", websocket_paths)
            self.assertIn("/api/v1/ws/jobs", websocket_paths)

    def test_bundled_japanese_import_failure_is_fail_fast(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings.load(
                data_root=root / "data", database_path=root / "data" / "api.sqlite3", worker_enabled=False
            )
            real_import = builtins.__import__

            def fail_japanese_import(name, globals=None, locals=None, fromlist=(), level=0):
                if name == "modules.japanese.router" and level == 1:
                    raise ImportError("simulated Japanese module import failure")
                return real_import(name, globals, locals, fromlist, level)

            with patch("builtins.__import__", side_effect=fail_japanese_import):
                with self.assertRaisesRegex(ImportError, "simulated Japanese module import failure"):
                    create_app(settings)


if __name__ == "__main__":
    unittest.main()
