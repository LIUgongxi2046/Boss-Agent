"""FR-10 person meeting preparations and F04 agenda links over actual SQLite."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_command_api import BossCommandAPI
from boss_page_api import BossPageAPI
from controls import ControlStore


@pytest.fixture
def app(tmp_path):
    store = ControlStore(tmp_path / "people.sqlite")
    store.initialize("ui-check")
    return BossCommandAPI(store), BossPageAPI(store)


def cmd(api, role, action, key, **input):
    return api.execute(role, action, {"client_request_id": key, **input})


def draft(**kw):
    return {
        "brief_id": None, "expected_version": "0",
        "contact_id": "coordinator-1",
        "purpose": "核查当前负责人的承诺、任务反馈和资料缺口",
        "meeting_id": "meeting-1",
        "source_refs": [{"source_id": "meeting-minutes", "version": "1"}],
        **kw,
    }


def attach_input(result, checksum, **changes):
    return {
        "brief_id": result["brief_id"],
        "expected_version": result["version"],
        "meeting_id": "meeting-1", "meeting_version": "1",
        "compiled_sha256": checksum,
        **changes,
    }


def read(pages, role="BOSS"):
    return pages.serve(role, "/api/boss/ui/workspace/people")


def test_preparation_has_source_pins_live_work_facts_and_no_external_action(app):
    api, pages = app
    code, result = cmd(api, "BOSS", "boss.people.prepare", "people-prep-first", **draft())
    assert code == 200, result
    assert result["state"] == "READY_FOR_REVIEW" and result["version"] == "1"
    assert result["source_count"] == 1 and result["task_count"] == 1
    assert result["meeting_unchanged"] is True and result["invitation_sent"] is False
    _, projection = read(pages)
    item = projection["briefs"][0]
    assert item["live_evidence_current"] is True
    assert item["compiled"]["contact"]["contact_id"] == "coordinator-1"
    assert item["compiled"]["contact"]["responsibility"] == "业务统筹"
    assert item["compiled"]["sources"][0]["source_id"] == "meeting-minutes"
    assert item["compiled"]["sources"][0]["version"] == "1"
    assert "合成历史会议纪要" in item["compiled"]["sources"][0]["excerpt"]
    assert item["compiled"]["tasks"][0]["task_id"] == "historical-1"
    assert item["compiled"]["questions"][0]["task_id"] == "historical-1"
    assert item["compiled"]["feedback"] == []
    assert projection["external_meeting_invitation_sent"] is False
    assert projection["employee_accounts_created"] is False
    with api.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='authorization'").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='message_outbox'").fetchone()[0] == 0


def test_attach_is_owner_authorized_idempotent_and_invalidates_f04(app):
    api, pages = app
    code, prepared = cmd(api, "BOSS", "boss.meeting.brief.prepare",
                         "people-f04-prepared", meeting_id="meeting-1",
                         meeting_version="1", expected_version="0")
    assert code == 200 and prepared["state"] == "READY_FOR_REVIEW"
    result = cmd(api, "BOSS", "boss.people.prepare", "people-prep-for-meeting", **draft())[1]
    _, view = read(pages)
    people = view["briefs"][0]
    _, f04 = pages.serve("BOSS", "/api/boss/ui/workspace/briefing")
    assert f04["current_status"] == "READY_FOR_REVIEW"

    input = attach_input(result, people["compiled_sha256"])
    assert cmd(api, "MAINTAINER", "boss.people.attach", "people-maint-denied", **input)[0] == 403
    assert cmd(api, "BOSS", "boss.people.attach", "people-version-false",
               **{**input, "meeting_version": "0"})[0] == 409
    code, linked = cmd(api, "BOSS", "boss.people.attach", "people-linked-to-meeting", **input)
    assert code == 200, linked
    assert linked["state"] == "ATTACHED_TO_MEETING_AGENDA"
    assert linked["meeting_agenda_linked"] is True
    assert linked["meeting_attendees_changed"] is False
    assert linked["invitation_sent"] is False
    assert linked["authorization_id"]
    assert cmd(api, "BOSS", "boss.people.attach", "people-linked-to-meeting", **input) == (code, linked)
    assert cmd(api, "BOSS", "boss.people.attach", "people-duplicate-link", **input)[0] == 409
    _, f04 = pages.serve("BOSS", "/api/boss/ui/workspace/briefing")
    assert f04["business_changed"] and f04["current_status"] == "NEEDS_REVIEW"
    assert f04["current"]["people_meeting_impacts"][0]["contact_id"] == "coordinator-1"
    assert f04["saved_brief"]["version"] == "1"
    assert cmd(api, "BOSS", "boss.people.prepare", "people-edit-linked",
               **draft(brief_id=result["brief_id"], expected_version="2"))[0] == 409
    with api.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='authorization'").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='person_brief_revision'").fetchone()[0] == 1


def test_agenda_detach_releases_link_and_preserves_audit(app):
    api, pages = app
    created = cmd(api, "BOSS", "boss.people.prepare", "people-draft-linked", **draft())[1]
    current = read(pages)[1]["briefs"][0]
    joined = cmd(api, "BOSS", "boss.people.attach", "people-attach-linked",
                 **attach_input(created, current["compiled_sha256"]))[1]
    bad = cmd(api, "BOSS", "boss.people.detach", "people-no-reason",
              brief_id=created["brief_id"], expected_version="2", reason="")
    assert bad[0] == 400
    code, result = cmd(api, "BOSS", "boss.people.detach", "people-detach",
                       brief_id=created["brief_id"], expected_version=joined["version"],
                       reason="议题改到下一场讨论")
    assert code == 200, result
    assert result["state"] == "UNLINKED_FROM_MEETING_AGENDA"
    assert result["external_calendar_updated"] is False
    assert read(pages)[1]["briefs"][0]["linked_meeting_version"] is None
    assert cmd(api, "BOSS", "boss.people.detach", "people-detach-old",
               brief_id=created["brief_id"], expected_version=joined["version"],
               reason="重复解除")[0] == 409
    updated = cmd(api, "BOSS", "boss.people.prepare", "people-revised-after-detach",
                  **draft(brief_id=created["brief_id"], expected_version=result["version"]))
    assert updated[0] == 200 and updated[1]["version"] == "4"
    with api.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='person_brief_revision'").fetchone()[0] == 3


def test_same_name_contacts_do_not_inherit_a_coordinator_work_facts(app):
    api, pages = app
    code, _ = cmd(api, "BOSS", "boss.people.prepare", "people-contact-other",
                  **draft(contact_id="contact-2", source_refs=[]))
    assert code == 200
    view = read(pages)[1]["briefs"][0]
    assert view["compiled"]["contact"]["contact_id"] == "contact-2"
    assert view["compiled"]["contact"]["name"] == "陈明"
    assert view["compiled"]["tasks"] == []
    assert view["compiled"]["feedback"] == []
    assert view["state"] == "MATERIALS_MISSING"
    # Even without a source, an owner can register an explicit discussion
    # agenda item; it does not confer an employee account or verified work fact.
    linked = cmd(api, "BOSS", "boss.people.attach", "people-other-contact-link",
                 **attach_input({"brief_id":view["brief_id"],"version":view["version"]},
                                view["compiled_sha256"]))
    assert linked[0] == 200, linked


def test_expired_contact_invalid_meeting_or_injected_owner_rejected(app):
    api, pages = app
    assert cmd(api, "MAINTAINER", "boss.people.prepare", "people-maint-write",
               **draft())[0] == 403
    assert read(pages, "MAINTAINER")[0] == 403
    assert read(pages, "GUEST")[0] == 401
    assert cmd(api, "BOSS", "boss.people.prepare", "people-inject-owner",
               **{**draft(), "owner_id": "hacker"})[0] == 400
    assert cmd(api, "BOSS", "boss.people.prepare", "people-unknown-contact",
               **draft(contact_id="未知的陈明"))[0] == 400
    assert cmd(api, "BOSS", "boss.people.prepare", "people-other-meeting",
               **draft(meeting_id="unapproved-meeting"))[0] == 400
    advanced = cmd(api, "MAINTAINER", "boss.simulation.clock.advance", "people-expire-clock",
                   at="2027-02-01T09:00:00+08:00")
    assert advanced[0] == 200
    assert cmd(api, "BOSS", "boss.people.prepare", "people-expired-contact",
               **draft())[0] == 403
    assert read(pages)[1]["briefs"] == []


def test_withdrawn_document_is_not_returned_even_from_saved_snapshot(app):
    api, pages = app
    first = cmd(api, "BOSS", "boss.people.prepare", "people-source-created", **draft())[1]
    prior = read(pages)[1]["briefs"][0]
    assert prior["live_evidence_current"]
    api.store.control("ui-check", "withdraw", {
        "source_id": "meeting-minutes", "version": "1",
    })
    current = read(pages)[1]["briefs"][0]
    assert current["live_evidence_current"] is False
    assert current["compiled"]["sources"][0]["excerpt"] is None
    assert current["compiled"]["evidence_redacted_until_review"] is True
    assert cmd(api, "BOSS", "boss.people.attach", "people-old-source-link",
               **attach_input(first, prior["compiled_sha256"]))[0] in (403, 409)
    assert cmd(api, "BOSS", "boss.people.prepare", "people-old-source-revise",
               **draft(brief_id=first["brief_id"], expected_version="1"))[0] == 403


def test_independent_task_change_requires_refreshed_person_preparation(app):
    api, pages = app
    first = cmd(api, "BOSS", "boss.people.prepare", "people-before-new-task", **draft())[1]
    before = read(pages)[1]["briefs"][0]
    created = cmd(api, "BOSS", "boss.assignment.create", "people-task-changed",
                  purpose="需要新的明细核查", coordinator_id="coordinator-1",
                  due_at="2026-10-24T17:00:00+08:00", timezone="Asia/Shanghai",
                  evidence_requirements=["原始经营明细"],
                  related_meeting_id="meeting-1", related_event_ids=["event-1"],
                  source_refs=["finance-note"], content_version="1")
    assert created[0] == 200, created
    saved = read(pages)[1]["briefs"][0]
    assert saved["live_evidence_current"] is False
    assert cmd(api, "BOSS", "boss.people.attach", "people-stale-task-attach",
               **attach_input(first, before["compiled_sha256"]))[0] == 409
    revised = cmd(api, "BOSS", "boss.people.prepare", "people-refresh-task",
                  **draft(brief_id=first["brief_id"], expected_version="1"))
    assert revised[0] == 200 and revised[1]["task_count"] == 2
