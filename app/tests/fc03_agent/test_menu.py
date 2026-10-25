from dataclasses import replace
import json

import pytest
from aiohttp import web
from nanobot.providers.base import LLMResponse

from test_formal import formal, call, event
from test_agent import scope, run
from business import encode
from boss_runtime_records import runtime_records


@pytest.fixture
def selected(formal):
    view = call(formal, "todayRead", json.loads(formal[1][0].read_parameters_json))
    item = view["items"][-1]
    assert len(view["items"]) > 1
    assert item["item_id"] != view["items"][0]["item_id"]
    formal[1][0] = replace(formal[1][0], client_request_id="menu-discussion-request",
        allowed_list_ids=frozenset({view["list_id"]}), selected_list_id=view["list_id"], selected_item_id=item["item_id"])
    return formal, view, item


@pytest.fixture
def sourced(formal):
    view = call(formal, "todayRead", json.loads(formal[1][0].read_parameters_json))
    item = next(candidate for candidate in view["items"]
        if any(reference["kind"] == "document" for reference in candidate["source_refs"]))
    formal[1][0] = replace(formal[1][0], client_request_id="menu-source-discussion",
        allowed_list_ids=frozenset({view["list_id"]}), selected_list_id=view["list_id"], selected_item_id=item["item_id"])
    return formal, view, item


def test_selected_item_enters_actual_runtime_and_uses_same_detail(selected, tmp_path):
    formal, view, item = selected
    observed = []
    question = "继续讨论当前事项，说明需要本人处理的原因与依据"
    async def producer(messages, tools):
        assert any(message["role"] == "user" and question in str(message["content"]) for message in messages)
        assert any(item["item_id"] in str(message["content"]) and "selected_item_ref" in str(message["content"]) for message in messages)
        outputs = [json.loads(message["content"]) for message in messages if message["role"] == "tool"]
        if not outputs:
            return event("morningDetailRead", {"list_id": view["list_id"], "item_id": item["item_id"]})
        observed[:] = outputs
        return LLMResponse(content=encode({"source_type": "SIMULATED", "item": outputs[0]["item"]}))
    result = run(formal, tmp_path, producer, formal=True, question=question)
    assert not result.error and observed[0]["item"] == item
    row = runtime_records(formal[0], "MAINTAINER")["runs"][0]
    reference = row["morning_context"]["selected_item_ref"]
    assert reference == {"list_id": view["list_id"], "list_version": view["list_version"],
        **{key: item[key] for key in ("item_id", "object_id", "version", "source_refs")}}
    assert row["tool_results"][0]["item_refs"][0]["item_id"] == reference["item_id"]
    assert item["title"] not in json.dumps(row, ensure_ascii=False)
    assert question not in json.dumps(row, ensure_ascii=False)
    assert row["usage"] is row["cost_total"] is None


def test_selected_discussion_cannot_read_other_item_or_create_list(selected):
    formal, view, item = selected
    other = next(candidate for candidate in view["items"] if candidate["item_id"] != item["item_id"])
    with pytest.raises(web.HTTPForbidden):
        call(formal, "morningDetailRead", {"list_id": view["list_id"], "item_id": other["item_id"]})
    with pytest.raises(web.HTTPForbidden):
        call(formal, "todayRead", json.loads(formal[1][0].read_parameters_json))
    with formal[0].connect() as db:
        assert db.execute("SELECT count(*) FROM objects WHERE kind='morning_list'").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM objects WHERE kind IN ('authorization','outbox','today_order')").fetchone()[0] == 0


def test_selected_source_revocation_stops_current_adoption(sourced):
    formal, view, item = sourced
    source = next(reference for reference in item["source_refs"] if reference["kind"] == "document")
    formal[0].control("ui-check", "withdraw", {"source_id": source["id"], "version": source["version"]})
    with pytest.raises(web.HTTPException):
        call(formal, "morningDetailRead", {"list_id": view["list_id"], "item_id": item["item_id"]})


@pytest.mark.parametrize("list_id,item_id", [(None, "missing-item"), ("missing-list", None)])
def test_partial_selection_is_rejected_before_tool_execution(formal, list_id, item_id):
    formal[1][0] = replace(formal[1][0], selected_list_id=list_id, selected_item_id=item_id)
    with pytest.raises(web.HTTPForbidden):
        call(formal, "todayRead", json.loads(formal[1][0].read_parameters_json))


def test_selected_source_matches_current_document(sourced):
    formal, view, item = sourced
    source = next(reference for reference in item["source_refs"] if reference["kind"] == "document")
    result = call(formal, "morningSourceRead", {"list_id": view["list_id"], "source_id": source["id"]})
    assert result["document"]["source_id"] == source["id"]
    assert result["document"]["version"] == source["version"]


def test_selected_item_rejects_unrelated_source(selected):
    from boss_command_api import BossCommandAPI
    from boss_page_api import BossPageAPI

    formal, view, item = selected
    # Create an independently readable, current simulated source through the
    # same approved MAINTAINER path used by the product. The fixture's existing
    # sources can all belong to the selected item; never rely on an accidental
    # second document or silently skip this authorization check.
    unrelated_id = "sim-doc-f01-unrelated"
    status, created = BossCommandAPI(formal[0]).execute("MAINTAINER", "boss.knowledge.source.create", {
        "client_request_id": "f01-unrelated-source-creation",
        "source_id": unrelated_id,
        "title": "用于晨间来源授权检查的独立模拟资料",
        "author_contact_id": "finance-1",
        "published_at": "2026-10-22",
        "content": "仅用于隔离测试的模拟运营参考资料，不对应当前选中事项，不得由绑定该事项的Agent读取。",
    })
    assert status == 200, created
    assert created["index_state"] == "INDEXED_CURRENT"
    assert BossPageAPI(formal[0]).serve("BOSS", "/api/boss/ui/evidence", "source=" + unrelated_id)[0] == 200
    permitted = {reference["id"] for reference in item["source_refs"] if reference["kind"] == "document"}
    assert unrelated_id not in permitted
    with pytest.raises(web.HTTPForbidden):
        call(formal, "morningSourceRead", {"list_id": view["list_id"], "source_id": unrelated_id})
