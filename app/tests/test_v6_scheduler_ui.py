"""Static A13 v6 integration assertions; visual acceptance still requires Mac."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_a13_real_technical_workflow_and_permissions():
    mapping=json.loads((ROOT/"specs/page-service-map.json").read_text(encoding="utf-8"))
    page=next(row for row in mapping["pages"] if row["page_id"]=="A13")
    assert page["role_gate"]=="MAINTAINER"
    assert page["component_file"]=="app/webui/MaintainerScheduler.tsx"
    assert page["actual_e2e_verified"] is False
    assert page["visual_pixel_verified"] is False
    assert page["manual_dispatch_verified"] is False
    assert page["real_cron_runtime_verified"] is False
    assert set(page["code_wired_write_actions"])=={
        "boss.scheduler.draft.save", "boss.scheduler.draft.validate",
        "boss.scheduler.activate","boss.scheduler.pause","boss.scheduler.resume",
        "boss.scheduler.cancel","boss.scheduler.manual_run",
    }


def test_a13_uses_auth_mutation_and_real_backend_views_without_fake_success():
    ui=(ROOT/"app/webui/MaintainerScheduler.tsx").read_text()
    gateway=(ROOT/"validation/boss_command_api.py").read_text()
    backend=(ROOT/"validation/boss_scheduler_config.py").read_text()
    controls=(ROOT/"validation/controls.py").read_text()
    shell=(ROOT/"app/webui/BossDesktop.tsx").read_text()
    overlay=(ROOT/"scripts/prepare_boss_webui.py").read_text()
    for token in (
        'client.requestMutation', '/api/boss/ui/workspace/scheduler',
        '/api/boss/ui/operation-status', 'boss.scheduler.draft.save',
        'boss.scheduler.draft.validate','boss.scheduler.activate',
        'boss.scheduler.pause','boss.scheduler.resume',
        'boss.scheduler.cancel','boss.scheduler.manual_run',
        'NEXT_RUN_TIME' if False else 'next_run_time',
        'manual_dispatch_supported_here',
    ):
        assert token in ui
    assert '"boss.scheduler.manual_run": "MAINTAINER"' in gateway
    assert 'dispatch_due_in_transaction(' in backend
    assert 'return self.dispatch_due_in_transaction(db, ns)' in controls
    assert 'BossMinutesAssignmentActions' not in ui
    assert "MaintainerScheduler" in shell
    assert "MaintainerScheduler.tsx" in overlay
    assert "dangerouslySetInnerHTML" not in ui
    assert "localStorage" not in ui
