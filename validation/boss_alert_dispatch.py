from datetime import datetime
from zoneinfo import ZoneInfo

from business import checksum, now
from boss_alert_policy import GENERATOR, get, items, material, record_dispatch
from boss_scheduler_config import event_in_scope
from boss_notification_snapshot import notification_snapshot


def quiet(clock, configuration):
    hour = clock.astimezone(ZoneInfo(configuration["timezone"])).hour
    begin, end = configuration["quiet_start"], configuration["quiet_end"]
    return hour >= begin or hour < end if begin > end else begin <= hour < end


def dispatch(store, db, ns, only_event_id=None):
    from boss_owner_plans import suppression
    from boss_owner_preferences import effective_owner_notice
    data = store.get(db, ns, "initial", "snapshot")
    clock = datetime.fromisoformat(store.get(db, ns, "clock", "current")["at"])
    schedule, technical = store.get(db, ns, "schedule", "current"), get(db, ns, "rules", "current")
    notice = effective_owner_notice(db, data, ns)
    results = []
    for event in items(db, ns, "event"):
        if event.get("generated_by") != GENERATOR or only_event_id is not None and event["event_id"] != only_event_id:
            continue
        if not event_in_scope(schedule, event):
            continue
        view = material(store, db, ns, data, event)
        evaluation, rule, reminder = view["evaluation"], view["business_rule"], view["reminder"]
        cfg = rule["configuration"] if rule else None
        tracking = get(db, ns, "business_alert_tracking", event["event_id"]) or {"episode": 0, "incident_open": False}
        phase = evaluation["phase"]
        if phase in ("BREACH", "IMMEDIATE") and not tracking["incident_open"]:
            tracking.update(episode=tracking["episode"] + 1, incident_open=True)
        if phase == "RECOVERY" and tracking["incident_open"]:
            recovery_id = event["event_id"] + ":" + str(tracking["episode"])
            if get(db, ns, "business_alert_recovery", recovery_id) is None:
                store.put(db, ns, "business_alert_recovery", recovery_id, {"event_id": event["event_id"], "event_version": event["version"], "owner_id": data["owner_id"],
                    "episode": tracking["episode"], "rule_version": rule["version"], "condition_since": evaluation["condition_since"], "recovered_at": event["observed_at"],
                    "source_refs": event["source_refs"], "recorded_at": now(), "task_completed": False})
            tracking["incident_open"] = False
        mode = "RECOVERY" if phase == "RECOVERY" else "ALERT"
        token = reminder.get("until") if reminder and reminder["state"] == "SNOOZED" else None
        expired_snooze = bool(token and datetime.fromisoformat(token) <= clock and tracking.get("last_snooze_until") != token)
        same_incident = tracking.get("sent_episode") == tracking["episode"] and tracking.get("sent_mode") == mode
        escalation = bool(cfg and technical and cfg["important_escalation"] and technical["important_escalation"]
                          and event["impact"] == "IMPORTANT" and tracking.get("last_impact") == "NORMAL")
        reason = None
        if not schedule["enabled"] or schedule["canceled"]:
            reason = "PLAN_PAUSED_OR_CANCELED"
        elif view["rule_state"] != "ACTIVE":
            reason = view["rule_state"]
        elif technical is None:
            reason = "TECHNICAL_RULES_NOT_CONFIGURED"
        elif event["state"] == "CANCELED":
            reason = "SOURCE_CANCELED"
        elif (plan_reason := suppression(store, db, ns, event, clock)):
            reason = plan_reason
        elif view["adoption_state"] != "CURRENT":
            reason = "SOURCE_NOT_CURRENT"
        elif reminder and reminder["state"] == "CLOSED":
            reason = "BOSS_CLOSED"
        elif reminder and reminder["state"] == "SNOOZED":
            auth = store.get(db, ns, "authorization", reminder["authorization_id"])
            if auth["revoked"]:
                reason = "REMINDER_AUTHORIZATION_REVOKED"
            elif datetime.fromisoformat(token) > clock:
                reason = "BOSS_SNOOZED"
        if reason is None:
            if phase in ("UNKNOWN", "WAITING", "SUMMARY"):
                reason = evaluation["reason"]
            elif phase == "RECOVERY" and (tracking["episode"] == 0 or not cfg["notify_recovery"]):
                reason = "RECOVERY_RECORDED_WITHOUT_NOTIFICATION"
            elif notice and not notice["content"]["notifications_enabled"]:
                reason = "OWNER_NOTIFICATIONS_PAUSED"
            elif (quiet(clock, cfg) or quiet(clock, technical) or notice and quiet(clock, notice["content"])) and not (
                    notice and notice["content"]["important_during_quiet"] and cfg["important_escalation"] and technical["important_escalation"] and event["impact"] == "IMPORTANT"):
                reason = "QUIET_HOURS"
            elif same_incident and not escalation and not expired_snooze:
                reason = "SAME_INCIDENT_MERGED"
            elif tracking.get("delivered_at") and (clock - datetime.fromisoformat(tracking["delivered_at"])).total_seconds() < max(cfg["cooldown_seconds"], technical["cooldown_seconds"]) and not escalation:
                reason = "COOLDOWN"
        result = {"source_type": "SIMULATED", "event_id": event["event_id"], "event_version": event["version"], "owner_id": data["owner_id"],
            "state": "SUPPRESSED" if reason else "DELIVERED", "reason": reason, "mode": mode, "episode": tracking["episode"],
            "rule_version": rule["version"] if rule else None, "technical_rule_version": technical["version"] if technical else None,
            "schedule_version": schedule["version"], "owner_notice_version": view["owner_notice_version"], "business_at": clock.isoformat(),
            "evaluation": evaluation, "source_refs": event["source_refs"], "execution_owner": "CronService", "external_delivery_verified": False}
        if reason == "GENERAL_PROGRESS_SUMMARY":
            store.put(db, ns, "business_alert_summary", event["event_id"], {**result, "observed_at": event["observed_at"]})
        notification_id = event["event_id"] + ":alert"
        old_notice = get(db, ns, "notification", notification_id)
        if reason is None:
            if old_notice:
                store.put(db, ns, "notification_revision", notification_id + ":" + old_notice["version"], old_notice)
            notification = {**result, "notification_id": notification_id, "version": str(int(old_notice["version"]) + 1) if old_notice else "1",
                "delivered_at": clock.isoformat(), "notification_center_state": "SAVED", "system_notification_state": "NOT_REQUESTED"}
            notification = notification_snapshot(db, ns, event, notification)
            store.put(db, ns, "notification", notification_id, notification)
            store.put(db, ns, "delivery", event["event_id"], notification)
            store.put(db, ns, "business_alert_delivery", checksum(result), notification)
            if reminder:
                store.put(db, ns, "reminder_revision", event["event_id"] + ":" + reminder["version"], reminder)
            store.put(db, ns, "reminder", event["event_id"], {"event_id": event["event_id"], "event_version": event["version"],
                "version": str(int(reminder["version"]) + 1) if reminder else "1", "state": "DELIVERED", "until": None})
            tracking.update(sent_episode=tracking["episode"], sent_mode=mode, last_impact=event["impact"], delivered_at=clock.isoformat())
            if expired_snooze:
                tracking["last_snooze_until"] = token
        elif reason == "SAME_INCIDENT_MERGED" and old_notice and old_notice["event_version"] != event["version"]:
            store.put(db, ns, "notification_revision", notification_id + ":" + old_notice["version"], old_notice)
            store.put(db, ns, "notification", notification_id, notification_snapshot(db, ns, event, {
                **old_notice, "version": str(int(old_notice["version"]) + 1), "event_version": event["version"],
                "source_refs": event["source_refs"], "merged_at": clock.isoformat(), "merge_reason": reason}))
        store.put(db, ns, "business_alert_tracking", event["event_id"], tracking)
        results.append(record_dispatch(store, db, ns, result))
    return results
