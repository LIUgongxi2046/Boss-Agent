import json
from pathlib import Path
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt
import yaml

from hermes_domain_schema import FIELDS, MEETING_DRAFT_FIELDS, MINUTES_DRAFT_FIELDS


ROOT = Path(__file__).resolve().parents[2]
DOCUMENT = ROOT / "docs/升级2.0运行与接口说明.md"


def test_runtime_document_links_and_domain_fields():
    text = DOCUMENT.read_text(encoding="utf-8")
    tokens = MarkdownIt().parse(text)
    links = [child.attrGet("href") for token in tokens for child in token.children or [] if child.type == "link_open"]
    assert links
    for href in links:
        target = urlsplit(href)
        if not target.scheme and target.path:
            assert (DOCUMENT.parent / unquote(target.path)).is_file(), href
    for action, fields in FIELDS.items():
        row = next(line for line in text.splitlines() if line.startswith("| `" + action + "` |"))
        assert all("`" + field + "`" in row for field in fields)
    assert all("`" + field + "`" in text for field in MEETING_DRAFT_FIELDS | MINUTES_DRAFT_FIELDS)


def test_runtime_document_routes_and_schemas():
    text = DOCUMENT.read_text(encoding="utf-8")
    routes = {
        "validation/agent_run_resume_routes.py": ["/api/v2/runs/{run_id}/resume", "/api/v2/runs/{run_id}/resume-status", "/api/v2/runs/{run_id}/resume-requests/{request_key}"],
        "validation/agent_source_history_routes.py": ["/api/v2/runs/{run_id}/source-history/{event_id}"],
        "validation/agent_artifact_source_history_routes.py": ["/api/v2/runs/{run_id}/artifacts/{artifact_id}/source-history"],
        "validation/hermes_transport.py": ["/internal/v1/tools/meeting-context", "/internal/v1/tools/meeting-draft", "/internal/v1/tools/minutes-context", "/internal/v1/tools/minutes-draft", "/internal/v1/tools/domain-intent"],
    }
    for source, paths in routes.items():
        implementation = (ROOT / source).read_text(encoding="utf-8")
        for path in paths:
            assert path in implementation
            assert path in text
    schemas = [ROOT / "validation/agent_run_resume_schema.json", ROOT / "validation/agent_source_history_schema.json", ROOT / "validation/agent_artifact_source_history_schema.json"]
    for path in schemas:
        schema = json.loads(path.read_text(encoding="utf-8"))
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert path.name in text
    for state in ("NOT_VERIFIED", "SERVICE_NOT_READY", "NOT_RUN", "BLOCKED"):
        assert state in text


def test_openapi_history_routes_match_schemas():
    specification = yaml.safe_load((ROOT / "specs/agent-runtime.openapi.yaml").read_text(encoding="utf-8"))
    assert {"ProductBearer": []} in specification["security"]
    expected = {
        "/api/v2/runs/{run_id}/source-history/{event_id}": ({"run_id", "event_id", "source_id", "version"}, "../validation/agent_source_history_schema.json"),
        "/api/v2/runs/{run_id}/artifacts/{artifact_id}/source-history": ({"run_id", "artifact_id", "source_id", "version", "artifact_version"}, "../validation/agent_artifact_source_history_schema.json"),
    }
    for path, (parameters, schema_ref) in expected.items():
        entry = specification["paths"][path]
        assert {item["name"] for item in entry["parameters"]} == parameters
        assert all(item["required"] for item in entry["parameters"])
        response = entry["get"]["responses"]
        assert {"200", "400", "401", "403", "404", "409", "410"} <= set(response)
        assert response["200"]["content"]["application/json"]["schema"]["$ref"] == schema_ref
        assert (ROOT / "specs" / schema_ref).is_file()


def test_openapi_resume_routes_match_schemas():
    specification = yaml.safe_load((ROOT / "specs/agent-runtime.openapi.yaml").read_text(encoding="utf-8"))
    schema = json.loads((ROOT / "validation/agent_run_resume_schema.json").read_text(encoding="utf-8"))
    assert {"ProductBearer": []} in specification["security"]
    base = "/api/v2/runs/{run_id}/"
    expected = {
        "resume-status": ("get", {"run_id"}, "status"),
        "resume": ("post", {"run_id"}, "receipt"),
        "resume-requests/{request_key}": ("get", {"run_id", "request_key"}, "request_receipt"),
    }
    for suffix, (method, names, definition) in expected.items():
        entry = specification["paths"][base + suffix]
        assert {item["name"] for item in entry["parameters"]} == names
        assert all(item["required"] and item["in"] == "path" for item in entry["parameters"])
        operation = entry[method]
        assert {"200", "400", "401", "403", "404", "409"} <= set(operation["responses"])
        assert operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"] == "../validation/agent_run_resume_schema.json#/$defs/" + definition
        assert definition in schema["$defs"]
    post = specification["paths"][base + "resume"]["post"]
    assert {"413", "503"} <= set(post["responses"])
    assert post["requestBody"]["content"]["application/json"]["schema"]["$ref"] == "../validation/agent_run_resume_schema.json#/$defs/request"
    assert set(schema["$defs"]["request"]["required"]) == {"expected_revision", "expected_goal_revision", "request_key"}
    assert schema["$defs"]["status"]["properties"]["allowed_actions"]["maxItems"] == 0


