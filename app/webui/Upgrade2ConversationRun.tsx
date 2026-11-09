import {useEffect, useLayoutEffect, useMemo, useRef, useState} from "react";
import {useClient} from "@/providers/ClientProvider";
import {RunApiError, RunHttpError, Upgrade2RunClient, validateRunCatalogue} from "./upgrade2-run-client";
import {Upgrade2RunPanel} from "./Upgrade2RunPanel";
import {Upgrade2ArtifactList,type ListedArtifact} from "./Upgrade2ArtifactList";
import {useUpgrade2Run, type Upgrade2Projection} from "./useUpgrade2Run";
import {RequiredOutputs} from "./RequiredOutputs";
import type {CreateMethodCatalog,DispatchInspection,MethodSelection,RequiredOutput} from "./upgrade2-run-client";
import {Upgrade2ResumeStatus} from "./Upgrade2ResumeStatus";
import {Upgrade2CompletionInspection} from "./Upgrade2CompletionInspection";
import {RunInputReceiptStatus} from "./RunInputReceiptStatus";
import {Upgrade2SourceHistory,type HistoryReference} from "./Upgrade2SourceHistory";
import {Upgrade2MethodSelection} from "./Upgrade2MethodSelection";
import {Upgrade2ObjectSelection} from "./Upgrade2ObjectSelection";
import Ajv2020 from "ajv/dist/2020";
import addFormats from "ajv-formats";
import artifactSchema from "../../validation/agent_artifact_schema.json";

const pendingSchema = new Ajv2020({strictTypes:false,allowUnionTypes:true});
addFormats(pendingSchema); pendingSchema.addSchema(artifactSchema);
const validatePending = pendingSchema.getSchema("urn:boss-agent:artifact-projection:1#/$defs/pending_requests");
if (!validatePending) throw new Error("成果待核查请求 Schema 未找到");

export function PendingArtifactRequests({runId,token,getToken,connected}:{runId:string;token:string;getToken:()=>string;connected:boolean}) {
  const [items,setItems]=useState<{request_key:string;artifact_id:string}[]|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const epoch=useRef(0);
  useLayoutEffect(()=>{epoch.current++;setItems(null);setBusy(false);setError("");return()=>{epoch.current++;};},[runId,token,connected]);
  async function read(){
    if(!connected||!token||getToken()!==token||busy)return;
    const current=++epoch.current;setItems(null);setError("");setBusy(true);
    try {
      const response=await fetch("/api/v2/runs/"+encodeURIComponent(runId)+"/artifact-pending-requests",{headers:{Authorization:"Bearer "+token},credentials:"same-origin",cache:"no-store",redirect:"error"});
      if(!response.ok){if(response.status===401&&current===epoch.current&&getToken()===token)window.dispatchEvent(new Event("boss-auth-expired"));throw new Error("待核查成果读取失败，HTTP "+response.status+"。");}
      const value:unknown=await response.json();
      if(!validatePending!(value))throw new Error("待核查成果响应不符合 Schema");
      const result=value as {run_id:string;requests:{run_id:string;request_key:string;artifact_id:string;status:string;artifact:unknown}[]};
      if(result.run_id!==runId||result.requests.some(item=>item.run_id!==runId||item.status!=="RECONCILING"||item.artifact!==null))throw new Error("待核查成果与当前运行不一致");
      if(current===epoch.current&&getToken()===token)setItems(result.requests);
    } catch(reason) {if(current===epoch.current&&getToken()===token)setError(reason instanceof Error?reason.message:String(reason));}
    finally {if(current===epoch.current)setBusy(false);}
  }
  return <section className="upgrade2-run-card" aria-label="待核查成果请求"><h3>待核查成果请求</h3>
    <p>来源撤销后，文件状态尚未确认的请求会保留供核查。</p>
    <button className="boss-btn" type="button" disabled={!connected||busy||!token||getToken()!==token} onClick={()=>void read()}>读取待核查请求</button>
    {busy&&<p role="status">正在读取待核查请求。</p>}{error&&connected&&<p role="alert">{error}</p>}
    {connected&&getToken()===token&&items!==null&&(items.length?<ul>{items.map(item=><li key={item.request_key}>原请求 {item.request_key} · 成果 {item.artifact_id} · 文件结果待核查</li>)}</ul>:<p>当前没有来源撤销后的待核查请求。</p>)}
  </section>;
}

export type Upgrade2ConversationBinding = {
  chatId: string;
  conversationId: string;
  runId: string;
  authToken: string;
  identityKey: string;
  pendingScopeKey: string;
  projection: Upgrade2Projection | null;
};

type DesktopExport = {exportArtifact: (request: {artifact_id: string; run_id: string; version: number; token: string}) => Promise<{canceled: boolean}>};

