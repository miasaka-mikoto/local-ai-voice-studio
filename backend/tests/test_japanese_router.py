from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.modules.japanese.adapters import (  # noqa: E402
    AdapterBundle,
    MockASRAdapter,
    MockTTSAdapter,
    MockTeacherAdapter,
)
from app.modules.japanese.repository import JapaneseRepository  # noqa: E402
from app.modules.japanese.router import create_router  # noqa: E402
from app.modules.japanese.service import JapaneseLearningService  # noqa: E402


class JapaneseRouterTests(unittest.TestCase):
    def test_router_exposes_mvp_contract_without_httpx_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = JapaneseLearningService(
                JapaneseRepository(root / "db.sqlite3"),
                root / "assets",
                AdapterBundle(MockASRAdapter(), MockTeacherAdapter(), MockTTSAdapter()),
            )
            router = create_router(service)
            routes = {
                (route.path, method)
                for route in router.routes
                for method in (route.methods or set())
            }
            expected = {
                ("/api/japanese/health", "GET"),
                ("/api/japanese/curriculum", "GET"),
                ("/api/japanese/learners", "POST"),
                ("/api/japanese/learners/{learner_id}", "PATCH"),
                ("/api/japanese/sessions", "POST"),
                ("/api/japanese/sessions/{session_id}/complete", "POST"),
                ("/api/japanese/sessions/{session_id}/turns", "GET"),
                ("/api/japanese/recordings", "POST"),
                ("/api/japanese/sessions/{session_id}/turns", "POST"),
                ("/api/japanese/sentence-repair", "POST"),
                ("/api/japanese/sessions/{session_id}/shadowing", "POST"),
                ("/api/japanese/sessions/{session_id}/shadowing/references", "POST"),
                (
                    "/api/japanese/sessions/{session_id}/shadowing/exercises/{exercise_id}/attempts",
                    "POST",
                ),
                ("/api/japanese/turns/{turn_id}/demonstration", "GET"),
                ("/api/japanese/exercises/{exercise_id}/reference", "GET"),
                ("/api/japanese/reviews/{review_id}/grade", "POST"),
                ("/api/japanese/learners/{learner_id}/progress", "GET"),
                ("/api/japanese/learners/{learner_id}/learning-path", "GET"),
                ("/api/japanese/learners/{learner_id}/pronunciation-plan", "POST"),
                ("/api/japanese/learners/{learner_id}/project-lessons", "POST"),
                ("/api/japanese/learners/{learner_id}/anki-connect", "GET"),
            }
            self.assertTrue(expected.issubset(routes))
            application = FastAPI()
            application.include_router(router)
            schema = application.openapi()
            self.assertIn("/api/japanese/sessions/{session_id}/shadowing", schema["paths"])


if __name__ == "__main__":
    unittest.main()
