"""Isolated route budget tests: no app startup, models, workers or user data.

Extract only the route AST because importing app.main constructs the application.
Repository/snapshot spies test the pre-persistence boundary, not SQLite integration.
"""
from __future__ import annotations

import ast
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock


APP_DIR = Path(__file__).resolve().parents[1] / "app"


def load_route(budget: int):
    source = ast.parse((APP_DIR / "main.py").read_text(encoding="utf-8"))
    factory = next(node for node in source.body if isinstance(node, ast.FunctionDef) and node.name == "create_app")
    route = next(node for node in factory.body if isinstance(node, ast.FunctionDef) and node.name == "import_lines")
    route.decorator_list = []
    errors = ast.parse((APP_DIR / "errors.py").read_text(encoding="utf-8"))
    error = next(node for node in errors.body if isinstance(node, ast.ClassDef) and node.name == "DomainError")
    repository = SimpleNamespace(import_lines=Mock())
    snapshots = SimpleNamespace(build=Mock(return_value={"snapshot": "synthetic"}))
    normalize = Mock(side_effect=lambda value, index: {"text": value["text"], "ordinal": index})
    parse = Mock(return_value=SimpleNamespace(lines=[{"text": "parsed"}], warnings=["synthetic warning"]))
    decode = Mock(side_effect=lambda data, encoding: data.decode(encoding or "utf-8"))
    namespace = {
        "Any": Any, "ImportRequest": object, "json": json, "Path": Path,
        "configured": SimpleNamespace(max_import_bytes=budget),
        "repository": repository, "snapshots": snapshots,
        "_import_line_from_ui": normalize, "parse_import": parse, "decode_bytes": decode,
    }
    module = ast.Module(body=[error, route], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(APP_DIR / "main.py"), "exec"), namespace)
    return SimpleNamespace(route=namespace["import_lines"], error=namespace["DomainError"],
                           repository=repository, snapshots=snapshots, normalize=normalize,
                           parse=parse, decode=decode)


def payload(**values):
    defaults = dict(lines=None, content=None, filename=None, format=None, source_path=None, encoding=None)
    defaults.update(values)
    return SimpleNamespace(**defaults)