export function Upgrade2ConversationRun({binding, connected, onOpenTask, onOpenTaskReceipt, onOpenMeeting, onOpenMinutes, onOpenSource}: {binding: Upgrade2ConversationBinding; connected: boolean; onOpenTask: (id: string) => void; onOpenTaskReceipt:(id:string,version:string)=>void; onOpenMeeting:(id:string,version:string)=>void; onOpenMinutes:(id:string,version:string)=>void; onOpenSource: (id: string, version: string, locator?: string) => void}) {
  const {getToken} = useClient();
  const client = useMemo(() => new Upgrade2RunClient({getToken}), [getToken]);
  const state = useUpgrade2Run({client, identityKey: binding.identityKey, pendingScopeKey: binding.pendingScopeKey,
    runId: binding.runId, conversationId: binding.conversationId, authToken: binding.authToken, connected, projection: binding.projection});
  const completionFinish = [...state.panelProps.events].reverse().find(event => event.type === "RUN_FINISHED");
  const [exportBusy, setExportBusy] = useState(false);
  const [objectBusy,setObjectBusy]=useState(false);
  const [exportError, setExportError] = useState("");
  const [history,setHistory]=useState<HistoryReference|null>(null);
  const exporting = useRef(false);
  const live = useRef(true);
  const latest = useRef({binding, connected});
  latest.current = {binding, connected};
  useEffect(() => { live.current = true; return () => { live.current = false; }; }, []);
  const desktop = (window as Window & {bossDesktop?: Partial<DesktopExport>}).bossDesktop;
  function exportArtifact(artifactId: string, version: number, listed?: ListedArtifact) {
    const run = state.panelProps.run;
    const artifact = listed ?? run?.artifacts.find(item => item.artifact_id === artifactId && item.version === version);
    if (!desktop?.exportArtifact || exporting.current || !connected || getToken() !== binding.authToken ||
        state.panelProps.loading || state.panelProps.busy || state.panelProps.error || state.panelProps.connection !== "CONNECTED" ||
        !run || run.run_id !== binding.runId || !run.allowed_actions.includes("EXPORT_ARTIFACT") ||
        !artifact || artifact.artifact_id !== artifactId || artifact.version !== version || artifact.run_id !== run.run_id || artifact.status !== "PUBLISHED" || artifact.verification_status !== "VERIFIED") return;
    const started = binding;
    const active = () => live.current && latest.current.connected && latest.current.binding.identityKey === started.identityKey &&
      latest.current.binding.pendingScopeKey === started.pendingScopeKey && latest.current.binding.runId === started.runId &&
      latest.current.binding.chatId === started.chatId && latest.current.binding.conversationId === started.conversationId &&
      latest.current.binding.authToken === started.authToken && getToken() === started.authToken;
    exporting.current = true;
    setExportBusy(true); setExportError("");
    const result = desktop.exportArtifact({artifact_id: artifactId, run_id: run.run_id, version, token: binding.authToken});
    void result.catch(reason => { if (active()) setExportError(reason instanceof Error ? reason.message : String(reason)); })
      .finally(() => { exporting.current = false; if (active()) setExportBusy(false); });
  }
  return <>
    <Upgrade2RunPanel {...state.panelProps} busy={state.panelProps.busy || exportBusy || objectBusy} onReload={() => void state.refresh()} onExportArtifact={desktop?.exportArtifact ? exportArtifact : undefined} onOpenSource={source => {if(source.result_event_id&&source.content_sha256)setHistory({run_id:binding.runId,event_id:source.result_event_id,source_id:source.source_id,version:source.revision,sha256:source.content_sha256,locator:source.locator});else onOpenSource(source.source_id, source.revision, source.locator);}}/>
    {state.snapshot&&<Upgrade2ObjectSelection key={JSON.stringify([binding.identityKey,binding.pendingScopeKey,binding.runId])} client={client} snapshot={state.snapshot} connected={connected} enabled={!state.panelProps.loading&&!state.panelProps.busy&&!state.panelProps.error&&!exportBusy&&!state.pending&&!state.decisionPending} token={binding.authToken} getToken={getToken} pendingScopeKey={binding.pendingScopeKey} onBlockChange={setObjectBusy}/>}
    {state.snapshot&&<Upgrade2MethodSelection key={state.snapshot.run_id+":"+state.snapshot.goal_revision} catalog={connected&&!state.panelProps.loading&&!state.panelProps.error&&getToken()===binding.authToken?state.methodCatalog:null} allowed={connected&&!state.panelProps.loading&&!state.panelProps.busy&&!state.panelProps.error&&!exportBusy&&!objectBusy&&getToken()===binding.authToken&&state.snapshot.allowed_actions.includes("SELECT_METHOD")&&!!state.methodCatalog?.selection_allowed} onSelect={state.selectMethod}/>}
    {state.methodReceipt&&state.snapshot&&connected&&!state.panelProps.loading&&!state.panelProps.busy&&!state.panelProps.error&&<p role="status">方法选择原请求 {state.methodReceipt.request_key} · 目标版本 {state.methodReceipt.goal_revision} · {state.methodReceipt.goal_revision===state.snapshot.goal_revision?"当前目标版本":state.methodReceipt.goal_revision<state.snapshot.goal_revision?"历史目标版本":"运行状态需要重新读取"} · 输入 {state.methodReceipt.input_id} · {state.methodReceipt.method_selection.sop_id} · 版本 {state.methodReceipt.method_selection.version} · 摘要 {state.methodReceipt.method_selection.content_sha256}。已选择，实际采用仍需核查。</p>}
    {history&&connected&&!state.panelProps.loading&&!state.panelProps.busy&&!state.panelProps.error&&state.panelProps.result?.event_id===history.event_id&&<Upgrade2SourceHistory key={JSON.stringify(history)} reference={history} token={binding.authToken} getToken={getToken} onClose={()=>setHistory(null)}/>}
    {state.snapshot?.status==="WAITING_INPUT"&&connected&&!state.panelProps.loading&&!state.panelProps.busy&&!state.panelProps.error&&<Upgrade2ResumeStatus client={client} snapshot={state.snapshot} token={binding.authToken} getToken={getToken} onAccessDenied={state.invalidateAccess}/>}
    {state.snapshot&&["FAILED","SUCCEEDED"].includes(state.snapshot.status)&&connected&&!state.panelProps.loading&&!state.panelProps.busy&&!state.panelProps.error&&<Upgrade2CompletionInspection client={client} runId={state.snapshot.run_id} runRevision={state.snapshot.revision} goalRevision={state.snapshot.goal_revision} token={binding.authToken} getToken={getToken} finishEventId={completionFinish?.event_id} onAccessDenied={state.invalidateAccess}/>}
    <Upgrade2ArtifactList runId={binding.runId} goalRevision={state.snapshot?.goal_revision??null} token={binding.authToken} getToken={getToken} connected={connected&&!state.panelProps.error} onOpenSource={onOpenSource}
      allowOpen={!!state.panelProps.run?.allowed_actions.includes("OPEN_ARTIFACT")&&!state.panelProps.loading&&!state.panelProps.busy&&!state.panelProps.error}
      allowExport={!!state.panelProps.run?.allowed_actions.includes("EXPORT_ARTIFACT")&&!state.panelProps.loading&&!state.panelProps.busy&&!state.panelProps.error}
      onExport={desktop?.exportArtifact?item=>exportArtifact(item.artifact_id,item.version,item):undefined}/>
    <PendingArtifactRequests key={JSON.stringify([binding.identityKey,binding.pendingScopeKey,binding.conversationId,binding.runId,binding.authToken,connected])} runId={binding.runId} token={binding.authToken} getToken={getToken} connected={connected}/>
    {exportError && <p role="alert" className="boss-n02-note error">{exportError}</p>}
    <button className="boss-btn" type="button" disabled={!connected || state.panelProps.loading || state.requestBusy} onClick={() => void state.refresh()}>重新读取运行</button>
    {state.pending && <button className="boss-btn" type="button" disabled={!connected || state.panelProps.loading || state.requestBusy} onClick={() => void state.reconcile()}>查询原请求结果</button>}
    {(state.decisionPending || state.lastDecision && !state.decisionReceipt) && <button className="boss-btn" type="button" disabled={!connected || state.requestBusy} onClick={() => void state.reconcileDecision()}>查询原本人决定</button>}
    {state.decisionReceipt && <div role="status">
      <p>本人决定请求 {state.decisionReceipt.request_key} · 意图 {state.decisionReceipt.receipt.intent_id} · 状态 {state.decisionReceipt.receipt.status} · 版本 {state.decisionReceipt.receipt.revision}</p>
      {state.decisionReceipt.receipt.authorization_id && <p>授权 {state.decisionReceipt.receipt.authorization_id} · 结果 {state.decisionReceipt.receipt.result_ref}{state.decisionReceipt.receipt.task_id&&" · 任务 "+state.decisionReceipt.receipt.task_id}</p>}
      {state.decisionReceipt.receipt.action&&<><p>动作 {state.decisionReceipt.receipt.action} · 目标版本 {state.decisionReceipt.receipt.goal_revision} · 对象 {state.decisionReceipt.receipt.business_object_id} · 版本 {state.decisionReceipt.receipt.business_object_version}</p>{state.decisionReceipt.receipt.source_refs?.map(source=><p key={source.source_id}>来源 {source.source_id} · 版本 {source.version} · 摘要 {source.source_sha256}</p>)}</>}
      {state.decisionReceipt.receipt.status==="SUCCEEDED"&&["boss.meeting.confirm","boss.meeting.cancel","boss.meeting.held"].includes(state.decisionReceipt.receipt.action??"")&&state.decisionReceipt.receipt.business_object_id&&state.decisionReceipt.receipt.business_object_version&&<button type="button" className="boss-btn" disabled={!connected||state.panelProps.loading||state.requestBusy} onClick={()=>onOpenMeeting(state.decisionReceipt!.receipt.business_object_id!,state.decisionReceipt!.receipt.business_object_version!)}>打开会议并重新读取</button>}
      {state.decisionReceipt.receipt.status==="SUCCEEDED"&&state.decisionReceipt.receipt.action==="boss.minutes.confirm"&&state.decisionReceipt.receipt.business_object_id&&state.decisionReceipt.receipt.business_object_version&&<button type="button" className="boss-btn" disabled={!connected||state.panelProps.loading||state.requestBusy} onClick={()=>onOpenMinutes(state.decisionReceipt!.receipt.business_object_id!,state.decisionReceipt!.receipt.business_object_version!)}>打开纪要并重新读取</button>}
      {state.decisionReceipt.receipt.status === "SUCCEEDED" && state.decisionReceipt.receipt.task_id && <button type="button" className="boss-btn" disabled={!connected || state.panelProps.loading || state.requestBusy} onClick={() => onOpenTask(state.decisionReceipt!.receipt.task_id!)}>打开交办并重新读取</button>}
      {state.decisionReceipt.receipt.status==="SUCCEEDED"&&["boss.assignment.create","boss.minutes.assignment.create"].includes(state.decisionReceipt.receipt.action??"")&&state.decisionReceipt.receipt.business_object_id&&state.decisionReceipt.receipt.business_object_version&&<button type="button" className="boss-btn" disabled={!connected||state.panelProps.loading||state.requestBusy} onClick={()=>onOpenTaskReceipt(state.decisionReceipt!.receipt.business_object_id!,state.decisionReceipt!.receipt.business_object_version!)}>打开交办并重新读取</button>}
    </div>}
    {state.receipt && ("input_id" in state.receipt.receipt
      ? <div><p>原请求 {state.receipt.request_key} 已记录 · 动作 {state.receipt.operation} · 运行 {state.receipt.run_id}</p><RunInputReceiptStatus receipt={state.receipt.receipt} currentGoalRevision={state.snapshot?.goal_revision??null}/></div>
      : <div role="status"><p>原请求 {state.receipt.request_key} 已记录 · 动作 {state.receipt.operation} · 运行 {state.receipt.run_id}</p><p>运行状态 {state.receipt.receipt.status} · 版本 {state.receipt.receipt.revision}</p></div>)}
  </>;
}

