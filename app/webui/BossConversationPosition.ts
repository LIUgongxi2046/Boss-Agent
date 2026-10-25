import {useEffect,useRef,useState,type RefObject} from "react";
import type {ThreadReadingPosition,ThreadReadingController} from "@/components/thread/ThreadViewport";

export type ConversationPosition={version:1;chatId:string;reading:ThreadReadingPosition|null;historyOpen:boolean;
  workspaceTop:number;runId:string|null;focusId:string|null};
const parameter="conversationPosition";
function fields(value:unknown,names:string[]):value is Record<string,unknown>{return typeof value==="object"&&value!==null&&!Array.isArray(value)&&Object.keys(value).length===names.length&&names.every(name=>Object.hasOwn(value,name));}
function identifier(value:unknown):value is string{return typeof value==="string"&&value.length>0&&value.length<=700;}
export function readConversationPosition():ConversationPosition|null{
  const encoded=new URL(window.location.href).searchParams.get(parameter);
  if(encoded===null)return null;
  if(encoded.length>4096)throw new Error("原阅读位置记录超过允许范围");
  const value:unknown=JSON.parse(encoded);
  if(!fields(value,["version","chatId","reading","historyOpen","workspaceTop","runId","focusId"])||value.version!==1||!identifier(value.chatId)||typeof value.historyOpen!=="boolean"||
      typeof value.workspaceTop!=="number"||!Number.isFinite(value.workspaceTop)||value.workspaceTop<0||
      !(value.runId===null||identifier(value.runId))||!(value.focusId===null||identifier(value.focusId)))throw new Error("原阅读位置记录无效");
  if(value.reading!==null&&(!fields(value.reading,["conversationKey","promptId","offsetTop"])||value.reading.conversationKey!=="websocket:"+value.chatId||
      !identifier(value.reading.promptId)||typeof value.reading.offsetTop!=="number"||!Number.isFinite(value.reading.offsetTop)))throw new Error("原消息位置与会话不符");
  return value as ConversationPosition;
}
export function writeConversationPosition(value:ConversationPosition|null){
  const url=new URL(window.location.href);
  if(value===null)url.searchParams.delete(parameter);else url.searchParams.set(parameter,JSON.stringify(value));
  window.history.replaceState(window.history.state,"",url);
}

type ReturnOptions=ThreadReadingController&{client:unknown;token:string;role:string;visible:boolean;chatId:string|null;
  loadedSessionId:string|undefined;runIds:string[];selectedRunId:string|null;selectRun:(id:string)=>void;historyOpen:boolean;selectHistoryOpen:(open:boolean)=>void;workspace:RefObject<HTMLDivElement|null>};
export function useConversationReturn(options:ReturnOptions){
  const latest=useRef(options);latest.current=options;
  const saved=useRef<{client:unknown;token:string;chatId:string|null;focus:HTMLElement|null;top:number}|null>(null);
  const active=useRef<AbortController|null>(null);
  const [error,setError]=useState(""),[restoring,setRestoring]=useState(false),[revision,setRevision]=useState(0);
  const {client,token,role,visible,chatId,loadedSessionId}=options;
  useEffect(()=>{
    setError("");setRestoring(false);
    if(role!=="BOSS"||!visible)return;
    if(!chatId){
      const original=saved.current;
      if(original?.chatId===null&&original.client===client&&original.token===token){
        if(latest.current.workspace.current)latest.current.workspace.current.scrollTop=original.top;
        if(original.focus?.isConnected)original.focus.focus({preventScroll:true});saved.current=null;
      }
      return;
    }
    if(loadedSessionId!=="websocket:"+chatId)return;
    const abort=new AbortController();active.current=abort;
    const current=()=>!abort.signal.aborted&&latest.current.client===client&&latest.current.token===token&&latest.current.chatId===chatId&&latest.current.role===role&&latest.current.visible;
    void (async()=>{
      const position=readConversationPosition();
      if(!position||position.chatId!==chatId)return;
      setRestoring(true);
      if(position.runId!==null){
        if(!latest.current.runIds.includes(position.runId))throw new Error("原运行当前无法读取，不能采用其他运行的位置");
        latest.current.selectRun(position.runId);
      }
      latest.current.selectHistoryOpen(position.historyOpen);
      if(position.reading)await latest.current.restoreReadingPosition(position.reading,abort.signal);
      if(!current())return;
      setRestoring(false);
      await new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve())));
      if(!current())return;
      const workspace=latest.current.workspace.current;
      if(!workspace)throw new Error("原会话工作区尚未就绪");
      workspace.scrollTop=position.workspaceTop;
      if(position.focusId!==null){
        const focus=workspace.querySelector<HTMLElement>('[data-conversation-return="'+CSS.escape(position.focusId)+'"]');
        if(!focus)throw new Error("原返回操作当前不可用，请核查原会话记录");
        focus.focus({preventScroll:true});
      }
      writeConversationPosition(null);saved.current=null;
    })().catch(failure=>{if(current()&&!(failure instanceof DOMException&&failure.name==="AbortError"))setError(failure instanceof Error?failure.message:String(failure));}).finally(()=>{if(current())setRestoring(false);if(active.current===abort)active.current=null;});
    return()=>{abort.abort();if(active.current===abort)active.current=null;};
  },[client,token,role,visible,chatId,loadedSessionId,revision]);
  const openBusiness=(action:()=>void,focus:HTMLElement|null=document.activeElement instanceof HTMLElement?document.activeElement:null)=>{
    const current=latest.current;
    saved.current={client:current.client,token:current.token,chatId:current.chatId,focus,top:current.workspace.current?.scrollTop??0};
    if(current.chatId){
      const reading=current.captureReadingPosition();
      if(reading&&reading.conversationKey!=="websocket:"+current.chatId)throw new Error("原生阅读位置不属于当前会话");
      writeConversationPosition({version:1,chatId:current.chatId,reading,historyOpen:current.historyOpen,workspaceTop:saved.current.top,runId:current.selectedRunId,focusId:focus?.dataset.conversationReturn??null});
    }else writeConversationPosition(null);
    action();
  };
  const cancelForInteraction=()=>{
    if(!active.current)return;
    active.current.abort();active.current=null;writeConversationPosition(null);saved.current=null;setError("");setRestoring(false);
  };
  return {openBusiness,cancelForInteraction,error,restoring,retry:()=>setRevision(value=>value+1),clear:()=>{cancelForInteraction();writeConversationPosition(null);setError("");}};
}
