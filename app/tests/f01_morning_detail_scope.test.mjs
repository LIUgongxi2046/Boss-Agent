import test from "node:test";
import assert from "node:assert/strict";
import { currentMorningDetailScope } from "../webui/morning-detail-scope.ts";

test("a date preview cannot enter pending privileged item-detail reads", () => {
  assert.equal(currentMorningDetailScope(null, {list_id: null}), false);
  assert.equal(currentMorningDetailScope(null, {list_id: "preview-only"}), false);
  assert.equal(currentMorningDetailScope(null, null), false);
});

test("the current persisted list and displayed projection must share one ID", () => {
  const list={adoption_state:"CURRENT",result:{list_id:"list-123"}};
  assert.equal(currentMorningDetailScope(list,{list_id:"list-123"}),true);
  assert.equal(currentMorningDetailScope(list,{list_id:"list-456"}),false);
  assert.equal(currentMorningDetailScope(list,{list_id:null}),false);
});

test("historical or invalidated lists never allow current-detail adoption", () => {
  for(const status of ["HISTORICAL_REQUIRES_REQUERY","REVOKED","UNAVAILABLE","NEEDS_REVIEW"]){
    assert.equal(currentMorningDetailScope(
      {adoption_state:status,result:{list_id:"list-123"}},{list_id:"list-123"}),false);
  }
});

test("even a CURRENT status without a persisted list identifier is not sufficient", () => {
  assert.equal(currentMorningDetailScope(
    {adoption_state:"CURRENT",result:{list_id:""}},{list_id:""}),false);
  assert.equal(currentMorningDetailScope(
    {adoption_state:"CURRENT",result:{list_id:null}},{list_id:null}),false);
});
