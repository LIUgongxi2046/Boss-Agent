import json
import os
from importlib.metadata import version

from business import ROOT
from boss_v7_store import rows


def read_local_system(store, db):
    package = json.loads((ROOT / "desktop/package.json").read_text())
    scheduler = getattr(store, "scheduler_runtime", None)
    runtime = scheduler.snapshot() if scheduler is not None else None
    runs = rows(db, "runtime_run")
    active = [row for row in runs if row["status"] in {"QUEUED", "RUNNING", "WAITING_INPUT"} and row.get("finished_at") is None]
    recovery = [{"name": row["run_id"], "state": row["status"], "checked_at": row.get("finished_at"),
                 "details": "服务恢复时记录：" + row["stop_reason"]} for row in runs if row.get("stop_reason") == "service_restarted"]
    instructions = [
        {"id": "quit", "title": "完整退出", "body": "桌面菜单退出或关闭最后一个窗口会结束桌面应用及其所属后台服务；编辑内容和未知请求需要先完成保存或核查。",
         "command": None, "state": "DESKTOP_LIFECYCLE_IMPLEMENTED"},
        {"id": "restart", "title": "重启与恢复", "body": "使用当前实例的正式启动入口重新打开。账号和资料继续使用原实例目录；调度采用已保存的重启策略，进行中请求按正式运行记录核查。",
         "command": None, "state": "INSTANCE_LAUNCHER_REQUIRED"},
        {"id": "receipt", "title": "核查未知请求", "body": "在请求恢复页面查询原请求编号，再读取正式对象当前版本。未知结果核查不重新执行业务写入。",
         "command": None, "state": "ORIGINAL_REQUEST_LOOKUP_AVAILABLE"},
        {"id": "scope", "title": "当前外部能力", "body": "外部能力采用SIMULATED_FIRST，语音暂停。模拟内部通知与真实外部送达分别记录。",
         "command": None, "state": "SIMULATED_FIRST"},
    ]
    return {
        "application_version": package["version"], "upstream_version": version("nanobot-ai"),
        "source_commit": os.environ.get("BOSS_SOURCE_COMMIT", "NOT_RECORDED_FOR_RUNNING_INSTANCE"),
        "service": {"state": "SERVING_CURRENT_REQUEST" if hasattr(store, "service_started_at") else "SERVICE_CONTEXT_NOT_ATTACHED", "started_at": getattr(store, "service_started_at", None),
                    "scheduler_state": runtime["state"] if runtime else "NOT_ATTACHED", "scheduler_owner": "CronService" if runtime else "NOT_ATTACHED", "active_runs": len(active)},
        "desktop": {"background_mode": "DESKTOP_HOST_REPORT_REQUIRED", "auto_start": None, "auto_update": None, "recording_state": "PAUSED_BY_USER"},
        "recovery": recovery, "instructions": instructions,
        "installations": rows(db, "installation_check"), "backups": rows(db, "backup_record"),
        "contributions": [
            {"component": "nanobot", "version": version("nanobot-ai"), "source": "nanobot-ai 固定开源依赖",
             "extension": "复用AgentLoop、SessionManager、ClientProvider、WebSocket和CronService；业务授权与页面由项目接入"},
            {"component": "Desktop", "version": package["version"], "source": "Electron " + package["devDependencies"]["electron"],
             "extension": "桌面窗口、受控IPC、通知与所属服务生命周期"},
            {"component": "Knowledge", "version": "pypdf " + version("pypdf") + " / python-docx " + version("python-docx"),
             "source": "成熟文档解析库与SQLite FTS5", "extension": "获准来源摄取、版本、原文位置、有效期及撤销"},
        ],
    }
