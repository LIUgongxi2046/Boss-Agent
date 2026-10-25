import {useEffect,useRef,useState} from "react";
import {useClient} from "@/providers/ClientProvider";
import type {Overview,OverviewScope,OverviewSelection} from "./business-overview-types";

type TopicReference={page_id:string;use:OverviewSelection["use"]}|null;
export type BusinessEntry={source_type:"RUNTIME_RECORD";store_reference:string;preparation_id:string;client_request_id:string;preparation_sha256:string;prepared_at:string;bound_at:string|null;binding_state:"PREPARED"|"BOUND";context:{session_id:string;chat_id:string;native_session_created_at:string}|null;applied_scope:OverviewScope;scope_sha256:string;topic_reference:TopicReference;topic_sha256:string|null;snapshot_sha256:string;source_references:{kind:"document";id:string;version:string|null;content_sha256:string|null;status:string}[];business_at:string;return_reference:{page_id:"N03";applied_scope:OverviewScope;topic_reference:TopicReference;snapshot_sha256:string};current_use_verified:boolean;business_authorization_granted:false;business_mutation_performed:false};
export type BusinessContext={source_type:"RUNTIME_RECORD";session_id:string;chat_id:string;binding_state:"BOUND"|"UNBOUND";entry:BusinessEntry|null;overview:Overview|null;references:{kind:"document";id:string;version:string}[];current_use_verified:boolean;current_selection_active?:boolean;business_authorization_granted:false;business_mutation_performed:false};
type Receipt={source_type:"RUNTIME_RECORD";client_request_id:string;outcome:"RECORDED"|"NOT_FOUND_IN_CURRENT_STORE";entry:BusinessEntry|null;business_authorization_granted:false;business_mutation_performed:false};
type Pointer={requestId:string;chatId:string|null};
type Props={role:"BOSS"|"MAINTAINER"|null;getToken:()=>string;onCreateChat:()=>Promise<string>;onOpenChat:(chatId:string)=>void;onBeforeStart:(start:()=>void)=>void};
const scopeKeys=["legal_entity_id","region_id","period_start","period_end","timezone","attention"] as const;
function pointerFromUrl():Pointer|null{const query=new URLSearchParams(window.location.search),requestId=query.get("businessConversationRequest");if(!requestId)return null;if(!/^[A-Za-z0-9_.-]{8,128}$/.test(requestId))throw new Error("经营会话原请求编号无效");return {requestId,chatId:query.get("businessConversationChat")};}
function savePointer(pointer:Pointer|null){const address=new URL(window.location.href);for(const key of ["businessConversationRequest","businessConversationChat"])address.searchParams.delete(key);if(pointer){address.searchParams.set("businessConversationRequest",pointer.requestId);if(pointer.chatId)address.searchParams.set("businessConversationChat",pointer.chatId);}window.history.replaceState(window.history.state,"",address);}
export function verifyBusinessEntry(entry:BusinessEntry,requestId:string){
  if(entry.source_type!=="RUNTIME_RECORD"||entry.client_request_id!==requestId||entry.business_authorization_granted!==false||entry.business_mutation_performed!==false||!entry.store_reference||!/^[a-f0-9]{64}$/.test(entry.preparation_sha256)||!/^[a-f0-9]{64}$/.test(entry.snapshot_sha256)||entry.return_reference.page_id!=="N03"||entry.return_reference.snapshot_sha256!==entry.snapshot_sha256||scopeKeys.some(key=>entry.return_reference.applied_scope[key]!==entry.applied_scope[key])||JSON.stringify(entry.return_reference.topic_reference)!==JSON.stringify(entry.topic_reference))throw new Error("经营会话准备与正式范围引用不符");
}
export function verifyBusinessContext(context:BusinessContext,chatId:string){
  if(context.source_type!=="RUNTIME_RECORD"||context.chat_id!==chatId||context.session_id!=="websocket:"+chatId||context.business_authorization_granted!==false||context.business_mutation_performed!==false)throw new Error("经营上下文与当前原生会话不符");
  if(context.binding_state==="BOUND"){
    if(!context.entry||!context.overview||!context.current_use_verified||!context.entry.current_use_verified||context.entry.binding_state!=="BOUND"||context.entry.context?.chat_id!==chatId||context.entry.context.session_id!==context.session_id||context.entry.snapshot_sha256!==context.overview.snapshot_sha256)throw new Error("经营会话缺少当前正式绑定");
    verifyBusinessEntry(context.entry,context.entry.client_request_id);
  }else if(context.binding_state!=="UNBOUND"||context.entry!==null||context.overview!==null||context.current_use_verified!==false)throw new Error("未绑定经营会话包含无效上下文");
}
export function useBusinessConversationEntry({role,getToken,onCreateChat,onOpenChat,onBeforeStart}:Props){
  const {client,token}=useClient();
  const [pointer,setPointer]=useState<Pointer|null>(pointerFromUrl),[entry,setEntry]=useState<BusinessEntry|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState(""),[lookedUp,setLookedUp]=useState(false);
  const epoch=useRef(0),pointerRef=useRef(pointer),latest=useRef({client,token,role,onCreateChat,onOpenChat,onBeforeStart});latest.current={client,token,role,onCreateChat,onOpenChat,onBeforeStart};
  function preserve(value:Pointer|null){pointerRef.current=value;savePointer(value);setPointer(value);}
  function begin(){const current=++epoch.current,identity=latest.current;setBusy(true);setError("");return()=>current===epoch.current&&latest.current.client===identity.client&&latest.current.token===identity.token&&latest.current.role==="BOSS";}
  async function readReceipt(value:Pointer,signal?:AbortSignal){
    const response=await fetch("/api/boss/ui/conversation/business-entry?"+new URLSearchParams({client_request_id:value.requestId}),{headers:{Authorization:"Bearer "+getToken()},cache:"no-store",signal});
    if(!response.ok)throw Object.assign(new Error("原经营会话记录读取失败"),{status:response.status});
    const result=await response.json() as Receipt;
    if(result.source_type!=="RUNTIME_RECORD"||result.client_request_id!==value.requestId||result.business_authorization_granted!==false||result.business_mutation_performed!==false||!["RECORDED","NOT_FOUND_IN_CURRENT_STORE"].includes(result.outcome)||Boolean(result.entry)!==(result.outcome==="RECORDED"))throw new Error("原经营会话回执与当前编号不符");
    if(result.entry){verifyBusinessEntry(result.entry,value.requestId);if(result.entry.current_use_verified!==false)throw new Error("历史回执不能代替当前经营范围核查");}
    return result;
  }
  useEffect(()=>{
    const current=++epoch.current,abort=new AbortController(),saved=pointerFromUrl();setEntry(null);setError("");setLookedUp(false);pointerRef.current=role==="BOSS"?saved:null;setPointer(pointerRef.current);setBusy(role==="BOSS"&&Boolean(saved));
    if(role==="BOSS"&&saved)void readReceipt(saved,abort.signal).then(result=>{if(epoch.current===current){setEntry(result.entry);setLookedUp(true);setBusy(false);}},_reason=>{if(epoch.current===current&&!abort.signal.aborted){setBusy(false);setError("原经营会话尚未取得回执，请核查连接后读取原编号。");}});
    return()=>{++epoch.current;abort.abort();};
  },[client,token,role,getToken]);
  async function openPrepared(original:BusinessEntry,value:Pointer,current:()=>boolean){
    verifyBusinessEntry(original,value.requestId);
    const checked=await client.requestMutation<BusinessEntry>("boss.conversation.business.prepare",{client_request_id:value.requestId,applied_scope:original.applied_scope,snapshot_sha256:original.snapshot_sha256,topic_reference:original.topic_reference});
    if(!current())return;verifyBusinessEntry(checked,value.requestId);
    if(!checked.current_use_verified)throw new Error("经营会话准备尚未重新核查当前资格");
    let chatId=checked.context?.chat_id??value.chatId;
    if(checked.binding_state==="PREPARED"){
      if(!chatId){chatId=await latest.current.onCreateChat();if(!current())return;value={...value,chatId};preserve(value);}
      client.attach(chatId);
      const bound=await client.requestMutation<BusinessEntry>("boss.conversation.business.bind",{client_request_id:value.requestId,preparation_id:checked.preparation_id,preparation_sha256:checked.preparation_sha256,chat_id:chatId});
      if(!current())return;verifyBusinessEntry(bound,value.requestId);setEntry(bound);
      if(bound.binding_state!=="BOUND"||bound.context?.chat_id!==chatId)throw new Error("经营范围尚未绑定原生会话");
    }
    if(!chatId)throw new Error("经营会话原记录缺少实际会话编号");
    client.attach(chatId);
    const context=await client.requestMutation<BusinessContext>("boss.conversation.business.read",{chat_id:chatId,adopt_selection:true});
    if(!current())return;verifyBusinessContext(context,chatId);
    if(context.entry?.preparation_id!==original.preparation_id||context.entry.preparation_sha256!==original.preparation_sha256)throw new Error("当前经营会话与原准备记录不符");
    preserve(null);setEntry(null);setLookedUp(false);latest.current.onOpenChat(chatId);
  }
  async function startNow(selection:OverviewSelection){
    if(latest.current.role!=="BOSS"||pointerRef.current||busy)throw new Error("当前经营会话原请求尚未核查");
    const current=begin(),value={requestId:crypto.randomUUID(),chatId:null};preserve(value);setLookedUp(false);
    const prepared=client.requestMutation<BusinessEntry>("boss.conversation.business.prepare",{client_request_id:value.requestId,applied_scope:selection.scope,snapshot_sha256:selection.snapshot_sha256,topic_reference:selection.page_id?{page_id:selection.page_id,use:selection.use}:null});
    await prepared.then(async result=>{if(!current())return;verifyBusinessEntry(result,value.requestId);setEntry(result);await openPrepared(result,value,current);}).then(()=>{if(current())setBusy(false);},_reason=>{if(current()){setBusy(false);setError("本次经营会话尚未确认，请读取原请求记录。系统不会自动重试或提交问题。");}});
  }
  async function start(selection:OverviewSelection){
    if(pointerRef.current){setError("已有原经营会话请求等待核查，请读取原记录或明确结束本次入口操作。");return;}
    latest.current.onBeforeStart(()=>void startNow(selection));
  }
  async function recover(){if(!pointer)throw new Error("经营会话缺少原请求编号");const current=begin();await readReceipt(pointer).then(result=>{if(current()){setEntry(result.entry);setLookedUp(true);setBusy(false);}},_reason=>{if(current()){setBusy(false);setError("当前尚未取得原经营会话回执，请保留原编号并核查连接。");}});}
  async function resume(){if(!pointer||!entry||!lookedUp)throw new Error("原经营会话记录尚未核查");const current=begin();setLookedUp(false);await openPrepared(entry,pointer,current).then(()=>{if(current())setBusy(false);},_reason=>{if(current()){setBusy(false);setError("原经营范围或会话当前无法采用，请核查原记录及当前资料。");}});}
  const status=pointer||error||busy?<details className="boss-n03-entry-status" open><summary>经营会话范围与原请求</summary>{pointer&&<p>原请求编号：{pointer.requestId}</p>}{entry&&<p>原范围 {entry.applied_scope.legal_entity_id} · {entry.applied_scope.period_start} 至 {entry.applied_scope.period_end}；{entry.binding_state==="BOUND"?"已有会话绑定，当前资格需要核查":"已经准备，尚未绑定会话"}。</p>}{busy&&<p role="status">正在核查经营范围与原生会话。</p>}{error&&<p role="alert">{error}</p>}<div className="boss-n03-actions">{pointer&&<button className="boss-btn" disabled={busy} onClick={()=>void recover()}>读取原经营会话记录</button>}{pointer&&entry&&<button className="boss-btn" disabled={busy||!lookedUp} onClick={()=>latest.current.onBeforeStart(()=>void resume())}>核查并进入原经营会话</button>}{busy&&<button className="boss-btn" onClick={()=>{++epoch.current;setBusy(false);setError("当前交接已停止，已经保存的准备或绑定仍可按原编号核查。");}}>取消当前会话交接</button>}{pointer&&<button className="boss-btn" disabled={busy||!lookedUp} onClick={()=>{preserve(null);setEntry(null);setError("");setLookedUp(false);}}>结束本次入口操作</button>}</div></details>:null;
  return {start,status,busy};
}
