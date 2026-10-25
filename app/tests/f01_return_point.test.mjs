import test from "node:test";
import assert from "node:assert/strict";
import {isSafeMorningFocusId,readMorningReturnPoint} from "../webui/morning-return.ts";

test("task and source object IDs with colon remain eligible for F01 return focus",()=>{
  for(const id of ["morning-item-task:task-123","morning-source-doc:finance.v2","morning-item-event:notice-1","morning-detail-retry"]){
    assert.equal(isSafeMorningFocusId(id),true);
    assert.deepEqual(readMorningReturnPoint(id,"93"),{focus:id,scroll:93});
  }
});

test("valid scroll positions survive refresh without storing business content",()=>{
  assert.deepEqual(readMorningReturnPoint("morning-question","0"),{focus:"morning-question",scroll:0});
  assert.deepEqual(readMorningReturnPoint("morning-prepare","77.5"),{focus:"morning-prepare",scroll:77.5});
});

test("invalid, missing or private-text position references cannot be adopted",()=>{
  for(const focus of [
    null,"","not-morning-task:1","morning-<script>","morning-中文私人文本",
    "morning-item-task:1?secret=abc","morning-"+"x".repeat(257),
  ]){
    assert.equal(readMorningReturnPoint(focus,"93"),null);
  }
  for(const scroll of [null,"","NaN","Infinity","-1"]){
    assert.equal(readMorningReturnPoint("morning-item-task:task-123",scroll),null);
  }
});
