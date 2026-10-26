from boss_execution_scope import require_dataset_scope
from boss_v7_store import NAMESPACE, optional, rows


def owner_spaces(db, snapshot):
    yield NAMESPACE, snapshot, None
    for archive in rows(db, "execution_archive", "dataset-catalog"):
        namespace = archive["namespace"]
        if namespace == NAMESPACE or archive.get("state") != "READ_ONLY":
            continue
        space = db.execute("SELECT active FROM spaces WHERE namespace=?", (namespace,)).fetchone()
        initial = optional(db, "initial", "snapshot", namespace)
        if space != (0,) or initial is None or initial.get("owner_id") != snapshot["owner_id"]:
            continue
        if initial.get("dataset_id") != archive.get("dataset_id"):
            continue
        require_dataset_scope(db, namespace, initial)
        yield namespace, initial, archive
