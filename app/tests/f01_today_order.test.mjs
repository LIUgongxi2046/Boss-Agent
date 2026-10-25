import test from "node:test";
import assert from "node:assert/strict";
import {
  moveTodayOrderWithinCategory,
  todayOrderPosition,
  validateTodayOrderReceipt,
  withoutTodayOrderRequest,
  isConfirmedMissingTodayOrderReceipt,
} from "../webui/today-order.ts";

const rows = [
  {item_id:"decide-1",category:"DECIDE"},
  {item_id:"coordinate-1",category:"COORDINATE"},
  {item_id:"decide-2",category:"DECIDE"},
  {item_id:"inform-1",category:"INFORM"},
  {item_id:"decide-3",category:"DECIDE"},
];
const order=rows.map(item=>item.item_id);

test("filtered '待决定' moves the next visible item without moving hidden categories",()=>{
  const changed=moveTodayOrderWithinCategory(order,rows,"DECIDE","decide-1",1);
  assert.deepEqual(changed,["decide-2","coordinate-1","decide-1","inform-1","decide-3"]);
  assert.deepEqual(changed.filter(id=>id.startsWith("decide-")),["decide-2","decide-1","decide-3"]);
  assert.equal(changed[1],"coordinate-1");
  assert.equal(changed[3],"inform-1");
  assert.deepEqual(order,rows.map(item=>item.item_id),"original form must remain unchanged until owner saves");
});

test("up and down in a filtered category are symmetrical",()=>{
  const next=moveTodayOrderWithinCategory(order,rows,"DECIDE","decide-2",-1);
  assert.deepEqual(next,["decide-2","coordinate-1","decide-1","inform-1","decide-3"]);
  assert.deepEqual(moveTodayOrderWithinCategory(next,rows,"DECIDE","decide-2",1),order);
});

test("filtered boundary disables moves even with hidden global neighbors",()=>{
  assert.equal(moveTodayOrderWithinCategory(order,rows,"COORDINATE","coordinate-1",-1),null);
  assert.equal(moveTodayOrderWithinCategory(order,rows,"COORDINATE","coordinate-1",1),null);
  assert.deepEqual(todayOrderPosition(order,rows,"DECIDE","decide-1"),{index:0,total:3});
  assert.deepEqual(todayOrderPosition(order,rows,"DECIDE","decide-3"),{index:2,total:3});
  assert.deepEqual(todayOrderPosition(order,rows,"COORDINATE","coordinate-1"),{index:0,total:1});
  assert.deepEqual(todayOrderPosition(order,rows,"DECIDE","inform-1"),{index:-1,total:3});
});

test("global list moves across categories only when ALL is selected",()=>{
  assert.deepEqual(moveTodayOrderWithinCategory(order,rows,"ALL","decide-1",1),
    ["coordinate-1","decide-1","decide-2","inform-1","decide-3"]);
  assert.equal(moveTodayOrderWithinCategory(order,rows,"DECIDE","coordinate-1",1),null);
  assert.equal(moveTodayOrderWithinCategory(order,rows,"ALL","unrecognized",1),null);
});

const savedOrder={
  source_type:"SIMULATED",list_id:"list-r-1",list_version:"1",
  date:"2026-10-25",timezone:"Asia/Shanghai",version:"2",
  snapshot_sha256:"a".repeat(64),item_ids:["task:one","meeting:two"],
  authorization_id:"owner-authorization-1",
};

test("original sorting receipt accepts only exactly matched non-writing recorded evidence",()=>{
  const valid={action:"boss.today.reorder",client_request_id:"r-1",outcome:"RECORDED",result:savedOrder,write_performed_by_lookup:false};
  assert.equal(validateTodayOrderReceipt(valid,"r-1"),valid);
  const missing={...valid,outcome:"NOT_FOUND_IN_CURRENT_STORE",result:null};
  assert.equal(validateTodayOrderReceipt(missing,"r-1"),missing);
  for(const bad of [
    null, [], {action:"boss.today.reorder",client_request_id:"r-1"},
    {...valid,client_request_id:"r-2"},
    {...valid,action:"boss.assignment.send"},
    {...valid,write_performed_by_lookup:true},
    {...valid,outcome:"SUCCEEDED"},
  ]){
    assert.throws(()=>validateTodayOrderReceipt(bad,"r-1"),/回执/);
  }
});

test("recorded outcome without the actual bound order and authorization is never accepted",()=>{
  const valid={action:"boss.today.reorder",client_request_id:"r-1",outcome:"RECORDED",result:savedOrder,write_performed_by_lookup:false};
  for(const bad of [
    {...valid,result:null},
    {...valid,result:undefined},
    {...valid,result:{...savedOrder,authorization_id:""}},
    {...valid,result:{...savedOrder,source_type:"PUBLIC_SOURCE"}},
    {...valid,result:{...savedOrder,item_ids:["task:one","task:one"]}},
    {...valid,result:{...savedOrder,snapshot_sha256:"invalid"}},
    {...valid,outcome:"NOT_FOUND_IN_CURRENT_STORE"},
  ]){
    assert.throws(()=>validateTodayOrderReceipt(bad,"r-1"),/排序原请求|当前库/);
  }
});

test("confirmed saved sort removes only its own URL identifier",()=>{
  const location="http://localhost:11322/?bossPage=F01&morningItem=task%3A123&todayOrderRequest=today-001&morningDate=2026-10-24";
  const normalized=withoutTodayOrderRequest(location,"today-001");
  const next=new URL(normalized);
  assert.equal(next.searchParams.get("todayOrderRequest"),null);
  assert.equal(next.searchParams.get("morningItem"),"task:123");
  assert.equal(next.searchParams.get("bossPage"),"F01");
  assert.equal(next.searchParams.get("morningDate"),"2026-10-24");
  assert.equal(withoutTodayOrderRequest(location,"today-002"),null,
    "a delayed request may not remove another original request");
  assert.equal(withoutTodayOrderRequest(location,""),null);
});

test("a server-confirmed missing request alone unlocks explicit review dismissal",()=>{
  const missing={action:"boss.today.reorder",client_request_id:"today-001",
    outcome:"NOT_FOUND_IN_CURRENT_STORE",result:null,write_performed_by_lookup:false};
  assert.equal(isConfirmedMissingTodayOrderReceipt(missing,"today-001"),true);
  assert.equal(isConfirmedMissingTodayOrderReceipt(null,"today-001"),false);
  assert.equal(isConfirmedMissingTodayOrderReceipt(missing,"today-002"),false);
  assert.equal(isConfirmedMissingTodayOrderReceipt({...missing,outcome:"RECORDED"},"today-001"),false);
  assert.equal(isConfirmedMissingTodayOrderReceipt({...missing,write_performed_by_lookup:true},"today-001"),false);
  assert.equal(isConfirmedMissingTodayOrderReceipt({...missing,action:"boss.assignment.send"},"today-001"),false);
  assert.equal(isConfirmedMissingTodayOrderReceipt(missing,""),false);
  assert.equal(isConfirmedMissingTodayOrderReceipt({...missing,result:savedOrder},"today-001"),false);
});
