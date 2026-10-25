import hashlib
import json
import sqlite3
import subprocess
from pathlib import Path

from lxml import etree
from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[2]
directory = Path(__file__).parent
UPSTREAM = Path("/Users/liuhaoxian/.codex/worktrees/boss-integration/Boss-Agent/.work/product/nanobot")
REVISION = "1bb712d3488915ca4ed9ccc1a93067ff722f5ab9"
checks = []
for name, check_id in (("prompt-identity-ui", "A05-REVOKED-PROVIDER-IDENTITY"),
                        ("prompt-receipt-identity-ui", "A05-REVOKED-RECEIPT-IDENTITY")):
    path = directory / ("w2-20261023-" + name + ".txt")
    tokens = MarkdownIt().parse(path.read_text())
    headings = [index for index, token in enumerate(tokens) if token.type == "inline" and token.content == "Result"
                and index > 0 and tokens[index - 1].type == "heading_open"]
    assert len(headings) == 1
    result = json.loads(next(token.content for token in tokens[headings[0] + 1:] if token.type == "inline"))
    assert result["status"] == "PASS" and result["check_id"] == check_id
    assert result["business_mutation_performed"] is False and result["model_requests"] == 0
    checks.append({"check_id": check_id, "status": "PASS", "source": str(path.relative_to(ROOT)),
                   "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
upstream = {}
for relative in ("webui/src/providers/ClientProvider.tsx", "webui/src/lib/nanobot-client.ts",
                 "webui/src/lib/runtime.ts", "webui/src/lib/types.ts"):
    path = UPSTREAM / relative
    assert path.read_bytes() == subprocess.check_output(["git", "show", REVISION + ":" + relative], cwd=UPSTREAM)
    upstream[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
source = ROOT / ".work/w2-checks/live-runtime-ui-data/test_live_next_turn_adopts_cur0/runtime.sqlite"
with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as original:
    expected = tuple(original.iterdump())
    for name in ("business.sqlite", "receipt.sqlite"):
        target = ROOT / ".work/w2-checks/prompt-ui" / name
        with sqlite3.connect(target.as_uri() + "?mode=ro", uri=True) as copied:
            assert tuple(copied.iterdump()) == expected
    assert original.execute("SELECT COUNT(*) FROM objects WHERE namespace='ui-check' AND kind='runtime_run'").fetchone()[0] == 2
suite = etree.parse(str(directory / "w2-20261023-prompt-identity-complete.xml")).getroot().find("testsuite")
assert suite is not None and suite.get("failures") == "0" and suite.get("errors") == "0"
sources = ["app/webui/MaintainerPromptVersion.tsx", "validation/boss_workspace_api.py", "validation/boss_page_api.py",
           "evidence/T19/check_prompt_identity_server.py", "evidence/T19/check_prompt_identity_ui.js",
           "evidence/T19/check_prompt_receipt_identity_ui.js", "evidence/T19/check_prompt_identity_results.py"]
sources.extend(str(path.relative_to(ROOT)) for path in sorted((directory / "prompt-ui").iterdir()))
report = {"status": "PASS_PROMPT_IDENTITY_COMPONENT_SCOPE", "checks": checks,
          "test_report": {key: suite.get(key) for key in ("tests", "failures", "errors", "skipped", "time")},
          "upstream_source_revision": REVISION, "actual_upstream_source_sha256": upstream,
          "source_and_two_copy_databases_unchanged": True, "actual_databases_reopened": True,
          "actual_runtime_record_count": 2, "new_external_requests": 0, "new_business_mutations": 0,
          "native_mutation_transport_exercised": False, "public_rolechannel_acceptance": "NOT_RUN",
          "visual_acceptance": "NOT_RUN", "full_A19_accepted": False,
          "source_code_sha256_at_collection": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sources}}
(directory / "w2-20261023-prompt-identity-ui.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps({"status": report["status"], "check_count": len(checks),
                  "source_and_two_copy_databases_unchanged": True, "new_external_requests": 0}, ensure_ascii=False))