type SourceReference = {source_id: string; version: string};
type Catalogue = {projection: string; chat_id: string; session_id: string; execution_namespace: string; dataset_version: string; context_version: string; selected_sources: SourceReference[]};
type EntryScope = {owner: string; namespace: string; dataset: string; context: string; sources: SourceReference[]};
type SavedRun = {pending: string | null; runId: string | null; dispatch?:{requestKey:string;revision:number}|null;pendingMethod?:MethodSelection|null;pendingRefs?:string[]|null};

function savedRun(key: string): SavedRun {
  const raw = localStorage.getItem(key);
  if (raw === null) return {pending: null, runId: null};
  const value: unknown = JSON.parse(raw);
  if (!value || typeof value !== "object" || !("pending" in value) || !("runId" in value) ||
      !(value.pending === null || typeof value.pending === "string" && value.pending.trim()) ||
      !(value.runId === null || typeof value.runId === "string" && value.runId.trim())) throw new Error("已保存的运行记录无效");
  const dispatch="dispatch" in value?value.dispatch:null;
  if(dispatch!==null&&(!dispatch||typeof dispatch!=="object"||!("requestKey" in dispatch)||typeof dispatch.requestKey!=="string"||!dispatch.requestKey.trim()||!("revision" in dispatch)||typeof dispatch.revision!=="number"||!Number.isSafeInteger(dispatch.revision)||dispatch.revision<0||!value.runId))throw new Error("已保存的派发请求无效");
  const method="pendingMethod" in value?value.pendingMethod:null;
  if(method!==null&&(!method||typeof method!=="object"||!("sop_id" in method)||typeof method.sop_id!=="string"||!method.sop_id.trim()||!("version" in method)||typeof method.version!=="string"||!method.version.trim()||!("content_sha256" in method)||typeof method.content_sha256!=="string"||!/^[0-9a-f]{64}$/.test(method.content_sha256)))throw new Error("原创建方法记录无效");
  const refs="pendingRefs" in value?value.pendingRefs:null;
  if(refs!==null&&(!Array.isArray(refs)||refs.some(ref=>typeof ref!=="string"||!ref.trim())||new Set(refs).size!==refs.length))throw new Error("原创建来源记录无效");
  return {pending: value.pending as string | null, runId: value.runId as string | null,dispatch:dispatch as SavedRun["dispatch"],pendingMethod:method as MethodSelection|null,pendingRefs:refs as string[]|null};
}

