from boss_page_api import BossPageAPI
from test_native import native, execute, read
from test_task_entry_consumer import create_task


def test_daily_question_returns_owner_decisions_and_saved_business_content(native):
    task = create_task(native, "owner-brief-real-task")
    _, dashboard = BossPageAPI(native[0]).serve("BOSS", "/api/boss/ui/dashboard")
    result, _ = execute(native, ["今天有哪些事情需要我决定、协调或知晓？按紧急程度说明原因。"])
    answer = result[0].content
    assert not result[0].error
    assert all(word in answer for word in ("需要决定", "需要协调", "需要知晓", "关注原因", "建议处理", "尚未执行"))
    assert all(item["title"] in answer for item in dashboard["today"]["items"])
    assert task["task_id"] not in answer
    assert "10月24日 17:00" in answer
    assert all(word not in answer for word in ("assignment_source_ids", "coordinator_id", "WAITING_FEEDBACK", "task_id=", "version="))
    runs = read(native, "runtime_run")
    assert runs[-1]["status"] == "SUCCEEDED"
    assert any(step["tool_id"] == "bossDashboardRead" for step in runs[-1]["tool_results"])
