"""FR-08 / FR-12 SQLite integration and privacy regressions.

Real objects, versioned mutation and access boundary; no genuine delivery.
"""
import json
import sys
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"validation"))
from controls import ControlStore
from boss_command_api import BossCommandAPI
from boss_page_api import BossPageAPI


@pytest.fixture
def services(tmp_path):
    db=ControlStore(tmp_path/"messaging.sqlite")
    db.initialize("ui-check")
    return BossCommandAPI(db),BossPageAPI(db)


def cmd(api,role,action,key,**kwargs):
    return api.execute(role,action,{"client_request_id":key,**kwargs})


def msg_input(**extra):
    return {
        "draft_id":None,"expected_version":"0",
        "recipient_id":"coordinator-1","related_task_id":None,
        "body":"请核实这份经营材料并反馈证据。",
        "attachment_refs":[{"source_id":"finance-note","version":"1"}],
        "visibility":"RECIPIENT_ONLY",**extra,
    }


def calendar_input(**extra):
    return {
        "expected_version":"1",
        "starts_at":"2026-10-24T18:00:00+08:00",
        "ends_at":"2026-10-24T19:00:00+08:00",
        "timezone":"Asia/Shanghai",
        "title":"仅本人可见的事项","private_body":"隐私事项：私人会面地点与资料",
        "location":"私人地点","attachment_refs":[],
        "acknowledge_conflict":False,**extra,
    }


def read(api,role,key):
    return api.serve(role,"/api/boss/ui/workspace/"+key)


def test_message_draft_uses_stable_contact_id_not_same_name(services):
    api,pages=services
    status,out=cmd(api,"BOSS","boss.message.draft.save","msg-draft-001",**msg_input())
    assert status==200,out
    assert out["status"]=="DRAFT"
    assert out["message_sent"] is False
    assert cmd(api,"BOSS","boss.message.draft.save","msg-draft-001",**msg_input())==(status,out)
    _,view=read(pages,"BOSS","outbox")
    assert view["drafts"][0]["recipient_id"]=="coordinator-1"
    assert view["sent_messages"]==[]
    assert read(pages,"MAINTAINER","outbox")[0]==403
    assert cmd(api,"MAINTAINER","boss.message.draft.save","maint-draft-001",**msg_input())[0]==403
    # Contact-2 has same display name, but is not the same stable identity.
    status,another=cmd(api,"BOSS","boss.message.draft.save","msg-draft-002",
                       **msg_input(recipient_id="contact-2"))
    assert status==200 and another["draft_id"]!=out["draft_id"]


def test_message_edit_cas_blocks_old_send_and_preserves_revision(services):
    api,pages=services
    first=cmd(api,"BOSS","boss.message.draft.save","msg-new-011",**msg_input())[1]
    id=first["draft_id"]
    edited=msg_input(draft_id=id,expected_version="1",body="已修改内容，请等待正式发送决定。")
    code,current=cmd(api,"BOSS","boss.message.draft.save","msg-edit-011",**edited)
    assert code==200 and current["version"]=="2"
    with api.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='message_draft_revision'").fetchone()[0]==1
    assert cmd(api,"BOSS","boss.message.draft.save","msg-stale-edit-01",
               **edited)[0]==409
    old_send={
        "draft_id":id,"expected_version":"1",
        "recipient_id":"coordinator-1",
        "expected_content_sha256":"old-stale-sha",
    }
    assert cmd(api,"BOSS","boss.message.send","msg-old-send-01",**old_send)[0]==409


def test_send_records_simulated_only_once_and_requires_matching_digest(services):
    api,pages=services
    d=cmd(api,"BOSS","boss.message.draft.save","msg-save-201",**msg_input())[1]
    details=read(pages,"BOSS","outbox")[1]["drafts"][0]
    bad={
        "draft_id":d["draft_id"],"expected_version":"1",
        "recipient_id":"coordinator-1",
        "expected_content_sha256":"tampered",
    }
    assert cmd(api,"BOSS","boss.message.send","msg-send-bad",**bad)[0]==403
    current={**bad,"expected_content_sha256":details["content_sha256"]}
    code,sent=cmd(api,"BOSS","boss.message.send","msg-send-201",**current)
    assert code==200,sent
    assert sent["send_state"]=="SENT_SIMULATED"
    assert sent["delivery_state"]=="NOT_VERIFIED"
    assert sent["external_channel_invoked"] is False
    assert cmd(api,"BOSS","boss.message.send","msg-send-201",**current)==(code,sent)
    assert cmd(api,"BOSS","boss.message.send","msg-send-202",**current)[0]==409
    _,state=read(pages,"BOSS","outbox")
    assert state["drafts"][0]["status"]=="SENT_SIMULATED"
    assert state["sent_messages"][0]["message_id"]==sent["message_id"]
    assert state["replies"]==[]
    with api.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='authorization'").fetchone()[0]==1
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='message_outbox'").fetchone()[0]==1
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='outbox'").fetchone()[0]==0


