import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type {MorningReference} from "./BossMorningView";
import type {MorningPreparationContext} from "./BossMorningPreparation";
import {
  AlertCircle, CheckCircle2, Loader2, RefreshCw, ShieldCheck,
} from "lucide-react";
import { useClient } from "@/providers/ClientProvider";
import type { AssignmentDraft } from "./BossAssignmentPicker";
import {BossAssignmentDetails} from "./BossAssignmentDetails";
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
  related_meeting_id?:string|null;related_event_ids?:string[];related_task_id?:string|null;
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
  insights: import("./BossInsightList").BossInsight[];
  tasks: AssignmentTask[];
  business_clock?:string;source_type?:string;namespace?:string;data_version?:string;
  feedback?: TaskFeedback[];
  linked_messages?: TaskLinkedMessage[];
  task_due_events?: TaskDueEvent[];
}
export interface AssignmentContext {
  namespace?:string;dataset_version?:string;business_clock?:string;
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
  | "boss.owner.goals.save" | "boss.owner.goals.confirm"
  | "boss.minutes.save" | "boss.minutes.confirm" | "boss.minutes.assignment.create" | "boss.approval.decide" | "boss.simulation.application.seed" | "boss.simulation.application.revise"
  | "boss.owner.plan.save" | "boss.owner.plan.pause" | "boss.owner.plan.resume" | "boss.owner.plan.cancel"
  | "boss.scheduler.draft.save" | "boss.scheduler.draft.validate" | "boss.scheduler.activate" | "boss.scheduler.manual_run" | "boss.scheduler.pause" | "boss.scheduler.resume" | "boss.scheduler.cancel"
  | "boss.alert.ack" | "boss.alert.snooze" | "boss.alert.close" | "boss.alert.meeting.link" | "boss.alert.assignment.create"
  | "boss.alert.rule.save" | "boss.alert.rule.validate" | "boss.alert.rule.activate" | "boss.alert.rule.disable"
  | "boss.simulation.alert.rule.save" | "boss.simulation.alert.rule.validate" | "boss.simulation.alert.rule.activate" | "boss.simulation.alert.rule.disable" | "boss.simulation.alert.load"
  | "boss.message.draft.save" | "boss.message.send" | "boss.research.prepare"
  | "boss.people.prepare" | "boss.people.attach" | "boss.people.detach"
  | "boss.meeting.brief.prepare" | "boss.meeting.draft.save" | "boss.meeting.confirm" | "boss.meeting.cancel" | "boss.meeting.held"
  | "boss.travel.review" | "boss.travel.confirm" | "boss.travel.cancel"
  | "boss.calendar.save" | "boss.calendar.share" | "boss.calendar.share.revoke" | "boss.calendar.delete"
  | "boss.sector.coordinate.create" | "boss.sector.review.schedule" | "boss.sector.meeting.prepare" | "boss.sector.decision.save";
type Result = {
  tasks_created?:number;messages_sent?:number;decision_count_confirmed?:number;
  record_id?:string;record_version?:string;page_id?:string;query_id?:string;execution_namespace?:string;action_code?:string;
  message_sent?:boolean;message_id?:string;send_state?:string;recipient_id?:string;external_channel_invoked?:boolean;research_id?:string;brief_id?:string;meeting_id?:string;travel_id?:string;calendar_id?:string;share_id?:string;share_status?:string;
  task_id?: string; task?: { task_id: string; status: string; version: string };
  status?: string; state?:string;version?: string; feedback_id?: string; draft_id?: string; commitment_id?:string;event_id?:string;event_version?:string;plan_id?:string;application_id?:string;minute_id?:string;
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

type TransactionScope="assignment"|"feedback"|"commitment"|"reminder"|"ownerNotice"|"ownerGoals"|"plan"|"scheduler"|"alerts"|"alertRules"|"alertInput"|"meetingApproval"|"minutesAssignment"|"research"|"people"|"meetingBrief"|"meetingArrangement"|"travel"|"privateCalendar"|"messageOperation"|"sectorOperation";
const TRANSACTION_ACTIONS:Record<TransactionScope,Action[]>={
  assignment:["boss.assignment.create","boss.assignment.send","boss.assignment.nudge","boss.assignment.extend","boss.assignment.extension.decide","boss.assignment.cancel","boss.assignment.complete","boss.message.draft.save"],
  feedback:["boss.simulation.feedback"],commitment:["boss.commitment.create","boss.commitment.extend","boss.commitment.cancel","boss.commitment.complete"],
  reminder:["boss.reminder.ack","boss.reminder.snooze","boss.reminder.close"],ownerNotice:["boss.owner.notice.save","boss.owner.notice.confirm"],ownerGoals:["boss.owner.goals.save","boss.owner.goals.confirm"],
  plan:["boss.owner.plan.save","boss.owner.plan.pause","boss.owner.plan.resume","boss.owner.plan.cancel"],
  scheduler:["boss.scheduler.draft.save","boss.scheduler.draft.validate","boss.scheduler.activate","boss.scheduler.manual_run","boss.scheduler.pause","boss.scheduler.resume","boss.scheduler.cancel"],
  alerts:["boss.alert.ack","boss.alert.snooze","boss.alert.close","boss.alert.meeting.link","boss.alert.assignment.create"],
  alertRules:["boss.alert.rule.save","boss.alert.rule.validate","boss.alert.rule.activate","boss.alert.rule.disable","boss.simulation.alert.rule.save","boss.simulation.alert.rule.validate","boss.simulation.alert.rule.activate","boss.simulation.alert.rule.disable"],
  alertInput:["boss.simulation.alert.load"],
  meetingApproval:["boss.minutes.save","boss.minutes.confirm","boss.approval.decide","boss.simulation.application.seed","boss.simulation.application.revise"],
  minutesAssignment:["boss.minutes.assignment.create"],
  research:["boss.research.prepare","boss.message.draft.save"],
  people:["boss.people.prepare","boss.people.attach","boss.people.detach"],
  meetingBrief:["boss.meeting.brief.prepare","boss.message.draft.save"],
  meetingArrangement:["boss.meeting.draft.save","boss.meeting.confirm","boss.meeting.cancel","boss.meeting.held"],
  travel:["boss.travel.review","boss.travel.confirm","boss.travel.cancel"],
  privateCalendar:["boss.calendar.save","boss.calendar.share","boss.calendar.share.revoke","boss.calendar.delete"],
  messageOperation:["boss.message.draft.save","boss.message.send"],
  sectorOperation:["boss.sector.coordinate.create","boss.sector.review.schedule","boss.sector.meeting.prepare","boss.sector.decision.save"],
};
export function useTransaction(onReload: (recorded?:boolean,action?:string) => void, onCreated?: (id: string) => void, onMessageDraftCreated?: (id: string) => void, scope:TransactionScope="assignment") {
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
    if(new URLSearchParams(window.location.search).has(scope+"Request")){setError("当前原请求仍需核查，请查询同一编号。");return false;}
    setPending({ action, payload, id: "boss-" + crypto.randomUUID(), title, preview, target:scope==="messageOperation"&&typeof payload.draft_id==="string"?payload.draft_id:scope==="privateCalendar"&&typeof payload.share_id==="string"?payload.share_id:scope==="travel"&&typeof payload.travel_id==="string"?payload.travel_id:scope==="meetingArrangement"&&typeof payload.meeting_id==="string"?payload.meeting_id:typeof payload.task_id==="string"?payload.task_id:typeof payload.commitment_id==="string"?payload.commitment_id:typeof payload.event_id==="string"?payload.event_id:typeof payload.plan_id==="string"?payload.plan_id:typeof payload.application_id==="string"?payload.application_id:typeof payload.brief_id==="string"?payload.brief_id:"" });
    setUncertain(false);
    setApproved(false); setError(""); setNotice("");
    return true;
  }, [scope]);
  const submit = useCallback(async () => {
    if (!pending || !approved || busy || uncertain || pending.restored) return;
    const current=epoch.current;remember(pending);setUncertain(true);setBusy(true); setError("");
    try {
      const result = await client.requestMutation<Result>(
        pending.action, { ...pending.payload, client_request_id: pending.id },
      );
      if(current!==epoch.current)return;
      if(scope==="sectorOperation"&&(!result.record_id||!result.record_version||result.page_id!==pending.payload.page_id||result.query_id!==pending.payload.query_id||result.execution_namespace!==pending.payload.execution_namespace||result.action_code!==pending.payload.action_code||result.messages_sent!==0||result.external_channel_invoked!==false))throw new Error("专题操作回执与查询范围、执行空间或保存后果不匹配");
      if(pending.action==="boss.minutes.save"&&(!result.minute_id||result.meeting_id!==pending.payload.meeting_id||!result.version||result.state!=="DRAFT_REVIEW"||result.tasks_created!==0||result.messages_sent!==0||result.decision_count_confirmed!==0))throw new Error("纪要草稿回执与当前会议或保存范围不匹配");
      if((scope==="reminder"||scope==="alerts")&&(!result.event_id||result.event_id!==pending.target||result.event_version!==pending.payload.event_version||!result.version))throw new Error("提醒回执与当前事件、版本或决定不匹配");
      if(scope==="messageOperation"){
        if(!result.draft_id||pending.target&&pending.target!==result.draft_id)throw new Error("消息回执与当前草稿不匹配");
        if(pending.action==="boss.message.draft.save"&&(result.status!=="DRAFT"||result.message_sent!==false))throw new Error("草稿回执缺少未发送状态");
        if(pending.action==="boss.message.send"){
          if(!result.message_id||result.send_state!=="SENT_SIMULATED"||result.external_channel_invoked!==false||result.recipient_id!==pending.payload.recipient_id)throw new Error("发送回执与当前收件人或发送状态不匹配");
          onMessageDraftCreated?.(result.draft_id);
        }
      }
      if(TRANSACTION_ACTIONS.privateCalendar.includes(pending.action)){
        const object=pending.action.includes(".share")?result.share_id:result.calendar_id;
        if(!object||pending.target&&pending.target!==object)throw new Error("私人安排回执与当前对象不匹配");
      }
      if(TRANSACTION_ACTIONS.meetingArrangement.includes(pending.action)&&(!result.meeting_id||result.meeting_id!==pending.target))throw new Error("会议回执与当前对象不匹配");
      if(TRANSACTION_ACTIONS.travel.includes(pending.action)){
        if(!result.travel_id||pending.target&&result.travel_id!==pending.target)throw new Error("行程回执与当前对象不匹配");
        onCreated?.(result.travel_id);
      }
      if(pending.action.startsWith("boss.people.")){
        if(!result.brief_id||pending.target&&pending.target!==result.brief_id)throw new Error("会面材料回执与当前对象不匹配");
        onCreated?.(result.brief_id);
      }
      if(pending.action==="boss.minutes.assignment.create"){
        if(!result.task_id||result.status!=="OPEN"||result.message_sent!==false)throw new Error("当前交办回执需要核查未发送状态");
        onCreated?.(result.task_id);
      }
      if (pending.action === "boss.assignment.create" && result.task_id) onCreated?.(result.task_id);
      if (pending.action === "boss.commitment.create" && result.commitment_id) onCreated?.(result.commitment_id);
      if (pending.action === "boss.message.draft.save" && result.draft_id) onMessageDraftCreated?.(result.draft_id);
      setNotice("实际模拟业务已保存。状态：" + (result.status || result.state || result.send_state || result.share_status || result.task?.status || "已记录") +
        "；对象：" + (result.record_id || result.task_id || result.task?.task_id || result.commitment_id || result.event_id || result.plan_id || result.application_id || result.minute_id || result.research_id || result.draft_id || result.brief_id || result.meeting_id || result.travel_id || result.calendar_id || result.share_id || "未知") + "。请重读当前状态。");
      remember(null);setUncertain(false);setPending(null); setApproved(false); onReload(true,pending.action);
    } catch (e) {
      if(current!==epoch.current)return;
      const status=e instanceof Error&&"status" in e&&typeof e.status==="number"?e.status:null;
      if(status!==null&&[400,401,403,404,409,410,413,422].includes(status)){setUncertain(false);remember(null);}
      if(status===401||status===403){setPending(null);setApproved(false);setNotice("");if(status===401)window.dispatchEvent(new Event("boss-auth-expired"));}
      setError((e instanceof Error ? e.message : String(e)) +
        "。请核查正式状态；结果尚未确定时仅查询原请求编号。");
    } finally { if(current===epoch.current)setBusy(false); }
  }, [approved, busy, client, onCreated, onMessageDraftCreated, onReload, pending,uncertain,remember,scope]);
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
        action:string;client_request_id:string;outcome:string;result?:Result;write_performed_by_lookup?:boolean;
      };
      if(current!==epoch.current)return;
      if(body.action!==pending.action||body.client_request_id!==pending.id)
        throw new Error("操作回执身份与本次动作不匹配");
      if(body.outcome==="RECORDED"&&body.result){
        if(scope==="sectorOperation"&&(body.write_performed_by_lookup!==false||!body.result.record_id||!body.result.record_version||!body.result.page_id||!body.result.query_id||!body.result.execution_namespace||!body.result.action_code||body.result.messages_sent!==0||body.result.external_channel_invoked!==false||pending.payload.query_id&&body.result.query_id!==pending.payload.query_id||pending.payload.execution_namespace&&body.result.execution_namespace!==pending.payload.execution_namespace||pending.payload.action_code&&body.result.action_code!==pending.payload.action_code))throw new Error("原专题操作回执缺少查询依据或与当前请求不符");
        if(pending.action==="boss.minutes.save"&&(body.write_performed_by_lookup!==false||!body.result.minute_id||!body.result.meeting_id||!body.result.version||body.result.state!=="DRAFT_REVIEW"||body.result.tasks_created!==0||body.result.messages_sent!==0||body.result.decision_count_confirmed!==0||pending.payload.meeting_id&&body.result.meeting_id!==pending.payload.meeting_id))throw new Error("原纪要草稿回执缺少只读依据或保存范围不符");
        if((scope==="reminder"||scope==="alerts")&&(!body.result.event_id||!body.result.event_version||!body.result.version||pending.payload.event_version&&body.result.event_version!==pending.payload.event_version))throw new Error("原提醒回执缺少事件版本或与当前请求不匹配");
        if(scope==="messageOperation"){
          if(body.write_performed_by_lookup!==false||!body.result.draft_id)throw new Error("原消息回执缺少只读核查依据或草稿编号");
          if(pending.action==="boss.message.draft.save"&&(body.result.status!=="DRAFT"||body.result.message_sent!==false))throw new Error("原草稿回执缺少未发送状态");
          if(pending.action==="boss.message.send"){
            if(!body.result.message_id||body.result.send_state!=="SENT_SIMULATED"||body.result.external_channel_invoked!==false||!body.result.recipient_id)throw new Error("原发送回执缺少收件人或发送结果");
            if(pending.payload.recipient_id&&body.result.recipient_id!==pending.payload.recipient_id)throw new Error("原发送回执与收件人不匹配");
          }
        }
        if(pending.action==="boss.minutes.assignment.create"){
          if(!body.result.task_id||body.result.status!=="OPEN"||body.result.message_sent!==false)throw new Error("原交办回执需要核查未发送状态");
          onCreated?.(body.result.task_id);
        }
        const target=scope==="messageOperation"?body.result.draft_id:TRANSACTION_ACTIONS.privateCalendar.includes(pending.action)?pending.action.includes(".share")?body.result.share_id:body.result.calendar_id:TRANSACTION_ACTIONS.travel.includes(pending.action)?body.result.travel_id:TRANSACTION_ACTIONS.meetingArrangement.includes(pending.action)?body.result.meeting_id:pending.action.startsWith("boss.alert.")?body.result.event_id:body.result.task_id??body.result.task?.task_id??body.result.commitment_id??body.result.event_id??body.result.plan_id??body.result.application_id??body.result.brief_id;
        if(TRANSACTION_ACTIONS.privateCalendar.includes(pending.action)&&!target)throw new Error("原请求回执缺少私人安排或分享编号");
        if(pending.target&&pending.target!==target)throw new Error("原请求回执不属于当前业务对象");
        if(scope==="messageOperation"&&pending.action==="boss.message.send"&&body.result.draft_id)onMessageDraftCreated?.(body.result.draft_id);
        if(TRANSACTION_ACTIONS.travel.includes(pending.action)){
          if(!body.result.travel_id)throw new Error("原请求回执缺少行程标识");
          onCreated?.(body.result.travel_id);
        }
        if(pending.action.startsWith("boss.people.")){
          if(!body.result.brief_id)throw new Error("原请求回执缺少会面材料标识");
          onCreated?.(body.result.brief_id);
        }
        if(pending.action==="boss.assignment.create"&&body.result.task_id)
          onCreated?.(body.result.task_id);
        if(pending.action==="boss.commitment.create"&&body.result.commitment_id)onCreated?.(body.result.commitment_id);
        if(pending.action==="boss.message.draft.save"&&body.result.draft_id)
          onMessageDraftCreated?.(body.result.draft_id);
        setNotice("原请求回执已确认当前操作保存成功，正式状态正在重读。");
        remember(null);setUncertain(false);setPending(null);setApproved(false);onReload(true,pending.action);
      }else if(body.outcome==="NOT_FOUND_IN_CURRENT_STORE"){
        setError("当前没有该请求回执，执行结果仍未确定，请继续读取同一原编号。");
        onReload();
      }else throw new Error("服务端回执格式无效，不能假定已执行");
    } catch(e) {
      if(current===epoch.current)setError(e instanceof Error?e.message:String(e));
    }finally{if(current===epoch.current)setLookupBusy(false);}
  },[pending,busy,lookupBusy,getToken,onCreated,onMessageDraftCreated,onReload,remember,scope]);
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
  const recovery=!pending&&unresolved?<BossOriginalReceipt scope={scope} actions={TRANSACTION_ACTIONS[scope]} onRecorded={()=>onReload(true)}/>:null;
  return { propose, dialog, recovery, notice, busy:busy||uncertain||lookupBusy||(!pending&&unresolved) };
}

