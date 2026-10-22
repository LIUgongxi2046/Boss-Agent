import argparse
import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path

from business import now


parser = argparse.ArgumentParser()
parser.add_argument("receipt", type=Path)
args = parser.parse_args()
receipt = json.loads(args.receipt.read_text())
assert receipt["exit_code"] == 0 and receipt["inputs_unchanged"] is True
for row in receipt["inputs"] + receipt["artifacts"]:
    assert hashlib.sha256(Path(row["path"]).read_bytes()).hexdigest() == row["sha256"], row["path"]
assert platform.mac_ver()[0] == "13.7.8" and platform.machine() == "x86_64"
assert importlib.metadata.version("nanobot-ai") == "0.3.5"
print(json.dumps({"at": now(), "status": "PASS", "scope": "复核已保存的真实执行记录、当前输入及环境一致性；本次没有重新发送模型请求", "original_check_id": receipt["check_id"], "original_receipt": str(args.receipt), "original_command": receipt["command"], "original_started_at": receipt["started_at"], "original_ended_at": receipt["ended_at"], "original_exit_code": receipt["exit_code"], "verified_inputs": len(receipt["inputs"]), "verified_artifacts": len(receipt["artifacts"]), "runtime_environment": {"macos": platform.mac_ver()[0], "architecture": platform.machine(), "nanobot": importlib.metadata.version("nanobot-ai")}}, ensure_ascii=False))
