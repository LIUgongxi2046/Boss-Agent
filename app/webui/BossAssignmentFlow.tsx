import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {MorningReference} from "./BossMorningView";
import type {MorningPreparationContext} from "./BossMorningPreparation";
import {
  AlertCircle, ArrowRight, CheckCircle2, Clock3, ClipboardCheck,
  FileSearch, Loader2, MessageSquareText, RefreshCw, ShieldCheck, XCircle,
} from "lucide-react";
import { useClient } from "@/providers/ClientProvider";
import type { AssignmentDraft } from "./BossAssignmentPicker";
import {BossAssignmentPreparation} from "./BossAssignmentPreparation";
import {BossOriginalReceipt} from "./BossOriginalReceipt";

export interface AssignmentTask {
  task_id: string; status: string; version?: string; purpose?: string;
  coordinator_id?: string; due_at?: string; timezone?: string;
  feedback_ids?: string[]; message_ids?: string[];
  source_refs?: string[]; evidence_requirements?: string[];
  origin_minute_id?: string; origin_minute_version?: string;
  origin_entry_id?: string; origin_source_id?: string;
  origin_source_version?: string;
  source_reference_state?: "CURRENT" | "NEEDS_REVIEW";
  source_reference_reasons?: string[];
  source_versions?:Record<string,string>;result_evidence_requires_resubmission?:boolean;
}
export interface TaskFeedback {
  feedback_id: string; task_id: string;
  kind: "PROGRESS" | "EXTENSION_REQUEST" | "RESULT_SUBMITTED";
  author_contact_id?: string; content?: string; evidence_refs?: string[];
  proposed_due_at?: string; submitted_at?: string;
  evidence_versions?:Record<string,string>;evidence_states?:Record<string,string>;historical_only?:boolean;task_version?:string;
}
export interface TaskLinkedMessage {
  message_id: string; task_id: string;
  type: "ASSIGNMENT_SEND" | "FOLLOWUP_MESSAGE" | "ASSIGNMENT_NUDGE";
  recipient_id: string; sent_at: string; send_state: string;
  delivery_state: string; reply_state: string;
  external_channel_invoked: false;
  body?:string;authorization_id?:string|null;
}
export interface TaskDueEvent {
  task_id: string; event_id: string; event_version: string;
  event_state: string; due_at: string; task_version_at_sync: string;
  dispatch_state: string; dispatch_reason: string | null;
  external_delivery_verified: false;
}
export interface TaskListResponse {
  tasks: AssignmentTask[];
  feedback?: TaskFeedback[];
  linked_messages?: TaskLinkedMessage[];
  task_due_events?: TaskDueEvent[];
}
export interface AssignmentContext {
  meeting: { meeting_id: string; starts_at: string } | null;
  event?: { event_id: string; status: string };
  assignment_source_ids?: string[];
  contacts: { contact_id: string; name: string; organization: string; responsibility: string }[];
}
export interface MaintenanceTaskRef {
  task_id: string; version: string; status: string; coordinator_id?: string;
}
type Action =
  | "boss.assignment.create" | "boss.assignment.send"
  | "boss.assignment.complete" | "boss.assignment.extend"
  | "boss.assignment.cancel" | "boss.assignment.nudge" | "boss.simulation.feedback"
  | "boss.assignment.extension.decide"
  | "boss.commitment.create" | "boss.commitment.extend" | "boss.commitment.cancel" | "boss.commitment.complete"
  | "boss.reminder.ack" | "boss.reminder.snooze" | "boss.reminder.close"
  | "boss.owner.notice.save" | "boss.owner.notice.confirm"
  | "boss.owner.plan.save" | "boss.owner.plan.pause" | "boss.owner.plan.resume" | "boss.owner.plan.cancel"
  | "boss.scheduler.draft.save" | "boss.scheduler.draft.validate" | "boss.scheduler.activate" | "boss.scheduler.manual_run" | "boss.scheduler.pause" | "boss.scheduler.resume" | "boss.scheduler.cancel"
  | "boss.alert.ack" | "boss.alert.snooze" | "boss.alert.close" | "boss.alert.meeting.link" | "boss.alert.assignment.create"
  | "boss.alert.rule.save" | "boss.alert.rule.validate" | "boss.alert.rule.activate" | "boss.alert.rule.disable"
  | "boss.simulation.alert.rule.save" | "boss.simulation.alert.rule.validate" | "boss.simulation.alert.rule.activate" | "boss.simulation.alert.rule.disable" | "boss.simulation.alert.load"
  | "boss.message.draft.save";
type Result = {
  task_id?: string; task?: { task_id: string; status: string; version: string };
  status?: string; state?:string;version?: string; feedback_id?: string; draft_id?: string; commitment_id?:string;event_id?:string;plan_id?:string;
};
type Pending = {
  action: Action; payload: Record<string, unknown>;
  id: string; title: string; preview: string[]; restored?:boolean; target?:string;
};
function shanghai(value: string): string {
  if (!/^\d{4}-\d\d-\d\dT\d\d:\d\d$/.test(value)) {
    throw new Error("请填写完整日期和时间");
  }
  return value + ":00+08:00";
}
function required(value: string, field: string): string {
  if (!value.trim()) throw new Error("请填写“" + field + "”。");
  return value.trim();
}
function displayTime(value?: string) { return value ? value.replace("T", " ") : "待核查"; }

