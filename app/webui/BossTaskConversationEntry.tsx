import {useEffect,useRef,useState} from "react";
import {useClient} from "@/providers/ClientProvider";

export type TaskConversationEntry={
  source_type:"RUNTIME_RECORD";preparation_id:string;client_request_id:string;preparation_sha256:string;
  binding_state:"PREPARED"|"BOUND";context:{session_id:string;chat_id:string}|null;
  task_reference:{kind:"task";id:string;version:string};
  source_references:{kind:"document";id:string;version:string;content_sha256:string}[];
  return_reference:{page_id:"F06";task_id:string;task_version:string};
  current_use_verified:boolean;business_authorization_granted:false;business_mutation_performed:false;
};
export type TaskConversationContext={source_type:"RUNTIME_RECORD";session_id:string;chat_id:string;
  binding_state:"UNBOUND"|"BOUND";entry:TaskConversationEntry|null;current_use_verified:boolean;
  business_authorization_granted:false;business_mutation_performed:false};
type Receipt={source_type:"RUNTIME_RECORD";client_request_id:string;outcome:"RECORDED"|"NOT_FOUND_IN_CURRENT_STORE";
  entry:TaskConversationEntry|null;business_authorization_granted:false;business_mutation_performed:false};
type Pointer={requestId:string;chatId:string|null};
type Props={task:{task_id:string;version?:string}|null;getToken:()=>string;
  onBeforeStart:(start:()=>void)=>void;onCreateChat:()=>Promise<string>;onOpenChat:(id:string)=>void;onReturnTask:(id:string)=>void};

