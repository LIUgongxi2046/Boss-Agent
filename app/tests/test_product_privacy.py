"""Product runtime metadata redaction tests (no real API key or model call)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FILE = ROOT / "validation" / "safe_diagnostics.py"
spec = importlib.util.spec_from_file_location("boss_safe_diagnostics", FILE)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

PRIVATE = "SYNTHETIC_PRIVATE_MESSAGE_SHOULD_NEVER_BE_SAVED"


def test_tool_arguments_and_source_body_are_redacted():
    events = mod.RedactedEventList()
    events.append({
        "type": "tool", "name": "create_assignment", "at": "2026-10-22T12:00:00Z",
        "input": {"message": PRIVATE, "api_key": "synthetic-token"},
        "output": {"task_id": "task-1", "status": "OPEN", "source_body": PRIVATE},
    })
    assert events[0]["task_id"] == "task-1"
    assert events[0]["status"] == "OPEN"
    assert "input" not in events[0]
    assert "output" not in events[0]
    assert PRIVATE not in json.dumps(events)
    assert "synthetic-token" not in json.dumps(events)


def test_prompt_and_private_error_do_not_leave_runtime_event():
    events = mod.RedactedEventList()
    events.append({"type": "iteration", "iteration": 1, "usage": {
        "prompt_tokens": 10, "completion_tokens": 4, "hidden": PRIVATE,
    }, "error": PRIVATE, "at": "now"})
    assert events[0]["error_present"] is True
    assert events[0]["usage"] == {"prompt_tokens": 10, "completion_tokens": 4}
    assert PRIVATE not in str(events)


def test_runtime_admission_has_only_allowed_metadata():
    events = mod.RedactedEventList()
    events.append({"type": "runtime_admission", "configuration": {
        "provider": "deepseek", "model_id": "deepseek-flash",
        "config_sha256": "testhash",
        "api_key": "not-a-real-key",
        "owner_memory": PRIVATE,
    }})
    assert set(events[0]["configuration"]) == {"provider", "model_id", "config_sha256"}
    assert PRIVATE not in json.dumps(events)


def test_validation_errors_and_unsupported_events_are_redacted():
    events = mod.RedactedEventList()
    events.append({"type": "tool_validation_error", "name": "query_metrics", "errors": [
        {"path": "$.message", "value": PRIVATE},
    ]})
    events.append({"type": "untyped", "payload": PRIVATE})
    events.append({"type": "tool_error", "error": PRIVATE})
    assert len(events) == 3
    assert PRIVATE not in json.dumps(events)
    assert events[0]["error_present"]


def test_product_transport_audit_does_not_record_raw_prompt():
    source = (ROOT / "validation" / "connection.py").read_text(encoding="utf-8")
    app = (ROOT / "validation" / "application.py").read_text(encoding="utf-8")
    assert "redact_payload=product_mode" in app
    assert 'record["input"] = body' in source
    assert "if self.redact_payload:" in source
    assert "request_sha256" in source
    assert "self.output.parent.chmod(0o700)" in source
    assert 'output = WORK / "diagnostics" if product_mode' in app
    assert "RedactedEventList(records)" in app


def test_electron_and_runtime_product_log_paths_stay_untracked():
    main = (ROOT / "validation" / "desktop" / "main.cjs").read_text()
    gitignore = (ROOT / ".gitignore").read_text()
    assert "BOSS_PRODUCT_UI" in main
    assert "path.join(work, 'diagnostics')" in main
    assert "validation/.work/" in gitignore
    assert ".work/" in gitignore
