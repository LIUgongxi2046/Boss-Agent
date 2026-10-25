import test from "node:test";
import assert from "node:assert/strict";
import {
  isActiveN02Scope, sameActiveN02Scope, mayDisplayCurrentTaskReference,
  shouldCancelN02PositionOnInteraction,
} from "../webui/n02-context-guard.ts";

const client={id:"current-provider"};
const active={client,token:"boss-token",chatId:"current-chat",role:"BOSS",
  visible:true,connectionStatus:"open"};
const entry={binding_state:"BOUND",current_use_verified:true,
  entry:{current_use_verified:true}};

test("an actual connected BOSS session is required before task context can be actionable",()=>{
  assert.equal(isActiveN02Scope(active),true);
  for(const change of [
    {role:"MAINTAINER"},{visible:false},{chatId:null},{chatId:""},
    {connectionStatus:"reconnecting"},{connectionStatus:"closed"},
  ])assert.equal(isActiveN02Scope({...active,...change}),false);
});

test("a previously authenticated reference is hidden while revalidating or after failed read",()=>{
  assert.equal(mayDisplayCurrentTaskReference(entry,active,false,""),true);
  assert.equal(mayDisplayCurrentTaskReference(entry,active,true,""),false);
  assert.equal(mayDisplayCurrentTaskReference(entry,active,false,"HTTP 409: source changed"),false);
  assert.equal(mayDisplayCurrentTaskReference(entry,{...active,visible:false},false,""),false);
  assert.equal(mayDisplayCurrentTaskReference(entry,{...active,connectionStatus:"closed"},false,""),false);
  assert.equal(mayDisplayCurrentTaskReference(entry,{...active,role:"MAINTAINER"},false,""),false);
  assert.equal(mayDisplayCurrentTaskReference({...entry,entry:{current_use_verified:false}},active,false,""),false);
  assert.equal(mayDisplayCurrentTaskReference({...entry,current_use_verified:false},active,false,""),false);
  assert.equal(mayDisplayCurrentTaskReference({...entry,binding_state:"UNBOUND"},active,false,""),false);
  assert.equal(mayDisplayCurrentTaskReference(null,active,false,""),false);
});

test("late business-context replies cannot cross authentication, chat or lifecycle",()=>{
  assert.equal(sameActiveN02Scope(active,{...active}),true);
  for(const change of [
    {client:{id:"other"}},{token:"new-token"},{chatId:"different-chat"},
    {role:"MAINTAINER"},{visible:false},{connectionStatus:"closed"},
  ])assert.equal(sameActiveN02Scope(active,{...active,...change}),false);
  assert.equal(sameActiveN02Scope({...active,visible:false},active),false);
});

test("N02 restore retry remains usable by mouse and keyboard",()=>{
  assert.equal(shouldCancelN02PositionOnInteraction("click",null,true),false,
    "click capture must not delete the original URL before retry");
  assert.equal(shouldCancelN02PositionOnInteraction("keydown","Enter",true),false,
    "keyboard Enter on retry must read the same saved original position");
  assert.equal(shouldCancelN02PositionOnInteraction("keydown"," ",true),false);
  assert.equal(shouldCancelN02PositionOnInteraction("keydown","Tab",false),false,
    "Tab and Shift+Tab must be able to reach the retry control");
  assert.equal(shouldCancelN02PositionOnInteraction("click",null,false),true,
    "a new explicit click outside the retry control abandons recovery");
  assert.equal(shouldCancelN02PositionOnInteraction("keydown","Escape",false),true);
  assert.equal(shouldCancelN02PositionOnInteraction("keydown","A",false),true);
});