export function DispatchRecoveryInspection({client,runId,requestKey,revision,storageKey,token,getToken,connected}:{client:Upgrade2RunClient;runId:string;requestKey:string;revision:number;storageKey:string;token:string;getToken:()=>string;connected:boolean}){
  const [result,setResult]=useState<DispatchInspection|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const epoch=useRef(0);
  const controller=useRef<AbortController|null>(null);
  function matches(){const current=savedRun(storageKey);return current.runId===runId&&current.dispatch?.requestKey===requestKey&&current.dispatch.revision===revision;}
  useLayoutEffect(()=>{
    epoch.current++;setResult(null);setError("");setBusy(false);
    const changed=(event:StorageEvent)=>{if(event.key===storageKey){epoch.current++;controller.current?.abort();setResult(null);setError("");setBusy(false);}};
    window.addEventListener("storage",changed);
    return()=>{epoch.current++;controller.current?.abort();window.removeEventListener("storage",changed);};
  },[client,runId,requestKey,revision,storageKey,token,connected]);
  async function inspect(){
    if(!connected||!token||getToken()!==token||busy)return;
    const current=++epoch.current;const abort=new AbortController();controller.current=abort;setResult(null);setError("");setBusy(true);
    const active=()=>current===epoch.current&&!abort.signal.aborted&&getToken()===token&&matches();
    try{
      if(!matches())throw new Error("原派发请求已经变化");
      const receipt=await client.dispatchReceipt(runId,revision,requestKey,abort.signal);
      if(!active())return;
      const inspection=await client.dispatchInspection(runId,requestKey,abort.signal);
      if(!active())return;
      if(inspection.receipt_state!==receipt.state||inspection.lease_epoch!==receipt.lease_epoch)throw new Error("派发状态已经变化，请重新核查。");
      setResult(inspection);
    }catch(reason){
      if(current===epoch.current&&!abort.signal.aborted&&getToken()===token){
        if((reason instanceof RunApiError||reason instanceof RunHttpError)&&reason.status===401)window.dispatchEvent(new Event("boss-auth-expired"));
        setError(reason instanceof Error?reason.message:String(reason));
      }
    }finally{if(current===epoch.current){setBusy(false);if(controller.current===abort)controller.current=null;}}
  }
  return <section className="upgrade2-run-card" aria-label="原派发核查">
    <button type="button" className="boss-btn" disabled={!connected||!token||busy} onClick={()=>void inspect()}>核查派发租约与进程</button>
    <p>原派发状态未确定时不会自动重试。</p>
    {error&&connected&&<p role="alert">{error}</p>}
    {result&&connected&&getToken()===token&&<div role="status"><p>派发状态 {result.receipt_state} · 运行状态 {result.run_status}</p>
      <p>原租约期次 {result.lease_epoch} · 当前期次 {result.current_lease_epoch} · 主体{result.lease_owner_matches?"一致":"已经变化"} · 到期时间 {result.lease_expires_at??"未提供"}</p>
      <p>并发预留 {result.reservation_state} · 进程状态 {result.process_state} · 退出码 {result.exit_code??"未提供"} · 退出范围 {result.exit_scope??"未提供"}</p>
      <p>自动重试：禁止。</p></div>}
  </section>;
}

