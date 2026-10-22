"""A07 maintenance-driven synthetic knowledge source lifecycle.

Tests use explicitly supplied synthetic text, not real company information.
Only the boss can read the indexed original source; maintenance sees metadata.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))
from controls import ControlStore  # noqa: E402
from boss_command_api import BossCommandAPI  # noqa: E402
from boss_page_api import BossPageAPI  # noqa: E402


@pytest.fixture
def services(tmp_path):
    store = ControlStore(tmp_path / "knowledge.sqlite")
    store.initialize("ui-check")
    return BossCommandAPI(store), BossPageAPI(store)


def create_input(key="maintenance-doc-create", **overrides):
    return {
        "client_request_id": key,
        "source_id": "sim-doc-operational-review",
        "title": "合成技术资料（由维护录入）",
        "author_contact_id": "finance-1",
        "published_at": "2026-10-22",
        "content": "这是明确提供的模拟资料原始正文，用于核对技术知识摄取和来源版本，包含唯一短语蓝天对照号。",
        **overrides,
    }


def request(cmd, role, action, payload):
    return cmd.execute(role, action, payload)


def projection(api, role, page, query=""):
    return api.serve(role, "/api/boss/ui/workspace/" + page, query)


def test_technical_create_has_real_fts_and_owner_only_text_read(services):
    cmd, page = services
    status, result = request(
        cmd, "MAINTAINER", "boss.knowledge.source.create", create_input()
    )
    assert status == 200, result
    assert result["index_state"] == "INDEXED_CURRENT"
    assert result["source_type"] == "SIMULATED"
    assert result["version"] == "1"
    assert result["business_action_authorized"] is False
    assert result["content_recorded_in_receipt"] is False
    assert request(
        cmd, "MAINTAINER", "boss.knowledge.source.create", create_input()
    ) == (status, result)
    code, index = projection(page, "MAINTAINER", "source-index")
    assert code == 200
    metadata = next(x for x in index["sources"]
                    if x["source_id"] == "sim-doc-operational-review")
    assert metadata["index_state"] == "INDEXED_CURRENT"
    assert metadata["title"] == "合成技术资料（由维护录入）"
    assert metadata["version"] == "1"
    assert metadata["content_visible"] is False
    assert all("content" not in row for row in index["sources"])
    assert "蓝天对照号" not in json.dumps(index)
    assert "finance-1" in index["available_simulated_author_ids"]
    assert projection(page, "BOSS", "source-index")[0] == 403
    _, searched = projection(page, "BOSS", "knowledge", "q=%E8%93%9D%E5%A4%A9%E5%AF%B9%E7%85%A7%E5%8F%B7")
    assert any(x["source_id"] == "sim-doc-operational-review" for x in searched["results"])
    assert "蓝天对照号" in next(x for x in searched["results"]
                                 if x["source_id"] == "sim-doc-operational-review")["excerpt"]
    evidence_code, evidence = page.serve(
        "BOSS", "/api/boss/ui/evidence", "source=sim-doc-operational-review"
    )
    assert evidence_code == 200
    assert evidence["version"] == "1"
    assert evidence["content"]
    assert page.serve("MAINTAINER", "/api/boss/ui/evidence",
                      "source=sim-doc-operational-review")[0] == 403
    with cmd.store.connect() as db:
        indexed = db.execute(
            "SELECT content FROM knowledge WHERE namespace=? AND source_id=?",
            ("ui-check", "sim-doc-operational-review"),
        ).fetchone()
        assert indexed and "蓝天对照号" in indexed[0]
        audit = db.execute(
            "SELECT input, output FROM audit WHERE operation='boss.knowledge.source.create'"
        ).fetchall()
        assert len(audit) == 1
        assert "蓝天对照号" not in str(audit)


def test_revoking_document_removes_owner_search_but_preserves_history(services):
    cmd, page = services
    assert request(cmd, "MAINTAINER", "boss.knowledge.source.create",
                   create_input())[0] == 200
    revise = create_input(
        "maintenance-doc-revise",
        expected_version="1",
        title="模拟技术资料第二版",
        content="这是由技术维护输入的第二版模拟资料，更新检索词为清泉对照号，与旧材料区分，支持原文来源回溯。",
    )
    code, changed = request(cmd, "MAINTAINER", "boss.knowledge.source.revise", revise)
    assert code == 200, changed
    assert changed["version"] == "2"
    assert request(
        cmd, "MAINTAINER", "boss.knowledge.source.revise", revise
    ) == (code, changed)
    assert request(cmd, "MAINTAINER", "boss.knowledge.source.revise",
                   create_input("maintenance-stale-edit", expected_version="1"))[0] == 409
    _, old_search = projection(page, "BOSS", "knowledge", "q=%E8%93%9D%E5%A4%A9%E5%AF%B9%E7%85%A7%E5%8F%B7")
    assert not old_search["results"]
    _, new_search = projection(page, "BOSS", "knowledge", "q=%E6%B8%85%E6%B3%89%E5%AF%B9%E7%85%A7%E5%8F%B7")
    assert len(new_search["results"]) == 1
    assert new_search["results"][0]["version"] == "2"

    status, withdrawn = request(cmd, "MAINTAINER", "boss.knowledge.source.withdraw", {
        "client_request_id": "maintenance-doc-withdraw", "source_id": "sim-doc-operational-review",
        "expected_version": "2",
    })
    assert status == 200, withdrawn
    assert withdrawn["withdrawn"] is True
    assert withdrawn["version"] == "3"
    assert request(cmd, "MAINTAINER", "boss.knowledge.source.withdraw", {
        "client_request_id": "maintenance-doc-withdraw-2", "source_id": "sim-doc-operational-review",
        "expected_version": "2",
    })[0] == 409
    assert projection(page, "BOSS", "knowledge", "q=%E6%B8%85%E6%B3%89%E5%AF%B9%E7%85%A7%E5%8F%B7")[1]["results"] == []
    assert page.serve("BOSS", "/api/boss/ui/evidence",
                      "source=sim-doc-operational-review")[0] == 410
    _, index = projection(page, "MAINTAINER", "source-index")
    item = next(x for x in index["sources"] if x["source_id"] == "sim-doc-operational-review")
    assert item["withdrawn"] is True
    assert item["index_state"] == "WITHDRAWN"
    with cmd.store.connect() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM knowledge WHERE namespace=? AND source_id=?",
            ("ui-check", "sim-doc-operational-review"),
        ).fetchone()[0] == 0
        assert db.execute(
            "SELECT COUNT(*) FROM objects WHERE kind='document_revision'",
        ).fetchone()[0] == 2


@pytest.mark.parametrize(("key", "change", "status"), [
    ("unknown-prefix", {"source_id": "finance-note"}, 400),
    ("bad-source-id", {"source_id": "sim-doc-../../escape"}, 400),
    ("bad-author", {"author_contact_id": "outside-organization"}, 400),
    ("invalid-date", {"published_at": "2026-02-30"}, 400),
    ("empty-text", {"content": "short"}, 400),
    ("contains-secret", {"content": "合成资料，不应保存 " + "sk-" + "x"*39 + " 这种凭据字符串。"}, 400),
    ("injected-owner", {"owner_id": "other-owner"}, 400),
    ("injected-scope", {"source_type": "PUBLIC_SOURCE"}, 400),
])
def test_invalid_maintenance_ingest_never_mutates(services, key, change, status):
    cmd, _ = services
    payload = create_input(key, **change)
    code, _ = request(cmd, "MAINTAINER", "boss.knowledge.source.create", payload)
    assert code == status
    with cmd.store.connect() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM objects WHERE kind='document' AND id LIKE 'sim-doc-%'",
        ).fetchone()[0] == 0
        assert db.execute(
            "SELECT COUNT(*) FROM objects WHERE kind='document_revision'",
        ).fetchone()[0] == 0


def test_maintainer_cannot_modify_fixture_source_or_impersonate_boss(services):
    cmd, page = services
    assert request(cmd, "BOSS", "boss.knowledge.source.create", create_input())[0] == 403
    assert request(cmd, None, "boss.knowledge.source.create", create_input())[0] == 401
    assert request(cmd, "MAINTAINER", "boss.knowledge.source.withdraw", {
        "client_request_id": "attempt-initial-source",
        "source_id": "finance-note", "expected_version": "1",
    })[0] == 400
    assert request(cmd, "MAINTAINER", "boss.knowledge.source.revise",
                   create_input("revise-not-yet", expected_version="1"))[0] == 404
    code, metadata = projection(page, "MAINTAINER", "source-index")
    assert code == 200
    assert all("content" not in row for row in metadata["sources"])


def test_same_key_rejected_if_content_changed(services):
    cmd, _ = services
    first = request(cmd, "MAINTAINER", "boss.knowledge.source.create", create_input())
    assert first[0] == 200
    altered = create_input(content="不同的模拟内容。" * 12)
    assert request(cmd, "MAINTAINER", "boss.knowledge.source.create", altered)[0] == 409


def test_simulated_author_is_not_granted_business_identity(services):
    cmd, page = services
    assert request(cmd, "MAINTAINER", "boss.knowledge.source.create",
                   create_input())[0] == 200
    body = projection(page, "MAINTAINER", "source-index")[1]
    assert body["external_ingestion_performed"] is False
    assert not any(x.get("access_scope") == "PUBLIC" for x in body["sources"])
    assert projection(page, "MAINTAINER", "calendar")[0] == 403
    assert projection(page, "MAINTAINER", "memory")[0] == 403
    assert page.serve("MAINTAINER", "/api/boss/ui/evidence",
                      "source=sim-doc-operational-review")[0] == 403