type TransactionScope="assignment"|"feedback"|"commitment"|"reminder"|"ownerNotice"|"ownerGoalsReadonly"|"plan"|"scheduler"|"alerts"|"alertRules"|"alertInput";
const TRANSACTION_ACTIONS:Record<TransactionScope,Action[]>={
  assignment:["boss.assignment.create","boss.assignment.send","boss.assignment.nudge","boss.assignment.extend","boss.assignment.extension.decide","boss.assignment.cancel","boss.assignment.complete","boss.message.draft.save"],
  feedback:["boss.simulation.feedback"],commitment:["boss.commitment.create","boss.commitment.extend","boss.commitment.cancel","boss.commitment.complete"],
  reminder:["boss.reminder.ack","boss.reminder.snooze","boss.reminder.close"],ownerNotice:["boss.owner.notice.save","boss.owner.notice.confirm"],ownerGoalsReadonly:[],
  plan:["boss.owner.plan.save","boss.owner.plan.pause","boss.owner.plan.resume","boss.owner.plan.cancel"],
  scheduler:["boss.scheduler.draft.save","boss.scheduler.draft.validate","boss.scheduler.activate","boss.scheduler.manual_run","boss.scheduler.pause","boss.scheduler.resume","boss.scheduler.cancel"],
  alerts:["boss.alert.ack","boss.alert.snooze","boss.alert.close","boss.alert.meeting.link","boss.alert.assignment.create"],
  alertRules:["boss.alert.rule.save","boss.alert.rule.validate","boss.alert.rule.activate","boss.alert.rule.disable","boss.simulation.alert.rule.save","boss.simulation.alert.rule.validate","boss.simulation.alert.rule.activate","boss.simulation.alert.rule.disable"],
  alertInput:["boss.simulation.alert.load"],
};
export function useTransaction(onReload: () => void, onCreated?: (id: string) => void, onMessageDraftCreated?: (id: string) => void, scope:TransactionScope="assignment") {
  const { client, getToken, token } = useClient();
  const [lookupBusy,setLookupBusy] = useState(false);
  const dialogRef = useRef<HTMLElement | null>(null);
  const busyRef = useRef(false);
  const [pending, setPending] = useState<Pending | null>(()=>{
    const values=new URLSearchParams(window.location.search),id=values.get(scope+"Request"),action=values.get(scope+"Action"),target=values.get(scope+"Target")??"";
    const actions=TRANSACTION_ACTIONS[scope];
    return id&&action&&actions.includes(action as Action)?{id,action:action as Action,target,payload:{},restored:true,title:"核查原请求结果",preview:["原请求："+id,"动作："+action,"对象："+(target||"创建对象待原回执核查")]}:null;
  });
  const [uncertain,setUncertain]=useState(Boolean(pending?.restored));
  const epoch=useRef(0),identity=useRef(token);
  useEffect(()=>{epoch.current++;if(identity.current!==token){identity.current=token;setPending(null);setApproved(false);setNotice("");setError("");setUncertain(false);setBusy(false);setLookupBusy(false);}return()=>{epoch.current++;};},[token]);
  const remember=useCallback((value:Pending|null)=>{const url=new URL(window.location.href);for(const key of ["Request","Action","Target"]){if(value){const content=key==="Request"?value.id:key==="Action"?value.action:value.target??"";url.searchParams.set(scope+key,content);}else url.searchParams.delete(scope+key);}window.history.replaceState(window.history.state,"",url);},[scope]);
  const [approved, setApproved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  busyRef.current = busy||lookupBusy||uncertain;
  useEffect(() => {
    if (!pending) return;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const modal = dialogRef.current;
    modal?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      const current = dialogRef.current;
      if (!current) return;
      if (event.key === "Escape" && !busyRef.current) {
        event.preventDefault();
        setPending(null);
        setApproved(false);
        return;
      }
      if (event.key !== "Tab") return;
      const nodes = Array.from(current.querySelectorAll<HTMLElement>(
        'button:not([disabled]),input:not([disabled]),[tabindex="0"]',
      )).filter(node => node.getClientRects().length > 0);
      if (!nodes.length) { event.preventDefault(); current.focus(); return; }
      const first = nodes[0], last = nodes[nodes.length - 1];
      if (event.shiftKey && (document.activeElement === first || document.activeElement === current)) {
        event.preventDefault();last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => { document.removeEventListener("keydown", onKeyDown); previous?.focus(); };
  }, [pending?.id]);
  const propose = useCallback((action: Action, payload: Record<string, unknown>, title: string, preview: string[]) => {
    if(new URLSearchParams(window.location.search).has(scope+"Request")){setError("当前原请求仍需核查，请查询同一编号。");return;}
    setPending({ action, payload, id: "boss-" + crypto.randomUUID(), title, preview, target:typeof payload.task_id==="string"?payload.task_id:typeof payload.commitment_id==="string"?payload.commitment_id:typeof payload.event_id==="string"?payload.event_id:typeof payload.plan_id==="string"?payload.plan_id:"" });
    setUncertain(false);
    setApproved(false); setError(""); setNotice("");
  }, [scope]);
  const submit = useCallback(async () => {
    if (!pending || !approved || busy || uncertain || pending.restored) return;
    const current=epoch.current;remember(pending);setUncertain(true);setBusy(true); setError("");
    try {
      const result = await client.requestMutation<Result>(
        pending.action, { ...pending.payload, client_request_id: pending.id },
      );
      if(current!==epoch.current)return;
      if (pending.action === "boss.assignment.create" && result.task_id) onCreated?.(result.task_id);
      if (pending.action === "boss.commitment.create" && result.commitment_id) onCreated?.(result.commitment_id);
      if (pending.action === "boss.message.draft.save" && result.draft_id) onMessageDraftCreated?.(result.draft_id);
      setNotice("实际模拟业务已保存。状态：" + (result.status || result.state || result.task?.status || "已记录") +
        "；对象：" + (result.task_id || result.task?.task_id || result.commitment_id || result.event_id || result.plan_id || "未知") + "。请重读当前状态。");
      remember(null);setUncertain(false);setPending(null); setApproved(false); onReload();
    } catch (e) {
      if(current!==epoch.current)return;
      const status=e instanceof Error&&"status" in e&&typeof e.status==="number"?e.status:null;
      if(status!==null&&[400,401,403,404,409,410,413,422].includes(status)){setUncertain(false);remember(null);}
      if(status===401||status===403){setPending(null);setApproved(false);setNotice("");if(status===401)window.dispatchEvent(new Event("boss-auth-expired"));}
      setError((e instanceof Error ? e.message : String(e)) +
        "。请核查正式状态；结果尚未确定时仅查询原请求编号。");
    } finally { if(current===epoch.current)setBusy(false); }
  }, [approved, busy, client, onCreated, onMessageDraftCreated, onReload, pending,uncertain,remember]);
  const reconcile = useCallback(async () => {
    if (!pending || busy || lookupBusy) return;
    const token = getToken();
    if (!token) { setError("当前身份已失效，无法核查业务回执"); return; }
    const current=epoch.current;setLookupBusy(true);setError("");
    try {
      const qs = new URLSearchParams({
        action: pending.action, client_request_id: pending.id,
      });
      const res = await fetch("/api/boss/ui/operation-status?" + qs.toString(), {
        headers: {Authorization:"Bearer "+token}, cache:"no-store",
      });
      if(current!==epoch.current)return;
      if(res.status===401||res.status===403){setPending(null);setApproved(false);setNotice("");remember(null);if(res.status===401)window.dispatchEvent(new Event("boss-auth-expired"));}
      if (!res.ok) throw new Error("幂等回执查询失败（HTTP " + res.status + "）");
      const body = await res.json() as {
        action:string;client_request_id:string;outcome:string;result?:Result;
      };
      if(current!==epoch.current)return;
      if(body.action!==pending.action||body.client_request_id!==pending.id)
        throw new Error("操作回执身份与本次动作不匹配");
      if(body.outcome==="RECORDED"&&body.result){
        const target=pending.action.startsWith("boss.alert.")?body.result.event_id:body.result.task_id??body.result.task?.task_id??body.result.commitment_id??body.result.event_id??body.result.plan_id;
        if(pending.target&&pending.target!==target)throw new Error("原请求回执不属于当前业务对象");
        if(pending.action==="boss.assignment.create"&&body.result.task_id)
          onCreated?.(body.result.task_id);
        if(pending.action==="boss.commitment.create"&&body.result.commitment_id)onCreated?.(body.result.commitment_id);
        if(pending.action==="boss.message.draft.save"&&body.result.draft_id)
          onMessageDraftCreated?.(body.result.draft_id);
        setNotice("已从实际 SQLite 幂等回执核实该交办动作已保存，任务状态正在重读。");
        remember(null);setUncertain(false);setPending(null);setApproved(false);onReload();
      }else if(body.outcome==="NOT_FOUND_IN_CURRENT_STORE"){
        setError("当前没有该请求回执，执行结果仍未确定，请继续读取同一原编号。");
        onReload();
      }else throw new Error("服务端回执格式无效，不能假定已执行");
    } catch(e) {
      if(current===epoch.current)setError(e instanceof Error?e.message:String(e));
    }finally{if(current===epoch.current)setLookupBusy(false);}
  },[pending,busy,lookupBusy,getToken,onCreated,onMessageDraftCreated,onReload,remember]);
  const dialog = pending ? <div className="boss-confirm-backdrop">
    <section ref={dialogRef} tabIndex={-1} className="boss-confirm boss-fc07-confirm" role="dialog" aria-modal="true" aria-labelledby="boss-confirm-title">
      <h3 id="boss-confirm-title"><ShieldCheck size={19}/> {pending.title}</h3>
      <p>仅当前已认证身份能发起此项模拟业务操作。下面的字段将与授权、对象版本及唯一请求编号一同保存。</p>
      <dl>{pending.preview.map((line, index) => <div key={index}><dd>{line}</dd></div>)}</dl>
      <label className="boss-confirm-check">
        <input type="checkbox" checked={approved} disabled={busy||uncertain} onChange={e=>setApproved(e.target.checked)}/>
        <span>本人确认以上具体对象、内容、期限和动作。</span>
      </label>
      {error && <p role="alert" className="boss-validation-error">{error}</p>}
      <p>原请求编号：{pending.id}</p>{uncertain&&<p role="status">结果尚未确定，仅查询原请求编号。</p>}
      <footer className="boss-actions">
        <button type="button" className="boss-btn" disabled={busy||lookupBusy||uncertain}
          onClick={() => {setPending(null);setApproved(false);}}>取消（不执行）</button>
        <button type="button" className="boss-btn" disabled={busy||lookupBusy}
          onClick={() => void reconcile()}>
          {lookupBusy && <Loader2 size={15} className="boss-spin"/>} 核查原请求结果</button>
        <button type="button" className="boss-btn boss-btn-primary" disabled={!approved||busy||lookupBusy||uncertain||pending.restored}
          onClick={() => void submit()}>{busy && <Loader2 size={15} className="boss-spin"/>} 确认并提交</button>
      </footer>
    </section>
  </div> : null;
  const unresolved=new URLSearchParams(window.location.search).has(scope+"Request");
  const recovery=!pending&&unresolved?<BossOriginalReceipt scope={scope} actions={TRANSACTION_ACTIONS[scope]} onRecorded={onReload}/>:null;
  return { propose, dialog, recovery, notice, busy:busy||uncertain||lookupBusy||(!pending&&unresolved) };
}

export function BossAssignmentFlow({ tasks, selectedTaskId, onSelectTask, onReload, onViewSource, context,
  draft, onDraftChange, onDraftSaved, onOpenCoordinatorPicker, onOpenDuePicker,
  onViewMessages, onMessageDraftCreated, morningReference, morningReady=true, morningContext, messagesEnabled=true }: {
  tasks: TaskListResponse | null; selectedTaskId: string;
  onSelectTask: (id: string, bypassDirty?:boolean) => void; onReload: () => void;
  onViewSource: (id?:string) => void; context: AssignmentContext | null;
  draft: AssignmentDraft;
  onDraftChange: (key: keyof AssignmentDraft, value: string) => void;
  onDraftSaved: () => void;
  onOpenCoordinatorPicker: () => void; onOpenDuePicker: () => void;
  onViewMessages: () => void;
  onMessageDraftCreated: (id: string) => void;
  morningReference?:MorningReference;morningReady?:boolean;morningContext?:MorningPreparationContext|null;
  messagesEnabled?:boolean;
}) {
  const { propose, dialog, recovery, notice, busy } = useTransaction(()=>{onDraftSaved();onReload();}, id => {
    onSelectTask(id,true); onDraftSaved();
  }, onMessageDraftCreated);
  const {purpose,coordinator,due,evidence,body,newDue,reason}=draft;
  const [error,setError]=useState("");
  const {getToken,token}=useClient();
  const [extensionHistory,setExtensionHistory]=useState<{task_id:string;task_version:string;due_at:string;decisions:{decision_id:string;feedback_id:string;decision:"APPROVE"|"REJECT";old_due_at:string;new_due_at:string;reason:string|null;request_reason:string;decided_at:string;previous_task_version:string;task_version:string}[]}|null>(null);
  const rows=tasks?.tasks||[];
  const current=selectedTaskId?rows.find(t=>t.task_id===selectedTaskId):rows[0];
  const feedback=useMemo(()=>(tasks?.feedback||[]).filter(f=>current&&f.task_id===current.task_id),[current,tasks]);
  const linkedMessages=useMemo(()=>(tasks?.linked_messages||[]).filter(
    row=>current&&row.task_id===current.task_id
  ),[current,tasks]);
  const taskDue=useMemo(()=>(tasks?.task_due_events||[]).find(
    row=>current&&row.task_id===current.task_id
  ),[current,tasks]);
  const completed=[...feedback].reverse().find(f=>f.kind==="RESULT_SUBMITTED"&&!f.historical_only&&Boolean(f.evidence_refs?.length));
  const extension=extensionHistory?[...feedback].reverse().find(f=>f.kind==="EXTENSION_REQUEST"&&!f.historical_only&&!extensionHistory.decisions.some(decision=>decision.feedback_id===f.feedback_id)):undefined;
  useEffect(()=>{
    const abort=new AbortController();setExtensionHistory(null);
    if(current?.task_id&&current.version)void fetch("/api/boss/ui/assignment-extensions?"+new URLSearchParams({task_id:current.task_id}),{headers:{Authorization:"Bearer "+getToken()},cache:"no-store",signal:abort.signal}).then(async response=>{
      if(abort.signal.aborted)return;
      if(response.status===401||response.status===403){setExtensionHistory(null);if(response.status===401)window.dispatchEvent(new Event("boss-auth-expired"));}
      if(!response.ok)throw new Error("延期决定读取失败，HTTP "+response.status);
      const value=await response.json();if(abort.signal.aborted)return;
      if(value.task_id!==current.task_id||value.task_version!==current.version)throw new Error("延期决定与当前交办版本不符，请重新读取");
      setExtensionHistory(value);
    }).catch(failure=>{if(!abort.signal.aborted)setError(failure.message);});
    return()=>abort.abort();
  },[current?.task_id,current?.version,getToken,token]);
  const safe=(fn:()=>void)=>{setError("");try{fn()}catch(e){setError(e instanceof Error?e.message:String(e))}};
  const prepareCreate=()=>safe(()=>{
    if(morningReference&&(!morningReady||!morningContext?.source_ids.length))throw new Error("请重新核查当前晨间事项与来源版本");
    if(!context||!morningReference&&(!context.meeting?.meeting_id||!context.event?.event_id||!context.assignment_source_ids?.includes("finance-note")))
      throw new Error("未取得关联会议、事件或有效资料，拒绝创建。");
    const meetingId=morningReference?morningContext!.meeting_id:context.meeting!.meeting_id;
    const eventIds=morningReference?morningContext!.event_ids:[context.event!.event_id];
    const sourceIds=morningReference?morningContext!.source_ids:["finance-note"];
    const purposeText=required(purpose,"交办目的"),proof=required(evidence,"证据要求");
    if(!coordinator||!context.contacts.some(c=>c.contact_id===coordinator))
      throw new Error("请选择获准的唯一负责人");
    const dueAt=shanghai(due);
    propose("boss.assignment.create",{
      purpose:purposeText,coordinator_id:coordinator,due_at:dueAt,
      timezone:"Asia/Shanghai",evidence_requirements:[proof],
      related_meeting_id:meetingId,
      related_event_ids:eventIds,
      source_refs:sourceIds,content_version:"1",
      ...(morningReference?{morning_reference:morningReference}:{}),
    },"核对并创建交办",[
      "目的："+purposeText,"负责人："+coordinator,"期限："+dueAt,
      "证据："+proof,"会议："+(meetingId??"没有关联会议"),
      "关联事件："+(eventIds.join("、")||"没有关联事件"),"资料来源："+sourceIds.join("、"),
    ]);
  });
  const prepareSend=()=>safe(()=>{
    if(!current||current.status!=="OPEN"||!current.version||!current.coordinator_id)
      throw new Error("仅 OPEN 且版本有效的交办可以发送。");
    if(current.source_reference_state!=="CURRENT")
      throw new Error("任务来源已失效或没有固定版本；必须重新核查后才能发送。");
    const message=required(body,"模拟消息正文");
    propose("boss.assignment.send",{
      task_id:current.task_id,task_version:current.version,
      recipient_id:current.coordinator_id,body:message,content_version:"1",
    },"模拟发送前确认",[
      "交办："+current.task_id+" v"+current.version,"目的："+current.purpose,"唯一收件人："+current.coordinator_id,
      "期限："+current.due_at+" · "+current.timezone,"依据："+(current.source_refs??[]).map(id=>id+" v"+(current.source_versions?.[id]??"未知")).join("；"),
      "正文："+message,"仅写入模拟发件箱，不会真正发送至外部人员。",
    ]);
  });
  const prepareNudge=()=>safe(()=>{
    if(!current?.version||!current.coordinator_id||
       !["WAITING_FEEDBACK","IN_PROGRESS"].includes(current.status))
      throw new Error("仅已经单独发送并处于等待反馈或进行中的任务能够催办。");
    if(current.source_reference_state!=="CURRENT")
      throw new Error("任务引用的资料已经变化，无法直接催办。");
    const message=required(body,"催办正文");
    propose("boss.assignment.nudge",{
      task_id:current.task_id,task_version:current.version,
      recipient_id:current.coordinator_id,body:message,
    },"本人授权独立催办",[
      "交办："+current.task_id+" · 当前版本 "+current.version,
      "目的："+current.purpose,"期限："+current.due_at+" · "+current.timezone,
      "收件人："+current.coordinator_id,"催办正文："+message,
      "只记录本地模拟发件，真正送达仍待核查；24小时模拟时钟内禁止重复催办。",
    ]);
  });
  const prepareFollowup=()=>safe(()=>{
    if(!current||!current.version||!current.coordinator_id)
      throw new Error("请先选择已保存的交办任务");
    if(!["WAITING_FEEDBACK","IN_PROGRESS"].includes(current.status))
      throw new Error("只有已经独立发送、正在等待或处理反馈的任务可以准备催办");
    if(current.source_reference_state!=="CURRENT")
      throw new Error("原始资料已经变化，不能据此继续催办");
    const message=required(body,"催办草稿正文");
    propose("boss.message.draft.save",{
      draft_id:null,expected_version:"0",
      recipient_id:current.coordinator_id,
      related_task_id:current.task_id,body:message,
      attachment_refs:[],visibility:"RECIPIENT_ONLY",
    },"保存当前交办的催办草稿",[
      "关联任务："+current.task_id,
      "唯一负责人："+current.coordinator_id,
      "当前任务状态："+current.status,
      "催办正文："+message,
      "只保存 F08 DRAFT，不会自动发送或生成送达回执。",
    ]);
  });
  const prepareComplete=()=>safe(()=>{
    if(!current||!completed||current.status!=="RESULT_SUBMITTED"||!current.version)
      throw new Error("当前没有已经提交且具备证据的核查结果。");
    if(current.source_reference_state!=="CURRENT"||current.result_evidence_requires_resubmission)
      throw new Error("原始来源已更改或撤销，不能确认完成。");
    propose("boss.assignment.complete",{
      task_id:current.task_id,task_version:current.version,feedback_id:completed.feedback_id,
    },"老板确认完成",[
      "交办："+current.task_id+" v"+current.version,"目的："+current.purpose,"负责人："+current.coordinator_id,"结果提交："+completed.feedback_id,
      "证据："+(completed.evidence_refs||[]).map(id=>id+" v"+(completed.evidence_versions?.[id]??"未知")).join("；"),
      "仅在本人确认后更新为 COMPLETED_CONFIRMED。",
    ]);
  });
  const prepareExtend=(decision:"APPROVE"|"REJECT")=>safe(()=>{
    if(!current||!extension||!current.version)throw new Error("未取得有效延期申请。");
    const date=decision==="APPROVE"?shanghai(newDue):null;
    const note=required(reason,"本人决定理由");
    propose("boss.assignment.extension.decide",{
      task_id:current.task_id,task_version:current.version,
      feedback_id:extension.feedback_id,due_at:date,decision,reason:note,
    },decision==="APPROVE"?"本人批准延期":"本人拒绝延期",[
      "交办："+current.task_id+" · 当前版本 "+current.version,
      "原期限："+displayTime(current.due_at),
      "延期依据："+extension.feedback_id,"申请期限："+displayTime(extension.proposed_due_at),"申请理由："+extension.content,
      "本人决定："+decision,"决定后期限："+(date??current.due_at),"本人理由："+note,
      "未批准前旧期限持续有效。",
    ]);
  });
  const prepareCancel=()=>safe(()=>{
    if(!current||!current.version)throw new Error("请选择有效任务。");
    const why=required(reason,"取消原因");
    propose("boss.assignment.cancel",{
      task_id:current.task_id,task_version:current.version,reason:why,
    },"老板确认取消交办",[
      "交办："+current.task_id+" v"+current.version,"目的："+current.purpose,"负责人："+current.coordinator_id,"原因："+why,
      "先前已发送的模拟消息和历史反馈不会撤销。",
    ]);
  });
  return <div className="boss-assignment-scope">
    <div className="boss-columns">
      <div className="boss-column">
        <section className="boss-panel">
          <div className="boss-panel-head"><h2>创建交办</h2><small>F06 · 当前老板授权</small></div>
          <div className="boss-form-grid">
            <label htmlFor="assignment-coordinator"><span id="assignment-coordinator-label">唯一负责人</span><select id="assignment-coordinator" aria-labelledby="assignment-coordinator-label" value={coordinator} onChange={e=>onDraftChange("coordinator",e.target.value)}>
              <option value="">请选择</option>
              {(context?.contacts||[]).map(c=><option key={c.contact_id} value={c.contact_id}>
                {c.name} · {c.organization} · {c.responsibility}
              </option>)}
            </select></label>
            <label>期限（Asia/Shanghai）<input type="datetime-local" value={due} onChange={e=>onDraftChange("due",e.target.value)}/></label>
          </div>
          <div className="boss-actions">
            <button type="button" className="boss-btn" onClick={onOpenCoordinatorPicker}>选择负责人（D04）</button>
            <button type="button" className="boss-btn" onClick={onOpenDuePicker}>选择时间与时区（D05）</button>
          </div>
          <label className="boss-label" htmlFor="assignment-purpose">交办目的</label>
          <textarea id="assignment-purpose" rows={3} value={purpose} onChange={e=>onDraftChange("purpose",e.target.value)}
            placeholder="说明目的、范围、要求与应交付的产物"/>
          <label className="boss-label" htmlFor="assignment-evidence">证据要求</label>
          <input id="assignment-evidence" className="boss-single-input" value={evidence} onChange={e=>onDraftChange("evidence",e.target.value)}/>
          <p className="boss-helper">会议：{morningReference?morningContext?.meeting_id??"没有关联会议":context?.meeting?.meeting_id||"待读取"} ·
            关联事件：{morningReference?morningContext?.event_ids.join("、")||"没有关联事件":context?.event?.event_id||"待读取"} · 资料：{morningReference?morningContext?.source_ids.join("、")||"依据尚待核查":context?.assignment_source_ids?.join("、")||"待读取"}</p>
          <div className="boss-actions">
            <button className="boss-btn boss-btn-primary" type="button" onClick={prepareCreate} disabled={busy||Boolean(morningReference&&!morningReady)}>
              <ShieldCheck size={15}/> 核对并创建</button>
            <button className="boss-btn" type="button" onClick={()=>onViewSource()}>查看来源</button>
          </div>
          <p className="boss-helper">创建与发送是两个独立操作，不会自动发出消息。</p>
        </section>
        <section className="boss-panel">
          <div className="boss-panel-head"><h2>当前交办列表</h2><small>仅展示 SQLite 正式状态</small></div>
          {rows.length?rows.map(t=><button key={t.task_id} type="button" onClick={()=>onSelectTask(t.task_id)}
            className={"boss-task-row "+(current?.task_id===t.task_id?"selected":"")}>
            <span className="boss-task-icon"><ClipboardCheck size={17}/></span>
            <span><strong>{t.purpose||t.task_id}</strong>
              <small>{t.status} · v{t.version||"?"} · {displayTime(t.due_at)}</small>
              <small>负责人：{t.coordinator_id||"待核查"}</small>
            </span><ArrowRight size={15}/>
          </button>):<p className="boss-helper">没有持久化交办，设计示例不会被视为正式任务。</p>}
          <div className="boss-actions"><button className="boss-btn" type="button" onClick={onReload}>
            <RefreshCw size={15}/> 重新读取任务状态</button></div>
        </section>
      </div>
      <div className="boss-column">
        {current?.version&&<BossAssignmentPreparation key={current.task_id} taskId={current.task_id} taskVersion={current.version}/>}
        <section className="boss-panel">
          <div className="boss-panel-head"><h2>交办详情与模拟发送</h2><small>有效授权 · 当前对象版本</small></div>
          {current ? <>
            <div className="boss-kv"><span>任务 ID</span><strong>{current.task_id}</strong></div>
            <div className="boss-kv"><span>任务目的与产物</span><strong>{current.purpose}</strong></div>
            <div className="boss-kv"><span>唯一负责人</span><strong>{current.coordinator_id}</strong></div>
            <div className="boss-kv"><span>当前版本</span><strong>{current.version}</strong></div>
            <div className="boss-kv"><span>时区</span><strong>{current.timezone}</strong></div>
            <div className="boss-kv"><span>正式状态</span><strong>{current.status}</strong></div>
            <div className="boss-kv"><span>截止时间</span><strong>{displayTime(current.due_at)}</strong></div>
            <div className="boss-kv"><span>证据要求</span><strong>{current.evidence_requirements?.join("、")||"缺少"}</strong></div>
            <div className="boss-kv"><span>原始依据版本</span>
              <strong>{current.source_reference_state||"NEEDS_REVIEW"}</strong>
            </div>
            {current.source_reference_state!=="CURRENT"&&
              <div className="boss-status boss-status-warn" role="status">
                <AlertCircle size={16}/> 当前依据需要复核：
                {(current.source_reference_reasons||[]).join("、")||"缺少可核验版本"}。
                旧授权不能应用于已撤销或换版材料。
              </div>}
            {current.origin_minute_id&&<div className="boss-workspace-item" role="group" aria-label="纪要交办原始来源">
              <strong>已确认纪要关联</strong>
              <div className="boss-kv"><span>纪要 / 条目</span>
                <strong>{current.origin_minute_id} · {current.origin_entry_id}</strong></div>
              <div className="boss-kv"><span>纪要版本</span>
                <strong>v{current.origin_minute_version}</strong></div>
              <div className="boss-kv"><span>原文来源</span>
                <strong>{current.origin_source_id} · v{current.origin_source_version}</strong></div>
              <div className="boss-actions">
                <button className="boss-btn" type="button" onClick={()=>onViewSource()}>
                  <FileSearch size={15}/> 核对当前业务来源</button>
              </div>
              <p className="boss-helper">本次交办由本人单独授权创建；是否发送以当前任务真实状态为准。</p>
            </div>}
            <label className="boss-label">模拟发件内容</label>
            <textarea rows={3} value={body} onChange={e=>onDraftChange("body",e.target.value)} placeholder="输入准备发给唯一负责人的正文"/>
            <div className="boss-actions"><button className="boss-btn boss-btn-primary" type="button"
              disabled={current.status!=="OPEN"||current.source_reference_state!=="CURRENT"||busy} onClick={prepareSend}>
              <MessageSquareText size={15}/> 核对并模拟发送</button></div>
          </>:<p className="boss-helper">请先选择或创建交办。</p>}
          <p className="boss-helper">模拟 SENT 只代表本地发件箱已记录；任务仍需反馈。</p>
          {current&&["WAITING_FEEDBACK","IN_PROGRESS"].includes(current.status)&&
            <div className="boss-actions">
              {messagesEnabled&&<button type="button" className="boss-btn"
                disabled={busy||current.source_reference_state!=="CURRENT"}
                onClick={prepareFollowup}>
                <MessageSquareText size={15}/> 保存关联催办草稿（F08）
              </button>}
              <button type="button" className="boss-btn boss-btn-primary"
                disabled={busy||current.source_reference_state!=="CURRENT"}
                onClick={prepareNudge}>
                <MessageSquareText size={15}/> 本人核对并模拟催办
              </button>
              {messagesEnabled&&<button type="button" className="boss-btn" onClick={onViewMessages}>
                打开 F08 草稿与模拟发件箱
              </button>}
            </div>}
        </section>
        <section className="boss-panel">
          <div className="boss-panel-head">
            <h2>到期提醒与调度结果</h2><small>FR06 · 服务端模拟时钟</small>
          </div>
          {taskDue ? <>
            <div className="boss-kv"><span>到期事件 ID</span><strong>{taskDue.event_id}</strong></div>
            <div className="boss-kv"><span>事件版本</span><strong>{taskDue.event_version}</strong></div>
            <div className="boss-kv"><span>到期时刻</span><strong>{displayTime(taskDue.due_at)}</strong></div>
            <div className="boss-kv"><span>事件状态</span><strong>{taskDue.event_state}</strong></div>
            <div className="boss-kv"><span>实际派发检查</span><strong>{taskDue.dispatch_state}</strong></div>
            <div className="boss-kv"><span>抑制原因</span><strong>{taskDue.dispatch_reason||"无记录"}</strong></div>
          </> : <p className="boss-helper">
            尚未经老板独立授权发送的任务不会启动到期催办；当前没有已登记的任务到期事件。
          </p>}
          <p className="boss-helper">
            仅注册本机模拟到期事件。取消或确认完成后终止后续催办，延期须由老板批准；
            当前不具备真实外部通知送达证明。
          </p>
        </section>
        <section className="boss-panel">
          <div className="boss-panel-head"><h2>关联发件与回复状态</h2><small>F06 / F08 同一任务 ID · 真实 SQLite</small></div>
          {linkedMessages.length ? linkedMessages.map(message=>
            <div key={message.message_id} className="boss-feedback">
              <div><span className="boss-tag boss-tag-blue">{message.type}</span>
                <small>{displayTime(message.sent_at)}</small></div>
              <div className="boss-kv"><span>消息编号</span><strong>{message.message_id}</strong></div>
              <p>{message.body}</p><p>本人授权 {message.authorization_id??"当时未记录"}</p>
              <div className="boss-kv"><span>收件人</span><strong>{message.recipient_id}</strong></div>
              <div className="boss-kv"><span>模拟发送</span><strong>{message.send_state}</strong></div>
              <div className="boss-kv"><span>真实送达</span><strong>{message.delivery_state}</strong></div>
              <div className="boss-kv"><span>回复</span><strong>{message.reply_state}</strong></div>
            </div>
          ) : <p className="boss-helper">当前交办尚无已保存的模拟发件；任务创建并不等于发送。</p>}
          <p className="boss-helper">
            两类消息分别来自 F06 交办发件箱和 F08 后续发件箱；
            NOT_VERIFIED 表示没有真实外部送达证明，不可解释为已经送达。
          </p>
          {messagesEnabled&&<div className="boss-actions">
            <button type="button" className="boss-btn" onClick={onViewMessages}>
              <MessageSquareText size={15}/> 查看 F08 消息与回复
            </button>
          </div>}
        </section>
        <section className="boss-panel">
          <div className="boss-panel-head"><h2>反馈与本人决定</h2><small>进展、结果提交、确认完成分别记录</small></div>
          {feedback.length ? feedback.map(f=><div className="boss-feedback" key={f.feedback_id}>
            <div><span className="boss-tag boss-tag-amber">{f.kind}</span><small>{displayTime(f.submitted_at)}</small></div>
            <p>{f.content||"未提供正文"}</p>
            <small>作者：{f.author_contact_id||"待核查"} · 提交时任务版本：{f.task_version??"未知"} · {f.historical_only?"仅保留历史":"当前反馈"}</small>
            <div className="boss-actions">{f.evidence_refs?.map(id=><button className="boss-btn" key={id} type="button" onClick={()=>onViewSource(id)}>查看反馈原文 {id} · v{f.evidence_versions?.[id]??"未知"} · {f.evidence_states?.[id]??"待核查"}</button>)}</div>
            {f.proposed_due_at && <small>申请新期限：{displayTime(f.proposed_due_at)}</small>}
          </div>):<p className="boss-helper">暂无署名反馈。不能提前认定完成。</p>}
          <div className="boss-actions">
            <button className="boss-btn boss-btn-primary" type="button"
              disabled={!current||current.status!=="RESULT_SUBMITTED"||!completed||current.source_reference_state!=="CURRENT"||current.result_evidence_requires_resubmission||busy} onClick={prepareComplete}>
              <CheckCircle2 size={15}/> 核查证据并确认完成</button>
          </div>
          {current?.result_evidence_requires_resubmission&&<p role="status">当前结果证据已经变化，需要负责人重新提交，确认来源不能代替重新提交结果。</p>}
          {current?.status==="RESULT_SUBMITTED"&&!completed&&<p role="status">当前结果缺少完成证据，需要负责人补充并重新提交。</p>}
          <div className="boss-form-grid boss-form-below">
            <label>新期限（北京时间）<input type="datetime-local" value={newDue} onChange={e=>onDraftChange("newDue",e.target.value)}/></label>
          </div>
          {extension&&<p>当前延期申请 {extension.feedback_id} · 申请期限 {displayTime(extension.proposed_due_at)} · 理由 {extension.content}；当前期限仍为 {displayTime(current?.due_at)}。</p>}
          <label className="boss-label">本人决定理由</label>
          <input aria-label="本人决定理由" className="boss-single-input" value={reason} onChange={e=>onDraftChange("reason",e.target.value)} placeholder="填写延期决定或取消的具体理由"/>
          <div className="boss-actions"><button type="button" className="boss-btn" disabled={!extension||busy||current?.source_reference_state!=="CURRENT"||["CANCELED","COMPLETED_CONFIRMED"].includes(current?.status??"")}
            onClick={()=>prepareExtend("APPROVE")}><Clock3 size={15}/> 本人核查并批准延期</button>
            <button type="button" className="boss-btn" disabled={!extension||busy||["CANCELED","COMPLETED_CONFIRMED"].includes(current?.status??"")} onClick={()=>prepareExtend("REJECT")}>本人核查并拒绝延期</button></div>
          {extensionHistory?.decisions.map(decision=><article className="boss-feedback" key={decision.decision_id}><p>延期决定 {decision.decision} · {decision.feedback_id} · {displayTime(decision.decided_at)}</p><p>原期限 {displayTime(decision.old_due_at)} · 决定后期限 {displayTime(decision.new_due_at)} · 版本 {decision.previous_task_version} → {decision.task_version}</p><p>申请理由：{decision.request_reason}</p><p>本人理由：{decision.reason??"当时未记录"}</p></article>)}
          <div className="boss-actions"><button type="button" className="boss-btn" onClick={prepareCancel}
            disabled={!current||busy||["CANCELED","COMPLETED_CONFIRMED"].includes(current.status)}>
            <XCircle size={15}/> 核对并取消交办</button></div>
        </section>
        {error && <div role="alert" className="boss-status boss-status-error"><AlertCircle size={16}/>{error}</div>}
        {notice && <div role="status" className="boss-status boss-status-ok"><CheckCircle2 size={16}/>{notice}</div>}
      </div>
    </div>
    {dialog}
    {recovery}
  </div>;
}

export function MaintainerFeedback({tasks,onReload}:{
  tasks:MaintenanceTaskRef[];onReload:()=>void;
}) {
  const {propose,dialog,recovery,notice}=useTransaction(onReload,undefined,undefined,"feedback");
  const [selected,setSelected]=useState("");
  const [kind,setKind]=useState<"PROGRESS"|"EXTENSION_REQUEST"|"RESULT_SUBMITTED">("PROGRESS");
  const [text,setText]=useState("");
  const [source,setSource]=useState("finance-note");
  const [date,setDate]=useState("");
  const [error,setError]=useState("");
  const current=tasks.find(t=>t.task_id===selected);
  const prepare=()=>{
    setError("");
    try {
      if(!current?.coordinator_id)throw new Error("请选择有负责人信息的有效交办。");
      const content=required(text,"模拟反馈"),proof=required(source,"证据来源");
      const payload:Record<string,unknown>={
        task_id:current.task_id,task_version:current.version,
        author_contact_id:current.coordinator_id,kind,content,evidence_refs:[proof],
      };
      if(kind==="EXTENSION_REQUEST")payload.proposed_due_at=shanghai(date);
      propose("boss.simulation.feedback",payload,"模拟负责人反馈确认",[
        "交办："+current.task_id,"任务版本："+current.version,
        "反馈人："+current.coordinator_id,"类型："+kind,
        "内容："+content,"证据："+proof,
        ...(kind==="EXTENSION_REQUEST"?["申请期限："+String(payload.proposed_due_at)]:[]),
        "维护角色只能注入模拟反馈，不能替老板确认完成或批准延期。",
      ]);
    } catch(e) {setError(e instanceof Error?e.message:String(e));}
  };
  return <>
    <section className="boss-panel boss-assignment-scope">
      <div className="boss-panel-head"><h2>模拟负责人反馈</h2><small>A04 · MAINTAINER 权限</small></div>
      <div className="boss-form-grid">
        <label>任务技术标识<select value={selected} onChange={e=>setSelected(e.target.value)}>
          <option value="">请选择待反馈交办</option>
          {tasks.filter(t=>t.status!=="COMPLETED_CONFIRMED").map(t=>
            <option key={t.task_id} value={t.task_id}>{t.task_id} · {t.status} · v{t.version}{t.status==="CANCELED"?" · 仅保留历史":""}</option>)}
        </select></label>
        <label>反馈类型<select value={kind} onChange={e=>setKind(e.target.value as typeof kind)}>
          <option value="PROGRESS">进展反馈</option>
          <option value="EXTENSION_REQUEST">延期申请</option>
          <option value="RESULT_SUBMITTED">结果提交</option>
        </select></label>
        <label>证据引用<input value={source} onChange={e=>setSource(e.target.value)}/></label>
        {kind==="EXTENSION_REQUEST"&&<label>拟申请新期限<input type="datetime-local" value={date}
          onChange={e=>setDate(e.target.value)}/></label>}
      </div>
      <label className="boss-label">署名模拟反馈正文</label>
      <textarea rows={3} value={text} onChange={e=>setText(e.target.value)} placeholder="描述进展或提交的模拟证据"/>
      {error && <p role="alert" className="boss-validation-error">{error}</p>}
      {notice && <div role="status" className="boss-status boss-status-ok">{notice}</div>}
      <div className="boss-actions">
        <button type="button" className="boss-btn boss-btn-primary" onClick={prepare}>
          <ShieldCheck size={15}/> 核对并注入反馈</button>
        <button type="button" className="boss-btn" onClick={onReload}><RefreshCw size={15}/> 重新查询</button>
      </div>
      <p className="boss-helper">模拟回复与老板业务决定独立存储；仅老板可以审批、延期或确认完成。</p>
      {current?.status==="CANCELED"&&<p role="status">当前交办已经取消，反馈仅保留历史，不恢复任务或催办。</p>}
    </section>
    {dialog}
    {recovery}
  </>;
}
