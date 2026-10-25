import test from "node:test";
import assert from "node:assert/strict";
import {shouldRefreshN02Attachments,validateN02AttachmentRead} from "../webui/n02-attachments.ts";

const chatId="n02-owner-chat-01";
const stored={
  attachment_id:"attachment-"+"a".repeat(64),
  original_name:"业务资料.xlsx",stored_name:"native-upload-8.xlsx",
  mime_type:"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  size_bytes:9216,content_sha256:"b".repeat(64),
  recorded_size_bytes:9216,recorded_content_sha256:"b".repeat(64),
  user_message_index:null,processing_state:"STORED",
};
const envelope=(attachments=[stored])=>({
  source_type:"RUNTIME_RECORD",chat_id:chatId,session_id:"websocket:"+chatId,
  session_state:"SAVED",business_authorization_granted:false,attachments,
});

test("file status refreshes even with no run or an unchanged run marker",()=>{
  assert.equal(shouldRefreshN02Attachments(null,"NO_RUN",10000),true);
  const first={runMarker:"NO_RUN",checkedAt:10000};
  assert.equal(shouldRefreshN02Attachments(first,"NO_RUN",11999),false);
  assert.equal(shouldRefreshN02Attachments(first,"NO_RUN",14999),false);
  assert.equal(shouldRefreshN02Attachments(first,"NO_RUN",15000),true);
  assert.equal(shouldRefreshN02Attachments(first,"run:1:RUNNING",10001),true);
  assert.equal(shouldRefreshN02Attachments(first,"NO_RUN",9999),true,
    "a clock step back must not hide external attachment changes");
  assert.throws(()=>shouldRefreshN02Attachments(first,"NO_RUN",Infinity),/时间/);
});

test("repeated native reads adopt upload, removal and content change independently of runtime",()=>{
  const first=validateN02AttachmentRead(envelope(),chatId);
  assert.equal(first[0].processing_state,"STORED");
  const changed=validateN02AttachmentRead(envelope([{...stored,
    size_bytes:7000,content_sha256:"c".repeat(64),processing_state:"CHANGED"}]),chatId);
  assert.equal(changed[0].processing_state,"CHANGED");
  const missing=validateN02AttachmentRead(envelope([{...stored,
    size_bytes:null,content_sha256:null,processing_state:"MISSING"}]),chatId);
  assert.equal(missing[0].processing_state,"MISSING");
  assert.equal(missing[0].recorded_size_bytes,9216);
  assert.equal(validateN02AttachmentRead(envelope([]),chatId).length,0);
});

test("cross-session, forged authority and missing ownership cannot appear as current files",()=>{
  for(const value of [
    {...envelope(),chat_id:"another-chat"},
    {...envelope(),session_id:"websocket:another-chat"},
    {...envelope(),source_type:"SIMULATED"},
    {...envelope(),business_authorization_granted:true},
    {...envelope(),session_state:"NO_SAVED_SESSION"},
    {...envelope(),attachments:null},
    undefined,[],null,
  ]) assert.throws(()=>validateN02AttachmentRead(value,chatId),/范围|会话/);
  assert.deepEqual(validateN02AttachmentRead({...envelope(),session_state:"NO_SAVED_SESSION",attachments:[]},chatId),[]);
});

test("invalid, repeated or path-like attachment references fail closed without leaking file names",()=>{
  for(const attachment of [
    {...stored,attachment_id:"other-kind"},
    {...stored,recorded_content_sha256:"not sha"},
    {...stored,processing_state:"READY"},
    {...stored,original_name:"../../private.sqlite"},
    {...stored,stored_name:"/Users/owner/private.xlsx"},
    {...stored,original_name:"private\\document.txt"},
    {...stored,user_message_index:-1},
    {...stored,size_bytes:-4},
  ]) assert.throws(()=>validateN02AttachmentRead(envelope([attachment]),chatId),/附件元信息/);
  assert.throws(()=>validateN02AttachmentRead(envelope([stored,stored]),chatId),/附件元信息/);
});
