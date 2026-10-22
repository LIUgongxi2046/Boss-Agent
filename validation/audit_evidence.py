import json
import os
import re

from business import ROOT, now
from connection import settings


def main():
    settings()
    sensitive = [os.environ["DEEPSEEK_API_KEY"]]
    for access_path in (ROOT / ".work").rglob("access.json"):
        access = json.loads(access_path.read_text())
        sensitive.extend(value for value in access.values() if isinstance(value, str) and len(value) >= 32)
    sensitive = set(sensitive)
    root = ROOT.parent / "evidence/T02"
    findings = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in {".json", ".jsonl", ".log", ".txt", ".md"}:
            continue
        content = path.read_text()
        count = sum(content.count(value) for value in sensitive)
        temporary_tokens = re.findall(r"\bnbwt_[A-Za-z0-9_-]{43}(?![A-Za-z0-9_-])", content)
        if count or temporary_tokens:
            findings.append({"path": str(path.relative_to(root)), "configured_secret_matches": count, "temporary_token_matches": len(temporary_tokens)})
    report = {"at": now(), "status": "PASS" if not findings else "FAIL", "scope": "用户提供的模型密钥、当前老板/维护凭据及上游临时 token 格式", "findings": findings}
    (root / "credential-audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False))
    assert not findings, "证据中发现敏感凭据，必须处理后复验"


if __name__ == "__main__":
    main()