def test_openapi_method_routes_and_waiting_input_match_source():
    specification = yaml.safe_load((ROOT / "specs/agent-runtime.openapi.yaml").read_text(encoding="utf-8"))
    schema = json.loads((ROOT / "specs/agent-runs.schema.json").read_text(encoding="utf-8"))["$defs"]
    implementation = (ROOT / "validation/agent_run_api.py").read_text(encoding="utf-8")
    document = DOCUMENT.read_text(encoding="utf-8")
    base = "/api/v2/runs/{run_id}/"
    expected = {
        "available-methods": ("get", {"run_id"}, "method_catalog"),
        "method-selection": ("post", {"run_id"}, "method_reselection_receipt"),
        "method-selection/requests/{request_key}": ("get", {"run_id", "request_key"}, "method_reselection_receipt"),
    }
    for suffix, (method, names, definition) in expected.items():
        path = base + suffix
        assert path in implementation and path in document
        entry = specification["paths"][path]
        assert {item["name"] for item in entry["parameters"]} == names
        assert all(item["required"] and item["in"] == "path" for item in entry["parameters"])
        operation = entry[method]
        assert {"200", "400", "401", "403", "404", "409", "503"} <= set(operation["responses"])
        assert operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"] == "./agent-runs.schema.json#/$defs/" + definition
        assert definition in schema
    post = specification["paths"][base + "method-selection"]["post"]
    assert "413" in post["responses"]
    assert post["requestBody"]["content"]["application/json"]["schema"]["$ref"] == "./agent-runs.schema.json#/$defs/method_reselection"
    assert set(schema["method_reselection"]["required"]) == {"expected_goal_revision", "request_key", "method_selection"}
    assert set(schema["method_catalog"]["required"]) == {"run_id", "goal_revision", "selection_allowed", "methods"}
    assert set(schema["snapshot"]["properties"]["waiting_input"]["required"]) == {"event_id", "goal_revision", "question"}
    assert "SELECT_METHOD" in schema["snapshot"]["properties"]["allowed_actions"]["items"]["enum"]
    for field in schema["method_catalog"]["properties"]["methods"]["items"]["required"]:
        assert "`" + field + "`" in document


def test_openapi_object_scope_routes_match_schema_and_source():
    specification = yaml.safe_load((ROOT / "specs/agent-runtime.openapi.yaml").read_text(encoding="utf-8"))
    schema = json.loads((ROOT / "specs/agent-runs.schema.json").read_text(encoding="utf-8"))["$defs"]
    implementation = (ROOT / "validation/agent_run_api.py").read_text(encoding="utf-8")
    document = DOCUMENT.read_text(encoding="utf-8")
    base = "/api/v2/runs/{run_id}/object-scope"
    expected = {
        "": ("post", {"run_id"}, "object_scope_receipt"),
        "/candidates": ("get", {"run_id"}, "object_scope_candidates"),
        "/meeting-candidates/{meeting_id}": ("get", {"run_id", "meeting_id"}, "object_scope_candidates"),
        "/requests/{request_key}": ("get", {"run_id", "request_key"}, "object_scope_receipt"),
    }
    assert {"ProductBearer": []} in specification["security"]
    for suffix, (method, names, definition) in expected.items():
        path = base + suffix
        assert path in implementation and path in document
        entry = specification["paths"][path]
        assert {item["name"] for item in entry["parameters"]} == names
        assert all(item["required"] and item["in"] == "path" for item in entry["parameters"])
        operation = entry[method]
        assert {"200", "400", "401", "403", "404", "409", "503"} <= set(operation["responses"])
        assert operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"] == "./agent-runs.schema.json#/$defs/" + definition
    post = specification["paths"][base]["post"]
    assert "413" in post["responses"]
    assert post["requestBody"]["content"]["application/json"]["schema"]["$ref"] == "./agent-runs.schema.json#/$defs/object_scope_request"
    assert set(schema["object_scope_request"]["required"]) == {"expected_goal_revision", "request_key", "objects"}
    assert set(schema["object_scope_candidates"]["required"]) == {"run_id", "goal_revision", "selection_allowed", "unavailable_reasons", "objects"}
    assert set(schema["object_scope_receipt"]["required"]) == {"run_id", "goal_revision", "request_key", "objects"}
    for reason in schema["object_scope_candidates"]["properties"]["unavailable_reasons"]["items"]["enum"]:
        assert "`" + reason + "`" in document
    assert "inspect_completion_in_transaction" in (ROOT / "validation/hermes_transport.py").read_text(encoding="utf-8")
    assert "`POST /internal/v1/events`" in document and "`BLOCKED`" in document
