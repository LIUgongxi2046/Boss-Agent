import argparse
import hashlib
import json
import os
import shutil
import sqlite3
from pathlib import Path

from filelock import FileLock
from nanobot.config.loader import load_config, save_config
from nanobot.channels.websocket.runtime import WebSocketConfig
from jsonschema import Draft202012Validator, FormatChecker

from business import checksum, initial_materials


ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def workspace_manifest(directory):
    entries = {}
    for path in directory.rglob("*"):
        assert not path.is_symlink()
        if path.is_file():
            entries[str(path.relative_to(directory))] = digest(path)
    return entries


def prepare(reference, target, token_ttl_seconds=None):
    reference = reference.resolve(strict=True)
    assert reference.is_relative_to(ROOT / "evidence/T11")
    report = json.loads(reference.read_text())
    assert report["status"] == "PASS_PUBLIC_A12_OWNER_DELETION_AND_NEXT_ACTUAL_MODEL_CONTEXT"
    source = (ROOT / report["application_directory"]).resolve(strict=True)
    parent = (ROOT / "validation/.work").resolve(strict=True)
    assert source.parent == parent and source.name.startswith("runtime-application-")
    target = target.resolve()
    assert target.parent == parent and target.name.startswith("account-upgrade-") and not target.exists()
    assert not (source / "accounts").exists()
    schema = json.loads((ROOT / "specs/runtime-records.schema.json").read_text())
    schema["$ref"] = "#/$defs/CurrentRuntimeRun"
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    with FileLock(str(source / "application.lock"), timeout=0):
        config = load_config(source / "config.json")
        channel = WebSocketConfig.model_validate(config.channels.websocket)
        if token_ttl_seconds is not None:
            assert isinstance(token_ttl_seconds, int) and 1 <= token_ttl_seconds <= 3600
            channel.token_ttl_s = token_ttl_seconds
            config.channels.websocket = channel.model_dump(mode="json", by_alias=True)
        assert config.providers.deepseek.api_key == "${DEEPSEEK_API_KEY}"
        workspace = config.workspace_path.resolve(strict=True)
        assert workspace.parent == source
        original_config_sha = digest(source / "config.json")
        original_database_sha = digest(source / "business.sqlite")
        original_files = workspace_manifest(workspace)
        target.mkdir(mode=0o700)
        destination = target / "business.sqlite"
        descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        with sqlite3.connect((source / "business.sqlite").as_uri() + "?mode=ro", uri=True) as db:
            db.execute("BEGIN")
            initial = json.loads(db.execute("SELECT body FROM objects WHERE namespace='ui-check' AND kind='initial' AND id='snapshot'").fetchone()[0])
            assert initial == initial_materials()
            rows = tuple(db.iterdump())
            runs = [json.loads(row[0]) for row in db.execute("SELECT body FROM objects WHERE namespace='ui-check' AND kind='runtime_run' ORDER BY id")]
            assert len(runs) == 3 and all(row["status"] == "SUCCEEDED" for row in runs)
            assert all(validator.is_valid(row) for row in runs)
            configuration = json.loads(db.execute("SELECT body FROM objects WHERE namespace='ui-check' AND kind='configuration' AND id='current'").fetchone()[0])
            memory = json.loads(db.execute("SELECT body FROM objects WHERE namespace='ui-check' AND kind='memory' AND id='current'").fetchone()[0])
            assert configuration["version"] == "3" and configuration["max_tool_rounds"] == 6
            assert memory["version"] == "2" and memory["confirmation_state"] == "DELETED" and memory["text"] == ""
            with sqlite3.connect(destination) as copied:
                db.backup(copied)
                assert copied.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                assert tuple(copied.iterdump()) == rows
        shutil.copytree(workspace, target / "workspace")
        assert workspace_manifest(target / "workspace") == original_files
        config.agents.defaults.workspace = str(target / "workspace")
        encoded_config = config.model_dump_json()
        access = json.loads((source / "access.json").read_text())
        assert all(value not in encoded_config for value in access.values())
        save_config(config, target / "config.json")
        (target / "config.json").chmod(0o600)
        assert digest(source / "config.json") == original_config_sha
        assert digest(source / "business.sqlite") == original_database_sha
        assert workspace_manifest(workspace) == original_files
    result = {"status": "ACTUAL_PREACCOUNT_APPLICATION_NATIVE_BACKUP", "reference": str(reference.relative_to(ROOT)),
        "reference_sha256": digest(reference), "source_directory": str(source.relative_to(ROOT)),
        "target_directory": str(target.relative_to(ROOT)), "source_database_sha256": original_database_sha,
        "copied_database_sha256": digest(destination), "source_configuration_sha256": original_config_sha,
        "workspace_manifest_sha256": checksum(original_files), "workspace_files": len(original_files),
        "historical_run_ids": [row["run_id"] for row in runs], "configuration_version": "3", "memory_version": "2",
        "memory_confirmation_state": "DELETED", "initial_snapshot_sha256": checksum(initial),
        "token_ttl_seconds": channel.token_ttl_s,
        "database_logical_copy_identical": True, "workspace_copy_identical": True,
        "source_database_configuration_and_workspace_unchanged": True, "new_model_calls": False,
        "private_body_recorded": False}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--target-directory", type=Path, required=True)
    parser.add_argument("--token-ttl-seconds", type=int)
    args = parser.parse_args()
    prepare(args.reference, args.target_directory, args.token_ttl_seconds)
