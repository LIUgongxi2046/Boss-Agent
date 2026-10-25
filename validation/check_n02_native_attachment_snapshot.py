import argparse
import hashlib
import json
from pathlib import Path

from nanobot.session.manager import SessionManager

from boss_conversation_attachments import ConversationAttachments


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    directory = args.snapshot.resolve()
    output = args.output.resolve()
    assert directory.is_relative_to(ROOT / ".work") and directory.is_dir()
    assert output.is_relative_to(ROOT / "docs/menu-delivery/N02") or output.is_relative_to(ROOT / ".work")
    context = {"session_id": "websocket:n02-real-file", "chat_id": "n02-real-file"}
    sessions = SessionManager(directory / "native-workspace", sessions_root=directory / "native-sessions")
    saved = sessions.read_session_snapshot(context["session_id"])
    assert saved is not None
    metadata = saved.metadata["boss_attachment_metadata"]
    users = [message for message in saved.messages if message["role"] == "user"]
    assert len(metadata) == 1 and users and not any(message.get("media") for message in users)
    assert all("relative_path" not in value for value in metadata.values())
    view = ConversationAttachments(sessions, directory / "media").read("BOSS", context)
    assert len(view["attachments"]) == 1
    attachment = view["attachments"][0]
    actual = (ROOT / "specs/morning-coverage.json").read_bytes()
    assert attachment["attachment_id"] in metadata
    assert attachment["original_name"] == "morning-coverage.json"
    assert attachment["mime_type"] == "application/json"
    assert attachment["size_bytes"] == attachment["recorded_size_bytes"] == len(actual)
    assert attachment["content_sha256"] == attachment["recorded_content_sha256"] == hashlib.sha256(actual).hexdigest()
    assert attachment["processing_state"] == "STORED" and attachment["user_message_index"] is None
    assert str(directory) not in json.dumps(view) and "relative_path" not in json.dumps(view)
    unavailable = ConversationAttachments(sessions, directory / "unavailable-media").read("BOSS", context)
    unavailable_file = unavailable["attachments"][0]
    assert unavailable_file["attachment_id"] == attachment["attachment_id"]
    assert unavailable_file["processing_state"] == "REFERENCE_UNAVAILABLE"
    assert unavailable_file["stored_name"] is None and unavailable_file["user_message_index"] is None
    assert unavailable_file["size_bytes"] is None and unavailable_file["content_sha256"] is None
    assert unavailable_file["recorded_size_bytes"] == len(actual)
    assert unavailable_file["recorded_content_sha256"] == hashlib.sha256(actual).hexdigest()
    assert sessions.read_session_snapshot(context["session_id"]).metadata == saved.metadata
    evidence = {"status": "PASS", "scope": "N1_ACTUAL_SDK_SAVED_DOCUMENT_SNAPSHOT",
        "metadata_count": len(metadata), "metadata_has_internal_reference": False,
        "user_message_keys": [sorted(message) for message in users],
        "user_media_count": sum(len(message.get("media", [])) for message in users),
        "snapshot_mutation_performed": False, "view": view, "reference_unavailable_view": unavailable}
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": evidence["status"], "attachment_count": len(view["attachments"])}))


if __name__ == "__main__":
    main()
