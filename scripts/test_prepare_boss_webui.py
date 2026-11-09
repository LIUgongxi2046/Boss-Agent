import unittest
import json
from pathlib import Path

import prepare_boss_webui as prepare
from jsonschema import Draft202012Validator


class WorkDirectoryTests(unittest.TestCase):
    def tearDown(self) -> None:
        prepare.configure_work_dir(None)

    def test_default_paths(self) -> None:
        prepare.configure_work_dir(None)
        self.assertEqual(prepare.SOURCE, prepare.ROOT / ".work/product/nanobot")
        self.assertEqual(prepare.NPM_CACHE, prepare.ROOT / ".work/npm-cache")
        self.assertEqual(prepare.OUTPUT_DIR, prepare.SOURCE / "nanobot/web/dist")
        self.assertEqual(prepare.OVERLAY_ROOT, prepare.ROOT)

    def test_isolated_paths(self) -> None:
        work_dir = prepare.ROOT / ".work/upgrade2-u2-07/isolated-build"
        prepare.configure_work_dir(work_dir)
        self.assertEqual(prepare.SOURCE, work_dir / "nanobot")
        self.assertEqual(prepare.NPM_CACHE, work_dir / "npm-cache")
        self.assertEqual(prepare.OUTPUT_DIR, work_dir / "dist")
        self.assertEqual(prepare.MANIFEST_DIR, work_dir / "overlay/.work/product")
        prepare.configure_work_dir(None)
        self.assertEqual(prepare.OVERLAY_ROOT, prepare.ROOT)

    def test_shared_and_external_paths_are_rejected(self) -> None:
        for path in (prepare.ROOT / ".work", prepare.ROOT / ".work/product", prepare.ROOT / ".work/product/nanobot", Path("/")):
            with self.subTest(path=path), self.assertRaises(ValueError):
                prepare.configure_work_dir(path)

    def test_runtime_schema_sources_and_import_paths(self) -> None:
        for name in prepare.RUN_SCHEMAS:
            with self.subTest(name=name):
                source = prepare.ROOT / "specs" / name
                schema = json.loads(source.read_text(encoding="utf-8"))
                self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
                Draft202012Validator.check_schema(schema)
                self.assertEqual((prepare.BOSS_DIR / "../../specs" / name).resolve(), (prepare.SOURCE_WEBUI / "specs" / name).resolve())

    def test_artifact_schema_source_and_import_path(self) -> None:
        source = prepare.ROOT / "validation" / "agent_artifact_schema.json"
        schema = json.loads(source.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        self.assertEqual((prepare.BOSS_DIR / "../../validation/agent_artifact_schema.json").resolve(), (prepare.SOURCE_WEBUI / "validation/agent_artifact_schema.json").resolve())

    def test_design_metadata_import_path(self) -> None:
        self.assertEqual((prepare.BOSS_DIR / "../../Boss-Agent-Desktop-Complete-v7/meta/页面配置.json").resolve(), (prepare.SOURCE_WEBUI / "Boss-Agent-Desktop-Complete-v7/meta/页面配置.json").resolve())
        self.assertEqual(len(json.loads((prepare.DESIGN / "meta/页面配置.json").read_text(encoding="utf-8"))), 72)

    def test_simulation_definition_import_path(self) -> None:
        source = prepare.ROOT / "data/simulation/supply-quality-v1.yaml"
        self.assertTrue(source.is_file())
        self.assertEqual((prepare.BOSS_DIR / "../../data/simulation/supply-quality-v1.yaml").resolve(), (prepare.SOURCE_WEBUI / "data/simulation/supply-quality-v1.yaml").resolve())


if __name__ == "__main__":
    unittest.main()
