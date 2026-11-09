import json
import subprocess
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_frontend_yaml_matches_existing_authoritative_data():
    source = ROOT / "data/simulation/supply-quality-v1.yaml"
    expected = yaml.safe_load(source.read_text(encoding="utf-8"))
    actual = subprocess.run(["node", str(ROOT / "app/tests/upgrade2-yaml-definition.mjs")], check=True, capture_output=True, text=True)
    assert json.loads(actual.stdout) == expected
