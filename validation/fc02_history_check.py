import argparse
import json
from pathlib import Path

from nanobot.config.loader import load_config, save_config

from controls import ControlStore


parser = argparse.ArgumentParser()
parser.add_argument("directory", type=Path)
parser.add_argument("action", choices=("inspect", "withdraw"))
args = parser.parse_args()
directory = args.directory.resolve()
if directory.parent != (Path(__file__).resolve().parent / ".work").resolve():
    raise ValueError("验证数据需要位于当前工程独立目录")
store = ControlStore(directory / "business.sqlite")
if args.action == "withdraw":
    store.control("ui-check", "withdraw", {"source_id":"finance-note", "version":"1"})
    config = load_config(directory / "config.json")
    config.channels.websocket["tokenTtlS"] = 30
    save_config(config, directory / "config.json")
with store.connect() as db:
    counts = {kind:db.execute("SELECT count(*) FROM objects WHERE namespace='ui-check' AND kind=?", (kind,)).fetchone()[0]
              for kind in ("query", "runtime_run", "bi_public_request", "task", "authorization", "outbox")}
    source = store.get(db,"ui-check","document","finance-note")
print(json.dumps({"counts":counts,"source_withdrawn":source.get("withdrawn",False)},ensure_ascii=False))