def test_simulated_reply_is_linked_and_cannot_confirm_task(services):
    api,pages=services
    cmd(api,"BOSS","boss.message.draft.save","msg-reply-new",**msg_input())
    d=read(pages,"BOSS","outbox")[1]["drafts"][0]
    s=cmd(api,"BOSS","boss.message.send","msg-reply-send",
          draft_id=d["draft_id"],expected_version="1",
          recipient_id="coordinator-1",
          expected_content_sha256=d["content_sha256"])[1]
    assert cmd(api,"BOSS","boss.simulation.message.reply","msg-owner-fake",
               message_id=s["message_id"],author_contact_id="coordinator-1",
               text="已核查")[0]==403
    assert cmd(api,"MAINTAINER","boss.simulation.message.reply","msg-other-author",
               message_id=s["message_id"],author_contact_id="contact-2",
               text="无法伪造回复")[0]==403
    code,reply=cmd(api,"MAINTAINER","boss.simulation.message.reply",
                   "msg-reply-valid",message_id=s["message_id"],
                   author_contact_id="coordinator-1",text="合成反馈：还缺少证明")
    assert code==200,reply
    assert reply["reply_to"]==s["message_id"]
    assert not reply["task_completion_confirmed"]
    assert cmd(api,"MAINTAINER","boss.simulation.message.reply",
               "msg-reply-repeat",message_id=s["message_id"],
               author_contact_id="coordinator-1",text="重复")[0]==409
    _,view=read(pages,"BOSS","outbox")
    assert view["sent_messages"][0]["reply_state"]=="RECEIVED_SIMULATED"
    assert view["replies"][0]["reply_to"]==s["message_id"]


def test_withdrawn_attachments_block_message_send(services):
    api,pages=services
    cmd(api,"BOSS","boss.message.draft.save","msg-before-withdraw",**msg_input())
    draft=read(pages,"BOSS","outbox")[1]["drafts"][0]
    api.store.control("ui-check","withdraw",{"source_id":"finance-note","version":"1"})
    status,_=cmd(api,"BOSS","boss.message.send","msg-withdraw-send",
                 draft_id=draft["draft_id"],expected_version="1",
                 recipient_id="coordinator-1",
                 expected_content_sha256=draft["content_sha256"])
    assert status==403
    _,view=read(pages,"BOSS","outbox")
    assert view["sent_messages"]==[]


def test_calendar_owner_only_updated_body_never_in_maintainer_projection(services):
    api,pages=services
    code,result=cmd(api,"BOSS","boss.calendar.save",
                    "private-calendar-save",**calendar_input())
    assert code==200,result
    assert result["version"]=="2"
    assert not result["external_calendar_updated"]
    assert cmd(api,"BOSS","boss.calendar.save",
               "private-calendar-save",**calendar_input())==(code,result)
    assert cmd(api,"MAINTAINER","boss.calendar.save","maint-calendar",
               **calendar_input(expected_version="2"))[0]==403
    _,view=read(pages,"BOSS","calendar")
    assert "隐私事项" in view["calendar"]["private_body"]
    assert view["calendar"]["version"]=="2"
    for k in ("system","dataset","audit","relationships"):
        _,p=read(pages,"MAINTAINER",k)
        assert "隐私事项" not in json.dumps(p)
        assert "私人地点" not in json.dumps(p)
    with api.store.connect() as db:
        auth=db.execute("SELECT body FROM objects WHERE kind='authorization'").fetchall()
        audit=db.execute("SELECT input,output FROM audit").fetchall()
        assert "隐私事项" not in str(auth)
        assert "隐私事项" not in str(audit)


