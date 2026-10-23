"""A05 Prompt lifecycle: actual runtime context-use evidence and role isolation.

The selected prompt may be loaded into a real nanobot RuntimeContextBlock,
but loading alone never claims the model returned an answer or passed an eval.
All assertions use synthetic SQLite, not the real user DeepSeek credential.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"validation"))
from boss_command_api import BossCommandAPI
from boss_page_api import BossPageAPI
from boss_prompt_config import active_runtime_prompts,record_runtime_context_load
from controls import ControlStore


@pytest.fixture
def service(tmp_path):
    store=ControlStore(tmp_path/"prompt-context.sqlite")
    store.initialize("ui-check")
    return BossCommandAPI(store),BossPageAPI(store)


def call(api,role,action,key,**params):
    return api.execute(role,action,{"client_request_id":key,**params})


def catalog(reads,role="MAINTAINER"):
    return reads.serve(role,"/api/boss/ui/workspace/prompt-versions")


def setup_active(service):
    api,reads=service
    saved=call(api,"MAINTAINER","boss.prompt.save","prompt-new-01",
        prompt_id=None,expected_version="0",
        kind="SECRETARY_ROLE",title="合成的秘书职责指引",
        instruction_text="仅对当前获准的模拟业务资料提供有来源的阅读说明；不修改任何老板授权，也不自行发送消息。",
        change_note="检查技术提示在下一会话的加载记录",
        source_ids=["finance-note"])
    assert saved[0]==200,saved
    item=saved[1]
    checked=call(api,"MAINTAINER","boss.prompt.validate","prompt-check-01",
        prompt_id=item["prompt_id"],expected_version=item["version"],
        expected_content_sha256=item["content_sha256"])
    assert checked[0]==200,checked
    activated=call(api,"MAINTAINER","boss.prompt.activate","prompt-enable-01",
        prompt_id=item["prompt_id"],expected_version=checked[1]["version"],
        expected_content_sha256=item["content_sha256"],
        expected_active_version="0")
    assert activated[0]==200,activated
    return item,checked[1],activated[1]


def test_real_context_load_count_is_not_claimed_at_activation(service):
    api,reads=service
    _,_,activated=setup_active(service)
    code,initial=catalog(reads)
    assert code==200
    assert initial["active"][0]["runtime_context_adoption"]=="NOT_OBSERVED"
    assert initial["active"][0]["context_load_count"]==0
    assert initial["active"][0]["last_context_at"] is None
    assert initial["model_evaluation_completed"] is False
    prompt=active_runtime_prompts(api.store,"ui-check")
    assert len(prompt)==1
    assert prompt[0]["prompt_id"]==activated["prompt_id"]
    # The same callback called by validation/application.py is directly checked.
    record_runtime_context_load(api.store,prompt)
    after=catalog(reads)[1]["active"][0]
    assert after["runtime_context_adoption"]=="RUNTIME_CONTEXT_PROVIDER_INVOKED"
    assert after["context_load_count"]==1
    assert after["last_context_at"]
    assert after["actual_model_evaluation_passed"] is False
    with api.store.connect() as db:
        record=db.execute("SELECT body FROM objects WHERE kind='prompt_context_use'").fetchone()
        assert record
        assert "instruction_text" not in record[0]
        assert "仅对当前获准" not in record[0]
    record_runtime_context_load(api.store,prompt)
    assert catalog(reads)[1]["active"][0]["context_load_count"]==2


def test_technical_prompt_cannot_grant_owner_authorizations(service):
    api,reads=service
    saved,checked,activated=setup_active(service)
    assert call(api,"BOSS","boss.prompt.deactivate","owner-off-001",
        kind="SECRETARY_ROLE",expected_active_version="1")[0]==403
    assert catalog(reads,"BOSS")[0]==403
    with api.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='authorization'").fetchone()[0]==0
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='task'").fetchone()[0]==0


def test_context_records_are_only_for_live_active_version(service):
    api,reads=service
    item,checked,activated=setup_active(service)
    selected=active_runtime_prompts(api.store,"ui-check")
    old=call(api,"MAINTAINER","boss.prompt.deactivate","prompt-deactivate-01",
        kind="SECRETARY_ROLE",expected_active_version="1")
    assert old[0]==200,old
    assert active_runtime_prompts(api.store,"ui-check")==[]
    # A turn which read a prompt just before deactivation cannot falsely
    # record adoption after the active pointer changed.
    record_runtime_context_load(api.store,selected)
    record=catalog(reads)[1]["active"][0]
    assert record["enabled"] is False
    assert record["runtime_context_adoption"]=="NOT_OBSERVED"
    assert record["context_load_count"]==0


def test_replaced_source_blocks_next_turn_context_adoption(service):
    api,reads=service
    setup_active(service)
    first=active_runtime_prompts(api.store,"ui-check")
    assert len(first)==1
    withdrawn=api.store.control("ui-check","withdraw",
        {"source_id":"finance-note","version":"1"})
    assert withdrawn["withdrawn"]
    assert active_runtime_prompts(api.store,"ui-check")==[]
    assert catalog(reads)[1]["adoptable_current_ids"]==[]
    record_runtime_context_load(api.store,[])
    assert catalog(reads)[1]["active"][0]["context_load_count"]==0


def test_source_withdrawal_between_selection_and_recording(service):
    api, reads = service
    setup_active(service)
    selected = active_runtime_prompts(api.store)
    api.store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    record_runtime_context_load(api.store, selected)
    assert catalog(reads)[1]["active"][0]["context_load_count"] == 0


def test_prompt_selection_is_scoped_to_execution_namespace(service):
    api, reads = service
    setup_active(service)
    api.store.initialize("independent-runtime")
    assert active_runtime_prompts(api.store, "independent-runtime") == []


def test_atomic_context_selection_survives_database_reopen(service):
    from boss_prompt_config import load_runtime_prompts

    api, reads = service
    item, checked, activated = setup_active(service)
    selected = load_runtime_prompts(api.store)
    assert selected[0]["prompt_id"] == item["prompt_id"]
    reopened = ControlStore(api.store.path)
    assert catalog(BossPageAPI(reopened))[1]["active"][0]["context_load_count"] == 1
    reopened.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    assert load_runtime_prompts(reopened) == []
    assert catalog(reads)[1]["active"][0]["context_load_count"] == 1


def test_duplicate_or_stale_context_record_not_exposed_to_business_owner(service):
    api,reads=service
    setup_active(service)
    record_runtime_context_load(api.store,active_runtime_prompts(api.store))
    assert catalog(reads)[0]==200
    for route in ("system","source-index","audit"):
        status,content=reads.serve("MAINTAINER","/api/boss/ui/workspace/"+route)
        assert status==200
        assert "instruction_text" not in json.dumps(content)
    for route in ("knowledge","memory","minutes","calendar","outbox"):
        status,content=reads.serve("BOSS","/api/boss/ui/workspace/"+route)
        assert status==200
        assert "context_load_count" not in json.dumps(content)
        assert "合成的秘书职责指引" not in json.dumps(content)


def test_actual_runtime_hook_uses_version_selection_and_records_metadata_only():
    source=(ROOT/"validation/application.py").read_text()
    assert 'load_runtime_prompts(store, "ui-check")' in source
    assert 'source="boss-confirmed-memory"' in source
    assert "guidance_authority_boundary" in source
    assert "technical prompts do not grant" in source.lower() or "Technical prompts do not grant" in source



def test_a05_version_diff_reads_persisted_revision_only_for_maintainer(service):
    api,reads=service
    item,checked,activated=setup_active(service)
    current=catalog(reads)[1]["drafts"][0]
    original_text=current["instruction_text"]
    saved=call(api,"MAINTAINER","boss.prompt.save","prompt-rewrite-01",
        prompt_id=item["prompt_id"],expected_version=checked["version"],
        kind="SECRETARY_ROLE",title="更新秘书职责",
        instruction_text="新版本：仅显示有出处的模拟材料，缺失信息保持未知；所有业务执行仍须BOSS当前指令。",
        change_note="修改与来源核对有关的表达限制",
        source_ids=["finance-note"])
    assert saved[0]==200,saved
    status,result=catalog(reads)
    assert status==200
    assert len(result["revisions"])>=2
    history=[x for x in result["revisions"] if x["prompt_id"]==item["prompt_id"]]
    assert {row["version"] for row in history}>={"1","2"}
    assert any(row["instruction_text"]==original_text for row in history)
    assert result["drafts"][0]["instruction_text"]!=original_text
    assert catalog(reads,"BOSS")[0]==403
    assert "instruction_text" not in str(reads.serve(
        "MAINTAINER","/api/boss/ui/workspace/system")[1])
    assert "instruction_text" not in str(reads.serve(
        "BOSS","/api/boss/ui/workspace/memory")[1])


def test_a05_frontend_uses_real_technical_payload_and_diff_only():
    page=(ROOT/"app/webui/MaintainerPromptVersion.tsx").read_text(encoding="utf-8")
    mapping=__import__("json").loads((ROOT/"specs/page-service-map.json").read_text(encoding="utf-8"))
    match=next(x for x in mapping["pages"] if x["page_id"]=="A05")
    assert match["component_file"]=="app/webui/MaintainerPromptVersion.tsx"
    assert set(match["code_wired_write_actions"])=={
        "boss.prompt.save","boss.prompt.validate",
        "boss.prompt.activate","boss.prompt.deactivate"
    }
    assert match["actual_e2e_verified"] is False
    for text in ("prompt-versions","client.requestMutation","content_sha256",
                 "revisions","removedLines","addedLines","runtime_context_adoption"):
        assert text in page
    assert "window.confirm" not in page
    assert "boss-a05-discard-title" in page
