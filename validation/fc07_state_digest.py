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
kinds = ("task", "outbox", "feedback", "assignment_extension_decision", "assignment_nudge", "self_commitment", "self_commitment_revision", "task_revision", "mvp_query", "fc01_preparation")
with sqlite3.connect((directory / "business.sqlite").as_uri() + "?mode=ro", uri=True) as db:
    rows = db.execute("SELECT kind,id,body FROM objects WHERE namespace='ui-check' AND kind IN (" + ",".join("?" for _ in kinds) + ") ORDER BY kind,id", kinds).fetchall()
print(json.dumps([{"kind": kind, "id": ident, "sha256": hashlib.sha256(body.encode()).hexdigest()} for kind, ident, body in rows]))
