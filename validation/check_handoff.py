import hashlib
import json
from collections import Counter

from markdown_it import MarkdownIt

from business import OPERATIONS, ROOT, SPEC, now


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def markdown_rows(document):
    rows = []
    row = None
    for token in MarkdownIt().enable("table").parse(document):
        if token.type == "tr_open":
            row = []
        elif token.type == "inline" and row is not None:
            row.append(token.content)
        elif token.type == "tr_close":
            rows.append(row)
            row = None
    return rows


def main():
    project = ROOT.parent
    ledger = json.loads((project / "delivery-ledger.json").read_text())
    acceptance = next(item for item in ledger["acceptances"] if item["id"] == "A02")
    assert acceptance["status"] == "PASS"
    assert next(item for item in ledger["tasks"] if item["id"] == "T02")["state"] == "ACCEPTED"
    assert json.loads((project / "evidence/T02/stage-decision.json").read_text())["authority"] == "EXPLICIT_USER"
    receipts = []
    for evidence in ledger["evidence"]:
        if not evidence["id"].startswith("E02-"):
            continue
        path = project / evidence["receipt_path"]
        assert digest(path) == evidence["receipt_sha256"]
        value = json.loads(path.read_text())
        assert value["exit_code"] == 0 and value["inputs_unchanged"] is True
        for item in value["inputs"] + value["artifacts"]:
            assert digest(project / item["path"]) == item["sha256"], item["path"]
        receipts.append({"id": evidence["id"], "check_id": value["check_id"], "receipt": evidence["receipt_path"], "status": "PASS"})
    assert {item["check_id"] for item in receipts} >= {item["id"] for item in acceptance["required_checks"]}
    models = ["deepseek-0-4d888b91-9413-4054-b2d5-67005e9e9f4d", "deepseek-1-84f6e53e-c966-45e8-ac85-b727b634066e"]
    baselines = []
    for run in models:
        directory = project / "evidence/T02" / run
        result = json.loads((directory / "result.json").read_text())
        inputs = json.loads((directory / "inputs.json").read_text())
        for path, expected in inputs["files"].items():
            assert digest(project / path) == expected, path
        assert result["status"] == "PASS" and result["observed_api_type"] == "chat_completions"
        assert result["state"]["status"] == "WAITING_FEEDBACK" and len(result["state"]["message_ids"]) == 1
        events = json.loads((directory / "events.json").read_text())
        assert set(OPERATIONS) <= {event["name"] for event in events if event["type"] == "tool"}
        transport = json.loads((directory / "http-requests.json").read_text())
        assert any(record.get("response_id") and record.get("usage") for record in transport)
        assert all("evaluator_only_expected" not in json.dumps(record["input"]["messages"]) for record in transport if record["type"] == "request")
        baselines.append(result["baseline"])
    assert baselines[0]["snapshot_sha256"] == baselines[1]["snapshot_sha256"] and baselines[0]["namespace"] != baselines[1]["namespace"]
    table = markdown_rows((project / "docs/选型验证.md").read_text())
    definitions = {item["assertion_id"]: item for item in SPEC["assertions"]}
    assertions = []
    for row in table:
        if row and row[0][:6] in definitions and len(row) > 1 and row[1] in {"PASS", "PARTIAL", "NOT_RUN", "BLOCKED", "FAIL"}:
            identifier = row[0][:6]
            assert len(row) == 3 and row[1] in {"PASS", "PARTIAL", "NOT_RUN", "BLOCKED", "FAIL"}
            assertions.append({"assertion_id": identifier, "provider": "deepseek", "run_ids": models, "status": row[1], "actual_and_limits": row[2], "evidence_index": "docs/选型验证.md 第 7 节及当前五组 receipt", "followup": None if row[1] == "PASS" else "D18；后续开发与产品验收；evidence/T02/stage-decision.json"})
    assert {item["assertion_id"] for item in assertions} == set(definitions) and len(assertions) == 37
    source = ROOT / ".work/upstream/nanobot-0.3.5"
    components = ["Sidebar", "ThreadShell", "ThreadComposer", "ThreadMessages", "GenericToolRun", "FilePreviewPanel", "AttachmentTile", "ChatList", "AutomationsSettings", "SettingsPage", "SettingsView", "SecuritySettings", "RuntimeConfigSettings", "AppsSettings", "SkillsCatalogSettings", "ModelsSettings", "ProviderSettings", "TokenUsageCard", "TokenUsageDetails"]
    source_rows = []
    for name in components:
        matches = list((source / "webui/src").rglob(name + ".tsx"))
        assert len(matches) == 1, name
        source_rows.append({"component": name, "path": str(matches[0].relative_to(source)), "sha256": digest(matches[0])})
    for relative in ["nanobot/nanobot.py", "nanobot/sdk/clients.py", "nanobot/sdk/streaming.py", "nanobot/agent/loop.py", "nanobot/agent/runner.py", "nanobot/agent/hook.py", "nanobot/cron/service.py", "nanobot/session/webui_turns.py", "nanobot/providers/openai_compat_provider.py", "nanobot/webui/settings_runtime.py", "nanobot/webui/settings_routes.py", "nanobot/webui/session_automations.py", "webui/src/lib/api.ts"]:
        source_rows.append({"component": relative, "path": relative, "sha256": digest(source / relative)})
    output = project / "evidence/T02"
    (output / "assertions.json").write_text(json.dumps({"at": now(), "definition_version": SPEC["version"], "stage_decision": "D18", "selection_feasibility": "PASS", "complete_product_validation": "PENDING_FOLLOWUP", "assertions": assertions}, ensure_ascii=False, indent=2))
    (output / "reuse-source-map.json").write_text(json.dumps({"tag": "v0.3.5", "commit": "1bb712d3488915ca4ed9ccc1a93067ff722f5ab9", "source_root": str(source), "components": source_rows}, ensure_ascii=False, indent=2))
    result = {"at": now(), "status": "PASS", "scope": "本轮选型交接：当前 receipt 与源码 hash、两次实际模型证据、37 项真实状态完整性、固定两端组件路径；未替代未执行的产品检查", "receipts": receipts, "model_runs": models, "baseline_sha256": baselines[0]["snapshot_sha256"], "assertion_status_counts": dict(Counter(item["status"] for item in assertions)), "source_locations": len(source_rows)}
    (output / "handoff-check.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
