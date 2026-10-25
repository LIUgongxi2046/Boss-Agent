import test from "node:test";
import assert from "node:assert/strict";
import {
  validateMorningBindingReceipt,
  canAcknowledgeMissingMorningBinding,
} from "../webui/morning-binding-recovery.ts";

const original="morning-bind-001";
const result={
  binding_id:original,chat_id:"2026-morning-001",session_id:"websocket:2026-morning-001",
  date:"2026-10-25",timezone:"Asia/Shanghai",snapshot_sha256:"a".repeat(64),
  order_version:"2",list_id:"list-1",item_id:"task:one",last_request_id:null,
};
const recorded={
  source_type:"SIMULATED",client_request_id:original,outcome:"RECORDED",
  result,adoption_state:"NOT_REVALIDATED_BY_LOOKUP",
  write_performed_by_lookup:false,business_authority_granted:false,
};

test("native morning binding lookup adopts only the exact original session",()=>{
  assert.equal(validateMorningBindingReceipt(recorded,original),recorded);
  assert.equal(canAcknowledgeMissingMorningBinding(recorded,original),false);
});

test("only a valid missing original read permits explicit ending of investigation",()=>{
  const missing={...recorded,outcome:"NOT_FOUND_IN_CURRENT_STORE",result:null};
  assert.equal(validateMorningBindingReceipt(missing,original),missing);
  assert.equal(canAcknowledgeMissingMorningBinding(missing,original),true);
  assert.equal(canAcknowledgeMissingMorningBinding(missing,"a-different-binding"),false);
  assert.equal(canAcknowledgeMissingMorningBinding(null,original),false);
  assert.equal(canAcknowledgeMissingMorningBinding(
    {...missing,result},original),false);
});

test("network errors and malformed/foreign binding receipts never authorize resending",()=>{
  for(const invalid of [
    null,[],
    {...recorded,client_request_id:"other-request"},
    {...recorded,write_performed_by_lookup:true},
    {...recorded,business_authority_granted:true},
    {...recorded,source_type:"PUBLIC_SOURCE"},
    {...recorded,adoption_state:"CURRENT"},
    {...recorded,result:null},
    {...recorded,result:{...result,binding_id:"another-binding"}},
    {...recorded,result:{...result,snapshot_sha256:"not-a-sha"}},
    {...recorded,result:{...result,item_id:"task:one",list_id:null}},
    {...recorded,outcome:"NOT_FOUND_IN_CURRENT_STORE"},
    {...recorded,outcome:"SUCCEEDED"},
  ]){
    assert.throws(()=>validateMorningBindingReceipt(invalid,original),/晨间原会话/);
  }
});

test("whole-day binding without selected item remains valid and cannot grant action",()=>{
  const wholeDay={...recorded,result:{...result,list_id:null,item_id:null}};
  assert.equal(validateMorningBindingReceipt(wholeDay,original),wholeDay);
  assert.equal(canAcknowledgeMissingMorningBinding(wholeDay,original),false);
});