export function BossAssignmentFlow({ tasks, selectedTaskId, onSelectTask, onReload, onViewSource, context,
  draft, onDraftChange, onDraftSaved, onOpenCoordinatorPicker, onOpenDuePicker,
  onViewMessages, onMessageDraftCreated, morningReference, morningReady=true, morningContext, messagesEnabled=true,
  loading=false,onDirtyChange,onNavigate,onDiscard,onNew,sourceReview,conversation }: {
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
  loading?:boolean;onDirtyChange?:(dirty:boolean)=>void;onNavigate:(page:string)=>void;onDiscard:()=>void;onNew:(task?:AssignmentTask)=>void;sourceReview?:ReactNode;conversation?:ReactNode;
}) {
  const { propose, dialog, recovery, notice, busy:transactionBusy } = useTransaction(recorded=>{if(recorded)onDraftSaved();onReload();}, id => {
    onSelectTask(id,true); onDraftSaved();
  }, onMessageDraftCreated);
  const {purpose,coordinator,due,evidence,body,newDue,reason,timezone}=draft;
  const [error,setError]=useState("");
  const busy=transactionBusy||Boolean(dialog);
  const {getToken,token}=useClient();
  const [extensionHistory,setExtensionHistory]=useState<{task_id:string;task_version:string;due_at:string;decisions:{decision_id:string;feedback_id:string;decision:"APPROVE"|"REJECT";old_due_at:string;new_due_at:string;reason:string|null;request_reason:string;decided_at:string;previous_task_version:string;task_version:string}[]}|null>(null);
  const rows=loading?[]:tasks?.tasks||[];
  const current=rows.find(t=>t.task_id===selectedTaskId);
  const contactName=(id?:string)=>{
    if(!id)return "尚未选择";
    const contact=context?.contacts.find(item=>item.contact_id===id);
    return contact?contact.name+"（"+contact.organization+" · "+contact.responsibility+"）":id;
  };
  const feedback=useMemo(()=>(tasks?.feedback||[]).filter(f=>current&&f.task_id===current.task_id),[current,tasks]);
  const linkedMessages=useMemo(()=>(tasks?.linked_messages||[]).filter(
    row=>current&&row.task_id===current.task_id
  ),[current,tasks]);
  const taskDue=useMemo(()=>(tasks?.task_due_events||[]).find(
    row=>current&&row.task_id===current.task_id
  ),[current,tasks]);
  const currentBasis=current?JSON.stringify([tasks?.namespace,tasks?.data_version,current,feedback]):context?JSON.stringify([context.namespace,context.dataset_version,context.meeting,context.event,context.contacts,context.assignment_source_ids,morningReference,morningContext]):"";
  const stale=Boolean(draft.basis&&currentBasis&&draft.basis!==currentBasis);
  const editable=!loading&&!busy&&!stale;
  const sourceIds=morningReference?morningContext?.source_ids??[]:(draft.sourceIds?draft.sourceIds.split("\n").map(item=>item.trim()).filter(Boolean):context?.assignment_source_ids??[]);
  const meetingId=morningReference?morningContext?.meeting_id??null:draft.meetingId||context?.meeting?.meeting_id||null;
  const eventIds=morningReference?morningContext?.event_ids??[]:draft.eventIds?draft.eventIds.split("\n").map(item=>item.trim()).filter(Boolean):context?.event?[context.event.event_id]:[];
  const clock=tasks?.business_clock??context?.business_clock,terminal=Boolean(current&&["CANCELED","COMPLETED_CONFIRMED"].includes(current.status));
  const overdue=current?.due_at&&clock&&!terminal&&Number.isFinite(Date.parse(current.due_at))&&Number.isFinite(Date.parse(clock))?Date.parse(current.due_at)<Date.parse(clock):null;
  useEffect(()=>{onDirtyChange?.(busy);return()=>onDirtyChange?.(false);},[busy,onDirtyChange]);
  function edit(field:keyof AssignmentDraft,value:string){if(!editable)return;if(!draft.basis)onDraftChange("basis",currentBasis);onDraftChange(field,value);}
  function absolute(value:string,label:string){if(!Number.isFinite(Date.parse(value))||!/(Z|[+-]\d{2}:\d{2})$/.test(value))throw new Error("请填写包含UTC时差的完整"+label);return value;}
  const result=[...feedback].reverse().find(f=>f.kind==="RESULT_SUBMITTED"&&!f.historical_only);
  const completed=result?.evidence_refs?.length?result:undefined;
  const currentExtensions=extensionHistory?.task_id===current?.task_id&&extensionHistory?.task_version===current?.version?extensionHistory:null;
  const extension=currentExtensions?[...feedback].reverse().find(f=>f.kind==="EXTENSION_REQUEST"&&!f.historical_only&&!currentExtensions.decisions.some(decision=>decision.feedback_id===f.feedback_id)):undefined;
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
  const safe=(fn:()=>void)=>{if(!editable)return;setError("");try{fn()}catch(e){setError(e instanceof Error?e.message:String(e))}};
  const prepareCreate=()=>safe(()=>{
    if(morningReference&&(!morningReady||!morningContext?.source_ids.length))throw new Error("请重新核查当前晨间事项与来源版本");
    if(!context||!sourceIds.length||sourceIds.some(id=>!(morningReference?morningContext?.source_ids:context.assignment_source_ids)?.includes(id)))throw new Error("创建交办需要当前获准来源。");
    const purposeText=required(purpose,"目的"),proof=required(evidence,"验收依据").split("\n").map(item=>item.trim()).filter(Boolean);
    if(proof.length>8||proof.some(item=>item.length>160))throw new Error("验收依据最多8项，每项最多160字。");
    if(!coordinator||!context.contacts.some(c=>c.contact_id===coordinator))
      throw new Error("请选择获准的唯一负责人");
    if(!due.trim()||!timezone.trim())throw new Error("请选择截止时间与时区。");
    const dueAt=absolute(due,"截止时间"),zone=required(timezone,"时区");new Intl.DateTimeFormat("zh-CN",{timeZone:zone}).format(new Date(dueAt));
    if(!clock||!Number.isFinite(Date.parse(clock)))throw new Error("尚未取得有效业务时钟，请重新读取。");
    if(Date.parse(dueAt)<=Date.parse(clock))throw new Error("交办期限必须晚于当前业务时钟。");
    propose("boss.assignment.create",{
      purpose:purposeText,coordinator_id:coordinator,due_at:dueAt,
      timezone:zone,evidence_requirements:proof,
      related_meeting_id:meetingId,
      related_event_ids:eventIds,
      source_refs:sourceIds,content_version:"1",
      ...(morningReference?{morning_reference:morningReference}:{}),
      ...(draft.relatedTask?{related_task_id:draft.relatedTask,related_task_version:draft.relatedTaskVersion}:{}),
    },"核对并创建交办",[
      "目的："+purposeText,"唯一负责人："+contactName(coordinator)+" · "+coordinator,
      "截止时间："+displayTime(dueAt)+" · "+zone,
      "验收依据："+proof.join("；"),"会议："+(meetingId??"没有关联会议"),
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
      "交办："+current.task_id+" v"+current.version,"目的："+current.purpose,"唯一负责人："+contactName(current.coordinator_id)+" · "+current.coordinator_id,
      "截止时间："+displayTime(current.due_at)+" · "+(current.timezone??"时区待核查"),"依据："+(current.source_refs??[]).map(id=>id+" v"+(current.source_versions?.[id]??"未知")).join("；"),
      "正文："+message,"仅写入模拟发件箱，不会真正发送至外部人员。",
    ]);
  });
  const lastNudge=[...linkedMessages].reverse().find(row=>row.type==="ASSIGNMENT_NUDGE");
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
      "目的："+current.purpose,"截止时间："+displayTime(current.due_at)+" · "+(current.timezone??"时区待核查"),
      "收件人："+contactName(current.coordinator_id)+" · "+current.coordinator_id,"催办正文："+message,
      "上次催办："+(lastNudge?displayTime(lastNudge.sent_at):"已读取记录中没有催办"),
      "只记录本地模拟发件，真正送达仍待核查；24小时模拟时钟内禁止重复催办。",
    ]);
  });
  const prepareFollowup=()=>safe(()=>{
    if(!current||!current.version||!current.coordinator_id)
      throw new Error("请先选择已保存的交办任务");
    if(!["WAITING_FEEDBACK","IN_PROGRESS","RESULT_SUBMITTED"].includes(current.status))
      throw new Error("当前任务状态不能准备后续沟通草稿");
    if(current.status!=="RESULT_SUBMITTED"&&current.source_reference_state!=="CURRENT")
      throw new Error("原始资料已经变化，不能据此继续催办");
    const message=required(body,"后续沟通正文");
    propose("boss.message.draft.save",{
      draft_id:null,expected_version:"0",
      recipient_id:current.coordinator_id,
      related_task_id:current.task_id,body:message,
      attachment_refs:[],visibility:"RECIPIENT_ONLY",
    },current.status==="RESULT_SUBMITTED"?"保存补材料草稿":"保存沟通草稿",[
      "关联任务："+current.task_id,
      "唯一负责人："+contactName(current.coordinator_id)+" · "+current.coordinator_id,
      "当前任务状态："+current.status,
      "草稿正文："+message,
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
    },"验收并确认完成",[
      "交办："+current.task_id+" v"+current.version,"目的："+current.purpose,"唯一负责人："+contactName(current.coordinator_id)+" · "+current.coordinator_id,"结果提交："+completed.feedback_id,
      "证据："+(completed.evidence_refs||[]).map(id=>id+" v"+(completed.evidence_versions?.[id]??"未知")).join("；"),
      "仅在本人确认后更新为 COMPLETED_CONFIRMED。",
    ]);
  });
  const prepareExtend=(decision:"APPROVE"|"REJECT")=>safe(()=>{
    if(!current||!extension||!current.version)throw new Error("未取得有效延期申请。");
    const date=decision==="APPROVE"?absolute(newDue,"新期限"):null;
    if(date&&(!clock||!Number.isFinite(Date.parse(clock))||Date.parse(date)<=Date.parse(clock)))throw new Error("新期限必须晚于当前业务时钟。");
    const note=required(reason,"本人决定理由");
    propose("boss.assignment.extension.decide",{
      task_id:current.task_id,task_version:current.version,
      feedback_id:extension.feedback_id,due_at:date,decision,reason:note,
    },decision==="APPROVE"?"本人批准延期":"本人拒绝延期",[
      "交办："+current.task_id+" · 当前版本 "+current.version,
      "原期限："+displayTime(current.due_at)+" · "+(current.timezone??"时区待核查"),
      "延期依据："+extension.feedback_id,"申请期限："+displayTime(extension.proposed_due_at)+" · "+(current.timezone??"时区待核查"),"申请理由："+extension.content,
      "本人决定："+decision,"决定后期限："+displayTime(date??current.due_at),"本人理由："+note,
      "未批准前旧期限持续有效。",
    ]);
  });
  const prepareCancel=(reasonText:string)=>safe(()=>{
    if(!current||!current.version)throw new Error("请选择有效任务。");
    const why=required(reasonText,"取消原因");
    propose("boss.assignment.cancel",{
      task_id:current.task_id,task_version:current.version,reason:why,
    },"确认取消交办",[
      "交办："+current.task_id+" v"+current.version,"目的："+current.purpose,"唯一负责人："+contactName(current.coordinator_id)+" · "+current.coordinator_id,"原因："+why,
      "取消后停止未来催办；先前已发送的模拟消息和历史反馈不会撤销。",
    ]);
  });
  return <div className="boss-assignment-scope">
    <BossAssignmentDetails rows={rows} selectedTaskId={selectedTaskId} current={current} context={context} draft={draft} feedback={feedback} messages={linkedMessages} taskDue={taskDue}
      extensions={currentExtensions} extension={extension} completed={completed} clock={clock} overdue={overdue} sourceIds={sourceIds} meetingId={meetingId} eventIds={eventIds}
      editable={editable} loading={loading} stale={stale} busy={busy} morningBlocked={Boolean(morningReference&&!morningReady)} messagesEnabled={messagesEnabled}
      sourceReview={sourceReview} conversation={conversation} edit={edit} onSelect={onSelectTask} onSource={onViewSource} onNavigate={onNavigate} onNew={onNew}
      onDiscard={onDiscard} onCoordinator={()=>{if(!draft.basis)edit("basis",currentBasis);onOpenCoordinatorPicker();}} onDue={()=>{if(!draft.basis)edit("basis",currentBasis);onOpenDuePicker();}}
      onMessages={onViewMessages} onCreate={prepareCreate} onSend={prepareSend} onNudge={prepareNudge} onFollowup={prepareFollowup} onComplete={prepareComplete} onExtend={prepareExtend} onCancel={prepareCancel}/>
    {error&&<div role="alert" className="boss-status boss-status-error"><AlertCircle size={16}/>{error}</div>}
    {notice&&<div role="status" className="boss-status boss-status-ok"><CheckCircle2 size={16}/>{notice}</div>}
    {dialog}{recovery}
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
