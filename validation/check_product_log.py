import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check():
    log_path = ROOT / "validation/.work/desktop/diagnostics/w3-runtime-service.log"
    content = log_path.read_text()
    lines = content.splitlines()
    pattern = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} \| [A-Z]+ \| [A-Za-z0-9_.]+:[A-Za-z0-9_<>]+:\d+ \| [A-Za-z_][A-Za-z0-9_]*")
    assert lines and all(line == "应用验证服务已启动" or pattern.fullmatch(line) for line in lines)
    assert any("nanobot.agent.loop:_assemble_outbound:" in line for line in lines)
    return {"status": "PASS_PRODUCT_SERVICE_LOG_FORMAT_ONLY", "lines_checked": len(lines),
            "log_sha256": hashlib.sha256(log_path.read_bytes()).hexdigest(),
            "source_sha256": hashlib.sha256((ROOT / "validation/application.py").read_bytes()).hexdigest(),
            "actual_model_output_assembly_observed": True,
            "message_body_and_traceback_formatted": False,
            "scope": "当前W3独立产品服务日志；其他诊断和安装包分别核查"}


if __name__ == "__main__":
    result = check()
    output = ROOT / "evidence/T09/w3-20261023/product-service-log.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))
