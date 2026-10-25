import test from "node:test";
import assert from "node:assert/strict";
import {prepareMorningAssignmentContext} from "../webui/morning-assignment-context.ts";

const original={
  list_id:"morning-list-1",list_version:"2",item_id:"meeting:1",
  snapshot_sha256:"a".repeat(64),
};
const source=(id,version="1")=>({source_id:id,version,source_type:"SIMULATED"});
const document=(id,version="1")=>({kind:"document",id,version});
function detail(overrides={}){
  return {
    source_type:"SIMULATED",
    list_id:original.list_id,list_version:original.list_version,
    snapshot_sha256:original.snapshot_sha256,
    business_authorization_granted:false,
    item:{
      item_id:original.item_id,
      source_refs:[document("meeting-minutes","3"),document("sim-doc-quality","2"),{kind:"event",id:"event-1",version:"4"}],
      related_meetings:[{kind:"meeting",id:"meeting-1",version:"7"}],
    },
    documents:[source("meeting-minutes","3"),source("sim-doc-quality","2")],
    ...overrides,
  };
}

test("F01 -> F06 includes current item documents outside old finance/alert whitelist",()=>{
  assert.deepEqual(prepareMorningAssignmentContext(original,detail()),{
    source_ids:["meeting-minutes","sim-doc-quality"],
    meeting_id:"meeting-1",
    event_ids:["event-1"],
  });
});

test("current item without a linked meeting or event does not invent either",()=>{
  const selected=detail({item:{
    item_id:original.item_id,
    source_refs:[document("sim-doc-operations","2")],
    related_meetings:[],
  },documents:[source("sim-doc-operations","2")]});
  assert.deepEqual(prepareMorningAssignmentContext(original,selected),{
    source_ids:["sim-doc-operations"],meeting_id:null,event_ids:[],
  });
});

test("no document does not grant creation authority or substitute a fake default",()=>{
  const selected=detail({item:{item_id:original.item_id,source_refs:[],related_meetings:[]},documents:[]});
  assert.deepEqual(prepareMorningAssignmentContext(original,selected),{
    source_ids:[],meeting_id:null,event_ids:[],
  });
});

test("wrong list, item, version, snapshot or source type is rejected before preparing",()=>{
  const variants=[
    {list_id:"morning-list-2"},
    {list_version:"3"},
    {snapshot_sha256:"b".repeat(64)},
    {item:{...detail().item,item_id:"event:2"}},
    {source_type:"PUBLIC_SOURCE"},
    {business_authorization_granted:true},
  ];
  for(const changed of variants){
    assert.throws(()=>prepareMorningAssignmentContext(original,detail(changed)),/晨间清单或选中事项/);
  }
});

test("missing, changed, repeated, unrelated or non-simulated document never silently enters an assignment",()=>{
  for(const documents of [
    [source("meeting-minutes","3")],
    [source("meeting-minutes","4"),source("sim-doc-quality","2")],
    [source("meeting-minutes","3"),source("sim-doc-unrelated","2")],
    [source("meeting-minutes","3"),source("meeting-minutes","3")],
    [source("meeting-minutes","3"),{...source("sim-doc-quality","2"),source_type:"PUBLIC_SOURCE"}],
  ]){
    assert.throws(()=>prepareMorningAssignmentContext(original,detail({documents})),/来源/);
  }
});

test("repeated and versionless item references are not normalized into false evidence",()=>{
  for(const sources of [
    [document("meeting-minutes","3"),document("meeting-minutes","3")],
    [document("meeting-minutes",null),document("sim-doc-quality","2")],
  ]){
    assert.throws(()=>prepareMorningAssignmentContext(original,detail({item:{...detail().item,source_refs:sources}})),/来源/);
  }
});

test("unverified meeting and event association cannot be silently added",()=>{
  const current=detail();
  assert.throws(()=>prepareMorningAssignmentContext(original,detail({
    item:{...current.item,related_meetings:[{kind:"event",id:"meeting-1",version:"1"}]},
  })),/会议/);
  assert.throws(()=>prepareMorningAssignmentContext(original,detail({
    item:{...current.item,source_refs:[
      ...current.item.source_refs,
      {kind:"event",id:"event-1",version:"4"},
    ]},
  })),/事件/);
});
