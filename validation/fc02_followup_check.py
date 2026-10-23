import json
import sys
from pathlib import Path

from business import checksum, initial_materials
from controls import ControlStore

directory = Path(sys.argv[1]).resolve()
if directory.parent != (Path(__file__).resolve().parent / ".work").resolve():
    raise ValueError("验证数据目录不属于当前工程")
store = ControlStore(directory / "business.sqlite")
action = sys.argv[2]
if action in ("withdraw-child", "withdraw-parent"):
    source = "finance-note" if action == "withdraw-parent" else "sim-bi:weighted-ratios:SIMULATED_BOUNDARY"
    store.control("ui-check", "withdraw", {"source_id": source, "version": "1"})
elif action != "inspect":
    raise ValueError("验证操作无效")
with store.connect() as db:
    initial = store.get(db, "ui-check", "initial", "snapshot")
    counts = {kind: db.execute("SELECT count(*) FROM objects WHERE namespace='ui-check' AND kind=?", (kind,)).fetchone()[0]
              for kind in ("query", "runtime_run", "bi_public_request", "task", "authorization", "outbox")}
    runs = [json.loads(row[0]) for row in db.execute("SELECT body FROM objects WHERE namespace='ui-check' AND kind='runtime_run' ORDER BY id")]
    print(json.dumps({"initial_sha256": checksum(initial), "initial_matches_generator": checksum(initial) == checksum(initial_materials()), "counts": counts,
        "runs": [{key: row[key] for key in ("run_id", "status", "feature_id", "request_id", "session_id", "tool_configuration", "tool_results", "usage", "cost_total")}
                 | ({"tool_errors": row["tool_errors"]} if "tool_errors" in row else {}) for row in runs]}, ensure_ascii=False))
