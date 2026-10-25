import json
import sys
from pathlib import Path

from business import checksum, initial_materials
from controls import ControlStore

directory = Path(sys.argv[1]).resolve()
if directory.parent != (Path(__file__).resolve().parent / ".work").resolve():
    raise ValueError("验证数据目录不属于当前工程")
store = ControlStore(directory / "business.sqlite")
with store.connect() as db:
    initial = store.get(db,"ui-check","initial","snapshot")
    counts = {kind:db.execute("SELECT count(*) FROM objects WHERE namespace='ui-check' AND kind=?",(kind,)).fetchone()[0]
              for kind in ("query","runtime_run","bi_scenario","task","authorization","outbox")}
    runs = [json.loads(row[0]) for row in db.execute("SELECT body FROM objects WHERE namespace='ui-check' AND kind='runtime_run'")]
    print(json.dumps({"initial_matches_generator":checksum(initial)==checksum(initial_materials()),"counts":counts,
        "runs":[{"run_id":row["run_id"],"status":row["status"],"tools":[item["tool_id"] for item in row["tool_configuration"]],
                 "feature_id":row["feature_id"],"usage":row["usage"],"cost_total":row["cost_total"]} for row in runs]},ensure_ascii=False))
