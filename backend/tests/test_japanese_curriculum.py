from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.modules.japanese.adapters import (  # noqa: E402
    AdapterBundle,
    MockASRAdapter,
    MockTTSAdapter,
    MockTeacherAdapter,
)
from app.modules.japanese.curriculum import SCENARIOS, STAGES, validate_catalog  # noqa: E402
from app.modules.japanese.models import CoachMode, LearningMode, utc_now  # noqa: E402
from app.modules.japanese.repository import JapaneseRepository  # noqa: E402
from app.modules.japanese.service import JapaneseLearningService, JapaneseServiceError  # noqa: E402


class JapaneseCurriculumTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.service = JapaneseLearningService(
            JapaneseRepository(root / "studio.sqlite3"),
            root / "assets",
            AdapterBundle(MockASRAdapter(), MockTeacherAdapter(), MockTTSAdapter()),
        )
        self.learner = self.service.create_learner(
            "路径测试学习者", "N4", ["在日本独立生活"], ["旅行", "游戏"]
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_catalog_covers_daily_life_with_valid_prerequisites(self) -> None:
        validate_catalog()
        catalog = self.service.curriculum()
        self.assertEqual(len(STAGES), 4)
        self.assertEqual(len(SCENARIOS), 38)
        self.assertEqual(catalog["coverage"]["scenario_count"], 38)
        self.assertGreaterEqual(len(catalog["coverage"]["domains"]), 10)
        self.assertEqual({item["level"] for item in SCENARIOS}, {"N5", "N4", "N3", "N2", "N1"})
        scenario_ids = {item["id"] for item in SCENARIOS}
        for scenario in SCENARIOS:
            self.assertTrue(set(scenario["prerequisites"]).issubset(scenario_ids))
            self.assertEqual(scenario["completion_policy"]["minimum_turns"], 3)

    def test_learning_path_uses_declared_level_without_inventing_mastery(self) -> None:
        path = self.service.learning_path(self.learner.id)
        self.assertEqual(path["summary"]["total"], 38)
        self.assertEqual(path["summary"]["completed"], 0)
        self.assertGreaterEqual(path["summary"]["available"], 20)
        self.assertEqual(path["policy"]["assessment"], "separate_metrics_only_no_overall_language_score")
        self.assertEqual(len(path["curve"]), 4)
        self.assertTrue(path["recommendations"])
        self.assertTrue(
            all(stage["completion"]["meaning"].endswith("不是语言能力总分。") for stage in path["stages"])
        )

    def test_completed_and_active_scenarios_have_persisted_evidence(self) -> None:
        completed = self.service.start_session(
            self.learner.id,
            LearningMode.CONVERSATION,
            CoachMode.FLUENT,
            "车站买票",
            {"curriculum_scenario_id": "station-ticket", "curriculum_version": "test"},
        )
        with self.assertRaisesRegex(JapaneseServiceError, "至少需要 3 轮"):
            self.service.complete_session(completed.id)
        self.service.repository.complete_session(completed.id, utc_now())
        active = self.service.start_session(
            self.learner.id,
            LearningMode.CONVERSATION,
            CoachMode.STRICT,
            "换乘与误点",
            {"curriculum_scenario_id": "train-transfer", "curriculum_version": "test"},
        )

        path = self.service.learning_path(self.learner.id)
        rows = {
            scenario["id"]: scenario
            for stage in path["stages"]
            for scenario in stage["scenarios"]
        }
        self.assertEqual(rows["station-ticket"]["status"], "completed")
        self.assertEqual(rows["station-ticket"]["evidence"]["completed_session_count"], 1)
        self.assertIn(completed.id, rows["station-ticket"]["evidence"]["session_ids"])
        self.assertEqual(rows["train-transfer"]["status"], "in_progress")
        self.assertIn(active.id, rows["train-transfer"]["evidence"]["session_ids"])
        self.assertEqual(path["summary"]["completed"], 1)
        self.assertEqual(path["summary"]["in_progress"], 1)


if __name__ == "__main__":
    unittest.main()