function pointerFromUrl():Pointer|null{
  const params=new URLSearchParams(window.location.search),requestId=params.get("taskConversationRequest");
  if(!requestId)return null;
  if(!/^[A-Za-z0-9_.-]{8,128}$/.test(requestId))throw new Error("任务会话原请求编号无效");
  return {requestId,chatId:params.get("taskConversationChat")};
}
function writePointer(pointer:Pointer|null){
  const url=new URL(window.location.href);
  for(const name of ["taskConversationRequest","taskConversationChat"])url.searchParams.delete(name);
  if(pointer){url.searchParams.set("taskConversationRequest",pointer.requestId);if(pointer.chatId)url.searchParams.set("taskConversationChat",pointer.chatId);}
  window.history.replaceState(window.history.state,"",url);
}
export function verifyTaskEntry(entry:TaskConversationEntry,requestId:string){
  if(entry.source_type!=="RUNTIME_RECORD"||entry.client_request_id!==requestId||
      entry.business_authorization_granted!==false||entry.business_mutation_performed!==false||
      entry.task_reference.kind!=="task"||!entry.task_reference.id||!entry.task_reference.version||
      entry.return_reference.page_id!=="F06"||entry.return_reference.task_id!==entry.task_reference.id||
      entry.return_reference.task_version!==entry.task_reference.version||!entry.source_references.length||
      entry.source_references.some(ref=>ref.kind!=="document"||!ref.id||!ref.version||!/^[a-f0-9]{64}$/.test(ref.content_sha256)))
    throw new Error("任务会话准备记录的范围或来源无效");
}
export function verifyTaskContext(context:TaskConversationContext,chatId:string){
  if(context.source_type!=="RUNTIME_RECORD"||context.chat_id!==chatId||context.session_id!=="websocket:"+chatId||
      context.business_authorization_granted!==false||context.business_mutation_performed!==false)
    throw new Error("当前任务上下文与会话范围不符");
  if(context.binding_state==="BOUND"){
    if(!context.entry||!context.current_use_verified||!context.entry.current_use_verified||
        context.entry.binding_state!=="BOUND"||context.entry.context?.chat_id!==chatId||context.entry.context.session_id!==context.session_id)
      throw new Error("任务入口缺少当前有效绑定");
    verifyTaskEntry(context.entry,context.entry.client_request_id);
  }else if(context.binding_state!=="UNBOUND"||context.entry!==null||context.current_use_verified!==false)
    throw new Error("当前未绑定会话包含无效任务上下文");
}
export function BossTaskConversationEntry({task,getToken,onBeforeStart,onCreateChat,onOpenChat,onReturnTask}:Props){
  const {client,token}=useClient();
  const [pointer,setPointer]=useState<Pointer|null>(pointerFromUrl),[entry,setEntry]=useState<TaskConversationEntry|null>(null);
  const [busy,setBusy]=useState(false),[error,setError]=useState(""),[lookupDone,setLookupDone]=useState(false);
  const epoch=useRef(0),latest=useRef({client,token,id:task?.task_id,version:task?.version,onBeforeStart,onOpenChat});
  latest.current={client,token,id:task?.task_id,version:task?.version,onBeforeStart,onOpenChat};
  const begin=()=>{const current=++epoch.current,scope=latest.current;setBusy(true);setError("");return()=>epoch.current===current&&latest.current.client===scope.client&&latest.current.token===scope.token&&latest.current.id===scope.id&&latest.current.version===scope.version;};
  const preserve=(value:Pointer|null)=>{writePointer(value);setPointer(value);};
  const readReceipt=async(value:Pointer,signal?:AbortSignal)=>{
    const response=await fetch("/api/boss/ui/conversation/task-entry?client_request_id="+encodeURIComponent(value.requestId),{headers:{Authorization:"Bearer "+getToken()},signal});
    if(!response.ok)throw new Error((await response.json()).error??"原任务会话记录读取失败");
    const result=await response.json() as Receipt;
    if(result.source_type!=="RUNTIME_RECORD"||result.client_request_id!==value.requestId||result.business_authorization_granted!==false||result.business_mutation_performed!==false||
        !["RECORDED","NOT_FOUND_IN_CURRENT_STORE"].includes(result.outcome)||Boolean(result.entry)!==(result.outcome==="RECORDED"))throw new Error("原任务会话回执范围不符");
    if(result.entry){verifyTaskEntry(result.entry,value.requestId);if(result.entry.current_use_verified!==false)throw new Error("历史准备记录不能代替当前有效性核查");}
    return result;
  };
  useEffect(()=>{
    const current=++epoch.current,abort=new AbortController(),original=pointerFromUrl();
    setPointer(original);setEntry(null);setError("");setLookupDone(false);setBusy(Boolean(original));
    if(original)void readReceipt(original,abort.signal).then(result=>{if(epoch.current===current){setEntry(result.entry);setLookupDone(true);}}).catch(failure=>{if(epoch.current===current&&!abort.signal.aborted)setError(failure instanceof Error?failure.message:String(failure));}).finally(()=>{if(epoch.current===current)setBusy(false);});
    return()=>{++epoch.current;abort.abort();};
  },[client,token,task?.task_id,task?.version]);
  const recover=async()=>{
    if(!pointer)throw new Error("缺少原任务会话请求编号");
    const current=begin();
    try{const result=await readReceipt(pointer);if(current()){setEntry(result.entry);setLookupDone(true);}}
    catch(failure){if(current())setError(failure instanceof Error?failure.message:String(failure));}
    finally{if(current())setBusy(false);}
  };
  const openPrepared=async(original:TaskConversationEntry,value:Pointer,current:()=>boolean)=>{
    verifyTaskEntry(original,value.requestId);
    if(original.task_reference.id!==task?.task_id||original.task_reference.version!==task?.version)throw new Error("原准备记录与当前选择的任务版本不符，请返回原任务核查");
    let chatId=original.context?.chat_id??value.chatId;
    if(original.binding_state==="PREPARED"){
      if(!chatId){chatId=await onCreateChat();if(!current())return;value={...value,chatId};preserve(value);}
      client.attach(chatId);
      const bound=await client.requestMutation<TaskConversationEntry>("boss.conversation.task.bind",{client_request_id:value.requestId,preparation_id:original.preparation_id,preparation_sha256:original.preparation_sha256,chat_id:chatId});
      if(!current())return;
      verifyTaskEntry(bound,value.requestId);
      if(bound.binding_state!=="BOUND"||bound.context?.chat_id!==chatId)throw new Error("任务准备尚未绑定原会话");
      setEntry(bound);
    }
    if(!chatId)throw new Error("原任务会话绑定缺少会话编号");
    client.attach(chatId);
    const context=await client.requestMutation<TaskConversationContext>("boss.conversation.task.read",{chat_id:chatId});
    if(!current())return;
    verifyTaskContext(context,chatId);
    if(context.entry?.preparation_id!==original.preparation_id||context.entry.preparation_sha256!==original.preparation_sha256||
        context.entry.task_reference.id!==original.task_reference.id||context.entry.task_reference.version!==original.task_reference.version)
      throw new Error("当前会话与原任务准备摘要不符");
    const verifiedChatId=chatId;
    latest.current.onBeforeStart(()=>{
      if(!current())return;
      preserve(null);setEntry(null);latest.current.onOpenChat(verifiedChatId);
    });
  };
  const start=async()=>{
    if(!task?.version||pointer||latest.current.id!==task.task_id||latest.current.version!==task.version)throw new Error("当前任务版本或原请求状态尚未确认");
    const current=begin(),value={requestId:crypto.randomUUID(),chatId:null};
    preserve(value);setLookupDone(false);
    try{
      const prepared=await client.requestMutation<TaskConversationEntry>("boss.conversation.task.prepare",{client_request_id:value.requestId,task_id:task.task_id,task_version:task.version});
      if(!current())return;
      verifyTaskEntry(prepared,value.requestId);setEntry(prepared);
      await openPrepared(prepared,value,current);
    }catch(failure){if(current()){setLookupDone(false);setError((failure instanceof Error?failure.message:String(failure))+"。请读取原请求记录核查，系统不会自动重试。");}}
    finally{if(current())setBusy(false);}
  };
  const continueOriginal=async()=>{
    if(!pointer||!entry||!lookupDone)throw new Error("原任务会话记录尚未核查");
    const current=begin();setLookupDone(false);
    try{await openPrepared(entry,pointer,current);}
    catch(failure){if(current())setError((failure instanceof Error?failure.message:String(failure))+"。请读取原请求记录核查。");}
    finally{if(current())setBusy(false);}
  };
  return <section className="boss-panel" aria-label="任务会话入口">
    <h3>围绕当前任务继续沟通</h3>
    <p>{task?task.task_id+" · 当前显示版本 "+(task.version??"尚未读取"):"请选择已经保存的任务"}</p>
    <p>新建会话会保留选定任务及来源版本。进入后由本人提交问题；任务变更通过正式交办入口确认。</p>
    {pointer?<>
      <p>原请求编号：<span data-task-conversation-request>{pointer.requestId}</span></p>
      {entry&&<p data-task-conversation-original>原任务 {entry.task_reference.id} · 版本 {entry.task_reference.version} · {entry.binding_state==="BOUND"?"已有绑定记录，当前有效性待核查":"已有准备记录，尚未绑定会话"}</p>}
      <div className="boss-actions">
        <button className="boss-btn" disabled={busy} onClick={()=>void recover()}>读取原任务会话记录</button>
        {entry&&<button className="boss-btn" disabled={busy||!lookupDone||entry.task_reference.id!==task?.task_id||entry.task_reference.version!==task?.version} onClick={()=>onBeforeStart(()=>void continueOriginal())}>继续原任务会话</button>}
        {entry&&<button className="boss-btn" disabled={busy} onClick={()=>onReturnTask(entry.task_reference.id)}>返回原任务核查</button>}
        <button className="boss-btn" disabled={busy||!lookupDone} onClick={()=>{preserve(null);setEntry(null);setError("");setLookupDone(false);}}>结束本次入口操作</button>
      </div>
      {lookupDone&&!entry&&<p>当前应用没有这项准备记录。可结束本次入口操作，重新选择任务；原请求不会自动重放。</p>}
    </>:<button className="boss-btn boss-btn-primary" disabled={busy||!task?.version} onClick={()=>onBeforeStart(()=>void start())}>新建当前任务会话</button>}
    {busy&&<p role="status">正在核查任务与会话记录</p>}
    {error&&<p role="alert">{error}</p>}
  </section>;
}