export function Upgrade2ConversationEntry({chatId, token, connected, onOpenTask, onOpenTaskReceipt, onOpenMeeting, onOpenMinutes, onOpenSource}: {chatId: string; token: string; connected: boolean; onOpenTask: (id: string) => void; onOpenTaskReceipt:(id:string,version:string)=>void; onOpenMeeting:(id:string,version:string)=>void; onOpenMinutes:(id:string,version:string)=>void; onOpenSource: (id: string, version: string, locator?: string) => void}) {
  const {client, getToken} = useClient();
  const runClient = useMemo(() => new Upgrade2RunClient({getToken}), [getToken]);
  const identityKey = useRef(crypto.randomUUID()).current;
  const live = useRef(true);
  const scopeGeneration = useRef(0);
  const submitting = useRef(false);
  const operation = useRef<AbortController|null>(null);
  const [scope, setScope] = useState<EntryScope | null>(null);
  const [stored, setStored] = useState<SavedRun>({pending: null, runId: null});
  const [goal, setGoal] = useState("");
  const [outputs,setOutputs]=useState<RequiredOutput[]>([]);
  const [methodCatalog,setMethodCatalog]=useState<CreateMethodCatalog|null>(null);
  const [method,setMethod]=useState<MethodSelection|null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const storageKey = scope ? "boss:upgrade2:create:" + JSON.stringify([scope.owner, scope.namespace, scope.dataset, chatId]) : "";
  const current = () => live.current && connected && getToken() === token;

  async function catalogue(): Promise<Catalogue> {
    const value: unknown = await client.requestMutation("boss.conversation.sources.list", {chat_id: chatId, query: ""});
    validateRunCatalogue(value);
    const result = value as Catalogue;
    if (result.chat_id !== chatId || result.session_id !== "websocket:" + chatId) throw new Error("资料选择与当前会话不一致");
    return result;
  }

  async function verifyEntryIdentity(expected:EntryScope,signal:AbortSignal){
    const response=await fetch("/api/boss/identity",{headers:{Authorization:"Bearer "+token},credentials:"same-origin",cache:"no-store",redirect:"error",signal});
    if(!response.ok)throw new RunHttpError(response.status,await response.text());
    const identity:unknown=await response.json();
    if(!identity||typeof identity!=="object"||!("role" in identity)||identity.role!=="BOSS"||!("owner_id" in identity)||identity.owner_id!==expected.owner||!("execution_namespace" in identity)||identity.execution_namespace!==expected.namespace){setScope(null);setMethod(null);setMethodCatalog(null);throw new Error("本人身份或执行空间已经变化，请重新核查");}
  }

  useLayoutEffect(() => {
    live.current = true;
    const generation = ++scopeGeneration.current;
    const active = () => current() && generation === scopeGeneration.current;
    const controller = new AbortController();
    setScope(null); setError(""); setBusy(false);setMethod(null);setMethodCatalog(null);
    void (async () => {
      const response = await fetch("/api/boss/identity", {headers: {Authorization: "Bearer " + token}, cache: "no-store", signal: controller.signal});
      if (!response.ok) throw new Error("HTTP " + response.status + "：" + await response.text());
      const identity: unknown = await response.json();
      if (!identity || typeof identity !== "object" || !("role" in identity) || identity.role !== "BOSS" ||
          !("owner_id" in identity) || typeof identity.owner_id !== "string" || !identity.owner_id ||
          !("execution_namespace" in identity) || typeof identity.execution_namespace !== "string" || !identity.execution_namespace) throw new Error("本人身份或执行空间无效");
      const result = await catalogue();
      if (identity.execution_namespace !== result.execution_namespace) throw new Error("身份与资料执行空间不一致");
      if (!active() || controller.signal.aborted) return;
      const next = {owner: identity.owner_id, namespace: result.execution_namespace, dataset: result.dataset_version, context: result.context_version, sources: result.selected_sources};
      const key = "boss:upgrade2:create:" + JSON.stringify([next.owner, next.namespace, next.dataset, chatId]);
      setStored(savedRun(key)); setScope(next);
    })().catch(reason => { if (active() && !controller.signal.aborted) setError(reason instanceof Error ? reason.message : String(reason)); });
    return () => { live.current = false; ++scopeGeneration.current; controller.abort(); operation.current?.abort(); };
  }, [chatId, token, connected, client, getToken, refresh]);

  async function loadCreateMethods(){
    if(!scope||!connected||busy||submitting.current||!current()||stored.pending||stored.dispatch)return;
    const generation=scopeGeneration.current;const controller=new AbortController();operation.current=controller;submitting.current=true;setBusy(true);setError("");setMethod(null);setMethodCatalog(null);
    const active=()=>current()&&generation===scopeGeneration.current&&!controller.signal.aborted;
    try{
      await verifyEntryIdentity(scope,controller.signal);
      if(!active())return;
      const selected=scope.sources.map(source=>source.source_id);
      const methods=await runClient.createMethodCatalog(chatId,selected,controller.signal);
      if(!active())return;
      const latest=await catalogue();
      if(!active())return;
      if(latest.execution_namespace!==scope.namespace||latest.dataset_version!==scope.dataset||latest.context_version!==scope.context||JSON.stringify(latest.selected_sources)!==JSON.stringify(scope.sources))throw new Error("会话资料选择已经变化，请重新读取");
      await verifyEntryIdentity(scope,controller.signal);
      if(!active())return;
      setMethodCatalog(methods);
    }catch(reason){if(active()){
      if((reason instanceof RunApiError||reason instanceof RunHttpError)&&(reason.status===401||reason.status===403)){
        setScope(null);if(reason.status===401)window.dispatchEvent(new Event("boss-auth-expired"));
      }
      setError(reason instanceof Error?reason.message:String(reason));
    }}
    finally{submitting.current=false;if(operation.current===controller)operation.current=null;if(active())setBusy(false);}
  }

  async function perform(reconcile: boolean) {
    if (!scope || !connected || busy || submitting.current || !current()) return;
    const generation = scopeGeneration.current;
    const active = () => current() && generation === scopeGeneration.current;
    submitting.current = true;
    const operationController=new AbortController();operation.current=operationController;
    setBusy(true); setError("");
    try {
      if (!navigator.locks) throw new Error("当前环境不支持跨窗口请求保护");
      await navigator.locks.request(storageKey, async () => {
        if (!active()) return;
        await verifyEntryIdentity(scope,operationController.signal);
        if(!active())return;
        const state = savedRun(storageKey);
        if (reconcile && !state.pending || !reconcile && (state.pending||state.dispatch)) throw new Error("原请求状态已经变化，请重新读取");
        let requestKey = state.pending;
        let pendingMethod=state.pendingMethod??null;
        let pendingRefs=state.pendingRefs??null;
        if (!reconcile) {
          if (!goal.trim()) throw new Error("请输入任务目标");
          if(!method||!methodCatalog?.methods.some(item=>item.status==="AVAILABLE"&&item.sop_id===method.sop_id&&item.version===method.version&&item.content_sha256===method.content_sha256))throw new Error("请选择当前可用方法");
          const latest = await catalogue();
          if (!active()) return;
          if (latest.execution_namespace !== scope.namespace || latest.dataset_version !== scope.dataset || latest.context_version !== scope.context ||
              JSON.stringify(latest.selected_sources) !== JSON.stringify(scope.sources)) throw new Error("会话资料选择已经变化，请重新读取");
          const refreshed=await runClient.createMethodCatalog(chatId,scope.sources.map(source=>source.source_id),operationController.signal);
          if(!active())return;
          if(!refreshed.methods.some(item=>item.status==="AVAILABLE"&&item.sop_id===method.sop_id&&item.version===method.version&&item.content_sha256===method.content_sha256))throw new Error("所选方法已经变化或不可用，请重新选择");
          await verifyEntryIdentity(scope,operationController.signal);
          if(!active())return;
          pendingMethod=method;pendingRefs=scope.sources.map(source=>source.source_id);
          requestKey = crypto.randomUUID();
          const pending = {pending: requestKey, runId: state.runId,pendingMethod,pendingRefs};
          localStorage.setItem(storageKey, JSON.stringify(pending)); setStored(pending);
        }
        if(!requestKey)throw new Error("原创建请求编号无效");
        if(!pendingMethod||!pendingRefs){
          if(reconcile){
            const legacy=await runClient.createReceipt(requestKey,operationController.signal);
            if(!active())return;
            const original=await runClient.read(legacy.run_id,operationController.signal);
            if(!active())return;
            if(original.conversation_id!==chatId)throw new Error("原请求运行与当前会话不一致");
            throw new Error("原创建请求已记录，运行编号 "+legacy.run_id+"；原方法或来源记录不完整，请保留请求编号核查。");
          }
          throw new Error("创建请求缺少方法或来源记录");
        }
        let admitted = false;
        try {
          const receipt = reconcile ? await runClient.createReceipt(requestKey,operationController.signal) : await runClient.create(chatId, goal, pendingRefs, requestKey,operationController.signal,outputs.length?outputs:undefined,pendingMethod);
          admitted = true;
          if (!active()) return;
          const runId = receipt.run_id;
          const snapshot = await runClient.read(runId,operationController.signal);
          if (!active()) return;
          if (snapshot.conversation_id !== chatId||JSON.stringify(snapshot.selected_refs)!==JSON.stringify(pendingRefs)||!snapshot.method_selection||snapshot.method_selection.goal_revision!==1||snapshot.method_selection.sop_id!==pendingMethod.sop_id||snapshot.method_selection.version!==pendingMethod.version||snapshot.method_selection.content_sha256!==pendingMethod.content_sha256) throw new Error("原请求运行、来源或方法不一致");
          const completed = {pending: null, runId,dispatch:null};
          localStorage.setItem(storageKey, JSON.stringify(completed)); setStored(completed);
          if (!reconcile) {setGoal("");setOutputs([]);setMethod(null);setMethodCatalog(null);}
        } catch (reason) {
          if (active() && !reconcile && !admitted && reason instanceof RunApiError && reason.status === 503 && reason.detail.code === "CREATE_NOT_ADMITTED") {
            const rejected = {pending: null, runId: state.runId};
            localStorage.setItem(storageKey, JSON.stringify(rejected)); setStored(rejected);
          }
          throw reason;
        }
      });
    } catch (reason) {
      if (active()) {
        if ((reason instanceof RunApiError || reason instanceof RunHttpError) && (reason.status === 401 || reason.status === 403 || reason instanceof RunApiError && ["EXECUTION_SPACE_CHANGED", "SCOPE_CHANGED"].includes(reason.detail.code))) setScope(null);
        setError(reason instanceof Error ? reason.message : String(reason));
      }
    } finally { submitting.current = false; if(operation.current===operationController)operation.current=null; if (active()) setBusy(false); }
  }

  async function reconcileDispatch(){
    if(!scope||!connected||busy||submitting.current||!current())return;
    const generation=scopeGeneration.current;
    const active=()=>current()&&generation===scopeGeneration.current;
    submitting.current=true;const operationController=new AbortController();operation.current=operationController;setBusy(true);setError("");
    try{
      if(!navigator.locks)throw new Error("当前环境不支持跨窗口请求保护");
      await navigator.locks.request(storageKey,async()=>{
        if(!active())return;
        const state=savedRun(storageKey);
        if(!state.runId||!state.dispatch)throw new Error("原派发请求不存在");
        const receipt=await runClient.dispatchReceipt(state.runId,state.dispatch.revision,state.dispatch.requestKey,operationController.signal);
        if(!active())return;
        if(receipt.state==="COMPLETED"){
          const saved={pending:null,runId:state.runId,dispatch:null};localStorage.setItem(storageKey,JSON.stringify(saved));setStored(saved);
        }else setError("原派发请求状态："+receipt.state+"，请继续核查。");
      });
    }catch(reason){if(active())setError(reason instanceof Error?reason.message:String(reason));}
    finally{submitting.current=false;if(operation.current===operationController)operation.current=null;if(active())setBusy(false);}
  }

  return <>
    {!scope && !error && <p role="status">正在核查当前本人会话与资料选择。</p>}
    {error && <p role="alert" className="boss-n02-note error">{error}</p>}
    {!scope && error && <button type="button" className="boss-btn" disabled={busy} onClick={() => setRefresh(value => value + 1)}>重新核查本人会话</button>}
    {scope && <>
      <p>当前会话已保存 {scope.sources.length} 项来源选择。可使用聊天区域的引用知识库入口更改。</p>
      <label>任务目标<textarea value={goal} onChange={event => {setGoal(event.target.value);setOutputs([]);}} disabled={busy || !!stored.pending||!!stored.dispatch}/></label>
      <button type="button" className="boss-btn" disabled={busy||!connected||!!stored.pending||!!stored.dispatch} onClick={()=>void loadCreateMethods()}>读取创建方法</button>
      {methodCatalog&&<label>创建方法<select value={method?.sop_id??""} disabled={busy||!!stored.pending||!!stored.dispatch} onChange={event=>{const selected=methodCatalog.methods.find(item=>item.sop_id===event.target.value&&item.status==="AVAILABLE");setMethod(selected?{sop_id:selected.sop_id,version:selected.version,content_sha256:selected.content_sha256}:null);}}><option value="">请选择方法</option>{methodCatalog.methods.map(item=><option key={item.sop_id} value={item.sop_id} disabled={item.status!=="AVAILABLE"}>{item.name} · {item.sop_id} · 版本 {item.version}{item.status!=="AVAILABLE"?" · 不可用":""}</option>)}</select></label>}
      {method&&<p>方法版本 {method.version} · 内容摘要 {method.content_sha256}</p>}
      {methodCatalog?.methods.filter(item=>item.status!=="AVAILABLE").map(item=><p key={item.sop_id}>{item.name} 不可用：{[...item.reasons,...item.missing_native_tools,...item.missing_runtime_tools,...item.missing_projections].join("、")}</p>)}
      <RequiredOutputs value={outputs} onChange={setOutputs} disabled={busy||!!stored.pending||!!stored.dispatch}/>
      {stored.pending ? <p role="status">原创建请求 {stored.pending} 等待核查。<button type="button" className="boss-btn" disabled={busy} onClick={() => void perform(true)}>查询原请求结果</button></p>
        : <button type="button" className="boss-btn" disabled={busy || !!stored.dispatch || !goal.trim()||!method} onClick={() => void perform(false)}>创建持续任务</button>}
      {stored.dispatch&&<p role="status">原派发请求 {stored.dispatch.requestKey} 等待核查。<button type="button" className="boss-btn" disabled={busy||!connected} onClick={()=>void reconcileDispatch()}>查询原派发结果</button></p>}
      {stored.dispatch&&stored.runId&&<DispatchRecoveryInspection key={JSON.stringify([identityKey,scope.owner,scope.namespace,scope.dataset,chatId,stored.runId,stored.dispatch.requestKey,stored.dispatch.revision,token])} client={runClient} runId={stored.runId} requestKey={stored.dispatch.requestKey} revision={stored.dispatch.revision} storageKey={storageKey} token={token} getToken={getToken} connected={connected}/>}
      <button type="button" className="boss-btn" disabled={busy} onClick={() => setRefresh(value => value + 1)}>重新读取会话资料</button>
      {stored.runId && <Upgrade2ConversationRun key={stored.runId} binding={{chatId, conversationId: chatId, runId: stored.runId, authToken: token, identityKey, pendingScopeKey: JSON.stringify([scope.owner, scope.namespace, scope.dataset]), projection: null}} connected={connected} onOpenTask={onOpenTask} onOpenTaskReceipt={onOpenTaskReceipt} onOpenMeeting={onOpenMeeting} onOpenMinutes={onOpenMinutes} onOpenSource={onOpenSource}/>}
    </>}
  </>;
}
