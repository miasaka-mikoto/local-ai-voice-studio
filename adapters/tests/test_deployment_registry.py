from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from adapters import EngineKind, EngineRegistry, LicenseRisk, MockEngineAdapter
from adapters.deployment import MAX_MANIFEST_BYTES, classify_license, import_deployment_manifest


class DeploymentImportTests(unittest.TestCase):
    def _manifest(self, root: Path, *, endpoint: str = "http://127.0.0.1:9000") -> Path:
        model = root / "model"
        model.mkdir()
        path = root / "deployment.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "hardware": {"gpu": "test", "system_ram_gb": 16, "secret": "drop"},
                    "engines": [
                        {
                            "id": "demo_tts",
                            "role": "trainable_cross_lingual_emotion_voice_clone_48khz_tts",
                            "model": "example/demo",
                            "model_path": str(model),
                            "url": endpoint,
                            "license": "Apache-2.0",
                            "install": ["must", "not", "be", "copied"],
                            "api_key": "must-not-leak",
                            "status": "validated_static",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_allowlisted_import_and_capability_inference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = import_deployment_manifest(self._manifest(Path(directory)))
        self.assertEqual(len(result.capabilities), 1)
        item = result.capabilities[0]
        self.assertIn(EngineKind.TTS, item.kinds)
        self.assertIn(EngineKind.TRAINING, item.kinds)
        self.assertTrue(item.supports_voice_cloning)
        self.assertTrue(item.supports_emotion_control)
        self.assertEqual(item.output_sample_rates, (48_000,))
        self.assertEqual(item.license_risk, LicenseRisk.PERMISSIVE)
        self.assertTrue(item.available_on_disk)
        self.assertEqual(item.endpoint, "http://127.0.0.1:9000")
        self.assertNotIn("install", item.metadata)
        self.assertNotIn("api_key", item.metadata)
        self.assertNotIn("secret", result.hardware)

    def test_remote_endpoint_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = import_deployment_manifest(
                self._manifest(Path(directory), endpoint="https://example.invalid/engine")
            )
        self.assertIsNone(result.capabilities[0].endpoint)
        self.assertTrue(any("non-loopback" in warning for warning in result.warnings))

    def test_endpoint_queries_and_network_paths_are_not_retained_or_probed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._manifest(Path(directory), endpoint="http://127.0.0.1:9000/?token=secret")
            value = json.loads(path.read_text(encoding="utf-8"))
            value["engines"][0]["model_path"] = r"\\example.invalid\share\model"
            value["engines"][0]["source"] = "https://example.invalid/repo?token=secret"
            path.write_text(json.dumps(value), encoding="utf-8")
            result = import_deployment_manifest(path)
        item = result.capabilities[0]
        self.assertIsNone(item.endpoint)
        self.assertIsNone(item.source_url)
        self.assertFalse(any(value.startswith("\\\\") for value in item.local_paths))
        self.assertTrue(any("network path" in warning for warning in result.warnings))

    def test_warnings_and_allowlisted_text_never_echo_nested_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._manifest(
                Path(directory), endpoint="https://user:ENDPOINT-SECRET@example.invalid/api"
            )
            value = json.loads(path.read_text(encoding="utf-8"))
            value["engines"][0]["model"] = {"api_key": "MODEL-SECRET"}
            value["engines"][0]["license"] = {"token": "LICENSE-SECRET"}
            value["engines"][0]["role"] = {"password": "ROLE-SECRET"}
            value["engines"][0]["license_note"] = "api_key=STRING-SECRET"
            value["engines"][0]["runner"] = "python run.py --token RUNNER-SECRET"
            value["engines"][0]["install_mode"] = "shell --password INSTALL-SECRET"
            path.write_text(json.dumps(value), encoding="utf-8")
            result = import_deployment_manifest(path)
        rendered = json.dumps(result.to_dict(), ensure_ascii=False)
        for secret in (
            "ENDPOINT-SECRET", "MODEL-SECRET", "LICENSE-SECRET", "ROLE-SECRET",
            "STRING-SECRET", "RUNNER-SECRET", "INSTALL-SECRET",
        ):
            self.assertNotIn(secret, rendered)

    def test_environment_root_and_windows_ambiguous_paths_cannot_escape_allowed_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._manifest(root)
            value = json.loads(path.read_text(encoding="utf-8"))
            value["environment_root"] = r"..\..\outside"
            value["engines"][0]["model_path"] = r"C:relative-model"
            value["engines"][0]["environment"] = r"\Windows\System32"
            path.write_text(json.dumps(value), encoding="utf-8")
            result = import_deployment_manifest(path)
            allowed = os.path.normcase(str(root.resolve()))
        self.assertTrue(any("environment_root" in warning for warning in result.warnings))
        self.assertTrue(all(os.path.commonpath((allowed, os.path.normcase(value))) == allowed for value in result.capabilities[0].local_paths))

    def test_environment_alone_does_not_make_missing_model_available(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = root / "env"
            environment.mkdir()
            path = root / "deployment.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "engines": [
                            {
                                "id": "missing_model",
                                "role": "tts",
                                "license": "MIT",
                                "model_path": str(root / "missing"),
                                "environment": str(environment),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            item = import_deployment_manifest(path).capabilities[0]
        self.assertFalse(item.available_on_disk)
        self.assertIn("environment", item.local_path_roles)

    def test_license_classifier_requires_exact_permissive_identifier(self) -> None:
        self.assertEqual(classify_license("MIT"), LicenseRisk.PERMISSIVE)
        self.assertEqual(classify_license("Commercial use is limited"), LicenseRisk.CUSTOM_REVIEW)
        self.assertEqual(classify_license("Unlimited custom license"), LicenseRisk.CUSTOM_REVIEW)

    def test_schema_duplicate_keys_and_manifest_size_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "deployment.json"
            path.write_text('{"schema_version":"1.0","schema_version":"1.0","engines":[]}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
                import_deployment_manifest(path)
            path.write_text(json.dumps({"schema_version": "999.0", "engines": []}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unsupported"):
                import_deployment_manifest(path)
            path.write_bytes(b" " * (MAX_MANIFEST_BYTES + 1))
            with self.assertRaisesRegex(ValueError, "manifest size"):
                import_deployment_manifest(path)

    def test_duplicate_and_invalid_ids_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._manifest(Path(directory))
            value = json.loads(path.read_text(encoding="utf-8"))
            value["engines"].append(dict(value["engines"][0]))
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate"):
                import_deployment_manifest(path)
            value["engines"] = [{"id": "../unsafe", "license": "unknown"}]
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid engine id"):
                import_deployment_manifest(path)

    def test_non_finite_json_numbers_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "deployment.json"
            path.write_text('{"engines":[],"hardware":{"system_ram_gb":NaN}}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "non-finite"):
                import_deployment_manifest(path)

    def test_synthetic_manifest_imports_without_runtime_start(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = import_deployment_manifest(self._manifest(Path(directory)))
        self.assertEqual(["demo_tts"], [item.engine_id for item in result.capabilities])
        self.assertEqual("1.0", result.schema_version)
        self.assertTrue(all(item.engine_id for item in result.capabilities))


class RegistryTests(unittest.TestCase):
    def test_duplicate_registration_requires_explicit_replace(self) -> None:
        registry = EngineRegistry()
        registry.register(MockEngineAdapter())
        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.register(MockEngineAdapter())
        registry.register(MockEngineAdapter(), replace=True)
        self.assertEqual(registry.get("mock").capability.engine_id, "mock")

    def test_backend_catalog_bridge_uses_sanitized_capability(self) -> None:
        registry = EngineRegistry()
        registry.register(MockEngineAdapter())
        record = registry.backend_catalog()[0]
        self.assertEqual(record["id"], "mock")
        self.assertEqual(record["sample_rate_hz"], 48_000)
        self.assertFalse(record["heavy_gpu"])
        self.assertTrue(record["executable_in_mvp"])

    def test_unknown_languages_do_not_match_without_explicit_opt_in(self) -> None:
        registry = EngineRegistry()
        registry.register(MockEngineAdapter())
        self.assertEqual(registry.capabilities(language="ja"), ())
        self.assertEqual(len(registry.capabilities(language="ja", include_unknown_languages=True)), 1)

    def test_manifest_only_engine_named_mock_is_not_reported_executable(self) -> None:
        registry = EngineRegistry()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "deployment.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "engines": [{"id": "mock", "role": "tts", "license": "MIT"}],
                    }
                ),
                encoding="utf-8",
            )
            registry.import_manifest(path)
        self.assertFalse(registry.backend_catalog()[0]["executable_in_mvp"])

    def test_manifest_import_is_atomic_on_registry_conflict(self) -> None:
        registry = EngineRegistry()
        registry.register(MockEngineAdapter())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "deployment.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "engines": [
                            {"id": "new_engine", "role": "tts", "license": "MIT"},
                            {"id": "mock", "role": "tts", "license": "MIT"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "would replace"):
                registry.import_manifest(path)
        with self.assertRaises(KeyError):
            registry.get("new_engine")


if __name__ == "__main__":
    unittest.main()
