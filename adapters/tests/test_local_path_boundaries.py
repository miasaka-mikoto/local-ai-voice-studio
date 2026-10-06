from pathlib import Path
import json
import tempfile
import unittest
from adapters.deployment import import_deployment_manifest

class LocalPathBoundaryTests(unittest.TestCase):
    def test_native_absolute_paths_and_relative_paths_stay_local(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            model = root / 'model'; model.mkdir()
            for model_path in [str(model), 'model']:
                with self.subTest(path=model_path):
                    manifest = root / 'deployment.json'
                    manifest.write_text(json.dumps({'schema_version':'1.0','environment_root':str(root),'engines':[{'id':'local','model_path':model_path}]}),encoding='utf-8')
                    capability = import_deployment_manifest(manifest).capabilities[0]
                    self.assertTrue(capability.available_on_disk)
                    self.assertEqual(capability.local_paths, (str(model),))

    def test_traversal_unc_and_drive_relative_paths_remain_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            for bad in ['../outside', r'..\outside', r'C:relative', r'\Windows\System32', r'\\server\share', '//server/share']:
                with self.subTest(path=bad):
                    manifest = root / 'deployment.json'
                    manifest.write_text(json.dumps({'schema_version':'1.0','engines':[{'id':'local','model_path':bad}]}),encoding='utf-8')
                    result = import_deployment_manifest(manifest)
                    self.assertEqual(result.capabilities[0].local_paths, ())
                    self.assertFalse(result.capabilities[0].available_on_disk)

    def test_invalid_endpoint_is_ignored_without_disclosing_input(self):
        with tempfile.TemporaryDirectory() as temp:
            manifest = Path(temp) / 'deployment.json'
            for bad in ['http://[secret', 'http://127.0.0.1:999999/']:
                with self.subTest(endpoint=bad):
                    manifest.write_text(json.dumps({'schema_version':'1.0','engines':[{'id':'local','url':bad,'source':bad}]}),encoding='utf-8')
                    result = import_deployment_manifest(manifest)
                    self.assertIsNone(result.capabilities[0].endpoint)
                    self.assertIsNone(result.capabilities[0].source_url)
                    self.assertNotIn(bad, json.dumps(result.to_dict()))
