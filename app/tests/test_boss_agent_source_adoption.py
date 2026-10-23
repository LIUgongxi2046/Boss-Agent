import asyncio
import copy
import json
import sys
from pathlib import Path

import pytest
from aiohttp import web

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from controls import ControlStore
from model_probe import BusinessTool


@pytest.fixture
def source_case(tmp_path):
    store = ControlStore(tmp_path / "tool-source.sqlite")
    store.initialize("ui-check")
    events = json.loads(next((ROOT / "evidence/T16").glob("deepseek-*/events.json")).read_text())
    query = copy.deepcopy(next(row["input"] for row in events if row["type"] == "tool" and row["name"] == "query_metrics"))
    query["envelope"]["execution_namespace"] = "ui-check"
    result = store.invoke("query_metrics", query)
    return store, query, result


@pytest.mark.parametrize("operation", ["query_metrics", "read_evidence"])
def test_model_tool_uses_current_query_and_rejects_stale_evidence_binding(source_case, operation):
    store, query, result = source_case
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", "finance-note")
        store.put(db, "ui-check", "document", "finance-note", {**document, "version": "2"})
    tool = BusinessTool(operation, store, query["envelope"], {}, [])
    params = ({key: value for key, value in query.items() if key != "envelope"} if operation == "query_metrics" else {
        "query_id": result["query_id"], "source_ids": ["finance-note"], "detail_refs": result["detail_refs"],
    })
    if operation == "query_metrics":
        current = json.loads(asyncio.run(tool.execute(**params)))
        assert current["sources"][0]["version"] == "2"
        assert current["query_id"] != result["query_id"]
    else:
        with pytest.raises(web.HTTPConflict):
            asyncio.run(tool.execute(**params))


@pytest.mark.parametrize("state,error", [("EXPIRED", web.HTTPGone), ("CONFLICTED", web.HTTPConflict),
                                        ("SUPERSEDED", web.HTTPConflict), ("RECEIVED", web.HTTPConflict)])
def test_model_metric_tool_rejects_ineligible_current_source(source_case, state, error):
    store, query, _ = source_case
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", "finance-note")
        store.put(db, "ui-check", "document", "finance-note", {**document, "validity_state": state})
    tool = BusinessTool("query_metrics", store, query["envelope"], {}, [])
    with pytest.raises(error):
        asyncio.run(tool.execute(**{key: value for key, value in query.items() if key != "envelope"}))
