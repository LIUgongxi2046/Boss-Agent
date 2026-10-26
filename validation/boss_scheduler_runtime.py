from datetime import datetime, timezone

from nanobot.cron.types import CronJob, CronPayload, CronSchedule

from business import checksum, encode, now, require
from boss_scheduler_config import plan_fields
from boss_v7_store import NAMESPACE, rows

CONTROL_ID = "boss-scheduler-control"
TIME_ID = "boss-scheduler-time"


class BossSchedulerRuntime:
    def __init__(self, store, cron):
        self.store, self.cron = store, cron
        self.version = None
        self.event_fingerprint = None
        self.started_at = None
        self.checked_at = None
        self.running_count = 0
        self.enabled = False
        self.trigger = None

    def start(self):
        require(self.started_at is None, "当前调度责任组件已经启动")
        for job in self.cron.list_jobs(include_disabled=True):
            if job.name == "boss-events":
                self.cron.remove_system_job(job.id)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.store.active(db, NAMESPACE)
            schedule = self.store.get(db, NAMESPACE, "schedule", "current")
            if plan_fields(schedule)["restart_policy"] == "PAUSE_ON_RESTART" and schedule["enabled"] and not schedule["canceled"]:
                schedule.update(enabled=False, version=str(int(schedule["version"]) + 1),
                                schedule_version=str(int(schedule["schedule_version"]) + 1), last_configured_at=now())
                self.store.put(db, NAMESPACE, "schedule", "current", schedule)
                db.execute("INSERT INTO audit(namespace,operation,input,output,created_at) VALUES(?,?,?,?,?)",
                           (NAMESPACE, "scheduler.restart.pause", encode({"policy": "PAUSE_ON_RESTART"}), encode({"schedule_version": schedule["version"]}), now()))
        self.started_at = now()
        self.reconcile()
        self.event_fingerprint = None
        self.cron.register_system_job(CronJob(id=CONTROL_ID, name="boss-scheduler-control",
            schedule=CronSchedule(kind="every", every_ms=500), payload=CronPayload(kind="system_event", message="核查当前调度配置和获准事件")))

    def reconcile(self):
        from boss_v7_metrics import policy_fingerprint
        with self.store.connect() as db:
            db.execute("BEGIN")
            self.store.active(db, NAMESPACE)
            schedule = self.store.get(db, NAMESPACE, "schedule", "current")
            fingerprint = checksum({"events": rows(db, "event"), "clock": self.store.get(db, NAMESPACE, "clock", "current"),
                                    "schedule": schedule, "rules": rows(db, "rules"), "reminders": rows(db, "reminder"),
                                    "business_rules": rows(db, "business_alert_rule"), "metric_policy_sha256": policy_fingerprint(db, NAMESPACE)})
        self.enabled = schedule["enabled"] and not schedule["canceled"]
        self.trigger = schedule["trigger"]
        if self.version != schedule["version"]:
            self.cron.remove_system_job(TIME_ID)
            if self.enabled and schedule["trigger"] in {"CRON", "EVENT_OR_TIME"}:
                plan = plan_fields(schedule)
                self.cron.register_system_job(CronJob(id=TIME_ID, name=plan["name"],
                    schedule=CronSchedule(kind="cron", expr=plan["expression"], tz=schedule["timezone"]),
                    payload=CronPayload(kind="system_event", message="按当前计划检查获准事项")))
            self.version = schedule["version"]
            self.event_fingerprint = None
        self.checked_at = now()
        changed = fingerprint != self.event_fingerprint
        self.event_fingerprint = fingerprint
        return changed and self.enabled and schedule["trigger"] in {"EVENT", "EVENT_OR_TIME"}

    async def on_job(self, job):
        require(job.id in {CONTROL_ID, TIME_ID}, "调度请求未绑定当前责任组件")
        changed = self.reconcile()
        if not self.enabled or job.id == TIME_ID and self.trigger == "EVENT" or job.id == CONTROL_ID and not changed:
            return encode({"state": "NO_DISPATCH_REQUIRED", "schedule_version": self.version})
        self.running_count += 1
        try:
            results = self.store.dispatch_due(NAMESPACE)
        finally:
            self.running_count -= 1
        return encode({"schedule_version": self.version, "results": results})

    def snapshot(self):
        job = self.cron.get_job(TIME_ID)
        next_ms = job.state.next_run_at_ms if job is not None and job.enabled else None
        return {"state": "RUNNING" if self.started_at else "NOT_STARTED", "active_run_count": self.running_count,
                "resume_checked_at": self.checked_at, "quit_behavior": "应用后台进程退出后停止；重启按已保存策略恢复",
                "schedule_version": self.version, "started_at": self.started_at,
                "next_run_time": datetime.fromtimestamp(next_ms / 1000, timezone.utc).isoformat() if next_ms else None}