class ImportBudgetTests(unittest.TestCase):
    def assert_rejected(self, harness, request, code="import_too_large", status=400):
        with self.assertRaises(harness.error) as caught:
            harness.route("synthetic-project", request)
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(caught.exception.status_code, status)
        harness.repository.import_lines.assert_not_called()
        harness.snapshots.build.assert_not_called()
        harness.normalize.assert_not_called()
        harness.parse.assert_not_called()

    def test_lines_below_equal_above_utf8_budget(self):
        for lines in ([{"text": "hello"}], [{"text": "中文台词"}]):
            content = json.dumps(lines, ensure_ascii=False)
            size = len(content.encode("utf-8"))
            for delta in (-1, 0, 1):
                with self.subTest(lines=lines, budget_delta=delta):
                    harness = load_route(size + delta)
                    if delta < 0:
                        self.assert_rejected(harness, payload(lines=lines))
                    else:
                        result = harness.route("synthetic-project", payload(lines=lines))
                        harness.repository.import_lines.assert_called_once_with(
                            "synthetic-project", "json", "frontend-lines.json", content,
                            [{"text": lines[0]["text"], "ordinal": 0}], [])
                        self.assertEqual(result, {"snapshot": "synthetic"})
                        harness.snapshots.build.assert_called_once_with()

    def test_utf8_bytes_not_character_count(self):
        lines = [{"text": "中文"}]
        content = json.dumps(lines, ensure_ascii=False)
        self.assertGreater(len(content.encode("utf-8")), len(content))
        self.assert_rejected(load_route(len(content)), payload(lines=lines))

    def test_unmapped_fields_count_before_normalization(self):
        lines = [{"text": "ok", "unmapped": {"padding": "中" * 100}}]
        harness = load_route(64)
        self.assert_rejected(harness, payload(lines=lines))

    def test_over_budget_invalid_line_rejected_before_normalization(self):
        self.assert_rejected(load_route(32), payload(lines=[{"unused": "x" * 100}]))

    def test_lines_take_precedence_over_other_sources(self):
        lines = [{"text": "ok"}, {"text": "second"}]
        content = json.dumps(lines, ensure_ascii=False)
        harness = load_route(len(content.encode("utf-8")))
        harness.route("synthetic-project", payload(lines=lines, content="ignored" * 100,
                      source_path="nonexistent-ignored-path", format="csv", filename="chosen.json"))
        args = harness.repository.import_lines.call_args.args
        self.assertEqual(args[1:4], ("json", "chosen.json", content))
        self.assertEqual(args[4], [{"text": "ok", "ordinal": 0}, {"text": "second", "ordinal": 1}])
        harness.decode.assert_not_called()
        harness.parse.assert_not_called()

    def test_empty_lines_still_use_lines_branch(self):
        harness = load_route(2)
        harness.route("synthetic-project", payload(lines=[], content="ignored", format="csv"))
        harness.repository.import_lines.assert_called_once_with(
            "synthetic-project", "json", "frontend-lines.json", "[]", [], [])
        harness.parse.assert_not_called()
        harness.normalize.assert_not_called()
        self.assert_rejected(load_route(1), payload(lines=[]))

    def test_content_budget_and_format_unchanged(self):
        content = "中文"
        size = len(content.encode("utf-8"))
        for delta in (-1, 0, 1):
            with self.subTest(delta=delta):
                harness = load_route(size + delta)
                request = payload(content=content, format="CSV")
                if delta < 0:
                    self.assert_rejected(harness, request)
                else:
                    harness.route("synthetic-project", request)
                    harness.parse.assert_called_once_with("csv", content)
                    harness.repository.import_lines.assert_called_once_with(
                        "synthetic-project", "csv", "import.csv", content,
                        [{"text": "parsed"}], ["synthetic warning"])

    def test_missing_content_and_format_unchanged(self):
        self.assert_rejected(load_route(64), payload(), "missing_import_content")
        self.assert_rejected(load_route(64), payload(content="ok"), "missing_import_format")

    def test_source_file_budget_and_precedence_unchanged(self):
        with tempfile.TemporaryDirectory(prefix="import-budget-") as directory:
            source = Path(directory) / "synthetic.csv"
            source.write_bytes(b"ok")
            for delta in (-1, 0, 1):
                with self.subTest(delta=delta):
                    harness = load_route(2 + delta)
                    request = payload(source_path=str(source), content="ignored", filename="override.csv")
                    if delta < 0:
                        self.assert_rejected(harness, request)
                        harness.decode.assert_not_called()
                    else:
                        harness.route("synthetic-project", request)
                        harness.parse.assert_called_once_with("csv", "ok")
                        self.assertEqual(harness.repository.import_lines.call_args.args[2:4], ("override.csv", "ok"))
            self.assertEqual(source.read_bytes(), b"ok")
            self.assertEqual(list(Path(directory).iterdir()), [source])

    def test_decoded_source_utf8_budget_unchanged(self):
        with tempfile.TemporaryDirectory(prefix="import-budget-") as directory:
            source = Path(directory) / "synthetic.csv"
            source.write_bytes("中文".encode("gb18030"))
            harness = load_route(4)
            self.assert_rejected(harness, payload(source_path=str(source), encoding="gb18030"))
            harness.decode.assert_called_once_with(source.read_bytes(), "gb18030")
            self.assertEqual(list(Path(directory).iterdir()), [source])

    def test_missing_source_unchanged(self):
        with tempfile.TemporaryDirectory(prefix="import-budget-") as directory:
            self.assert_rejected(load_route(64), payload(source_path=str(Path(directory) / "absent.csv")),
                                 "import_file_not_found", 404)


if __name__ == "__main__":
    unittest.main()
