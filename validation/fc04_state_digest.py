import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

from application_paths import application_work_directory

parser = argparse.ArgumentParser()
parser.add_argument("directory")
args = parser.parse_args()
directory = application_work_directory(Path(__file__).resolve().parent, args.directory)
kinds = ("task", "task_revision", "outbox", "feedback", "assignment_extension_decision", "assignment_nudge", "self_commitment", "self_commitment_revision",
    "owner_notice_draft", "owner_notice_active", "owner_notice_active_revision", "owner_plan", "owner_plan_revision", "document", "document_history",
    "business_alert_rule", "business_alert_rule_draft", "business_alert_rule_revision", "business_alert_observation", "business_alert_action", "notification_meeting_link", "notification_assignment_reference")
with sqlite3.connect((directory / "business.sqlite").as_uri() + "?mode=ro", uri=True) as db:
    rows = db.execute("SELECT kind,id,body FROM objects WHERE namespace='ui-check' AND kind IN (" + ",".join("?" for _ in kinds) + ") ORDER BY kind,id", kinds).fetchall()
print(json.dumps([{"kind": kind, "id": identifier, "sha256": hashlib.sha256(body.encode()).hexdigest()} for kind, identifier, body in rows]))
