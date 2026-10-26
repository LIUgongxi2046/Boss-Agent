import json


def current_calendar(db, namespace, initial):
    saved = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='private_calendar' AND id='private-1'",
                       (namespace,)).fetchone()
    if saved is not None:
        return json.loads(saved[0])
    if initial["private_calendar"] is None:
        return None
    return {**initial["private_calendar"], "version": "1", "status": "ACTIVE",
            "title": "", "location": "", "attachment_refs": []}
