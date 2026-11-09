import json
import subprocess
from pathlib import Path

from test_agent_artifacts import prepared


ROOT = Path(__file__).resolve().parents[2]


def test_artifact_source_metadata_visible(prepared):
    store, _, service, _, _, _, _ = prepared
    with store.connect() as db:
        db.execute("BEGIN")
        _, refs, _ = service._sources(db, ["simulation-meeting-material"])
    result = subprocess.run(["node", str(ROOT / "app/tests/u2_09_artifact_source_ui_check.cjs")], input=json.dumps(refs[0], ensure_ascii=False), text=True, capture_output=True, check=True, cwd=ROOT)
    assert json.loads(result.stdout)["reference_visible"]