def test_calendar_conflict_unknown_must_be_acknowledged(services):
    api,_=services
    nearby=calendar_input(starts_at="2026-10-23T08:30:00+08:00",
        ends_at="2026-10-23T09:30:00+08:00")
    assert cmd(api,"BOSS","boss.calendar.save","private-conflict-fail",**nearby)[0]==409
    assert cmd(api,"BOSS","boss.calendar.save","private-conflict-pass",
               **{**nearby,"acknowledge_conflict":True})[0]==200


def test_busy_share_returns_no_title_location_body_and_can_revoke(services):
    api,pages=services
    saved=cmd(api,"BOSS","boss.calendar.save",
              "private-share-save",**calendar_input())[1]
    params={
        "expected_version":saved["version"],"recipient_id":"coordinator-1",
        "purpose":"仅向对方展示已占用时段",
        "expires_at":"2026-10-25T08:00:00+08:00",
        "fields":["busy","starts_at","ends_at","timezone"],
    }
    assert cmd(api,"MAINTAINER","boss.calendar.share","maint-share",**params)[0]==403
    status,shared=cmd(api,"BOSS","boss.calendar.share","owner-share-001",**params)
    assert status==200,shared
    assert shared["share_status"]=="ACTIVE_SIMULATED"
    assert not shared["external_delivery_created"]
    _,owner=read(pages,"BOSS","calendar")
    record=owner["shares"][0]
    assert record["busy"] is True
    assert "title" not in record and "private_body" not in record
    assert "location" not in record and "attachment_refs" not in record
    assert cmd(api,"BOSS","boss.calendar.share","share-private-body",
               **{**params,"fields":["private_body"]})[0]==403
    code,revoked=cmd(api,"BOSS","boss.calendar.share.revoke","revoke-share-1",
                     share_id=shared["share_id"],expected_version=saved["version"])
    assert code==200,revoked
    assert revoked["share_status"]=="REVOKED"
    assert not revoked["external_recall_verified"]
    assert cmd(api,"BOSS","boss.calendar.share.revoke","revoke-again",
               share_id=shared["share_id"],expected_version=saved["version"])[0]==409


def test_calendar_update_invalidates_existing_busy_share(services):
    api,pages=services
    saved=cmd(api,"BOSS","boss.calendar.save","calendar-write-1",**calendar_input())[1]
    params={
        "expected_version":saved["version"],"recipient_id":"finance-1",
        "purpose":"协调一段日程","expires_at":"2026-10-25T08:00:00+08:00",
        "fields":["busy","starts_at","ends_at","timezone"],
    }
    sh=cmd(api,"BOSS","boss.calendar.share","calendar-share-1",**params)
    assert sh[0]==200
    changed=cmd(api,"BOSS","boss.calendar.save","calendar-write-2",
                **calendar_input(expected_version="2",
                   private_body="新的本人私人正文"))
    assert changed[0]==200,changed
    assert changed[1]["active_shares_invalidated"]
    _,calendar=read(pages,"BOSS","calendar")
    assert calendar["shares"][0]["revoked"] is True
    assert cmd(api,"BOSS","boss.calendar.share","stale-calendar-share",
               **params)[0]==409


def test_calendar_delete_revokes_shares_and_stops_future_private_read(services):
    api,pages=services
    saved=cmd(api,"BOSS","boss.calendar.save","delete-save-1",**calendar_input())[1]
    cmd(api,"BOSS","boss.calendar.share","delete-share-1",
        expected_version=saved["version"],recipient_id="finance-1",
        purpose="忙碌时段",expires_at="2026-10-25T08:00:00+08:00",
        fields=["busy","starts_at","ends_at","timezone"])
    code,deleted=cmd(api,"BOSS","boss.calendar.delete","owner-delete-1",
                     expected_version="2")
    assert code==200,deleted
    assert deleted["status"]=="DELETED"
    assert deleted["future_visibility_stopped"]
    assert not deleted["physical_secure_erasure_verified"]
    _,owner=read(pages,"BOSS","calendar")
    assert owner["calendar"]["private_body"]==""
    assert owner["calendar"]["status"]=="DELETED"
    assert owner["shares"][0]["revoked"]
    assert cmd(api,"BOSS","boss.calendar.save","restore-not-allowed",
               **calendar_input(expected_version="3"))[0]==409
