import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle, ArrowRight, CheckCircle2, Clock3, ClipboardCheck,
  Loader2, MessageSquareText, RefreshCw, ShieldCheck, XCircle,
} from "lucide-react";
import { useClient } from "@/providers/ClientProvider";
import type { AssignmentDraft } from "./BossAssignmentPicker";

export interface AssignmentTask {
  task_id: string; status: string; version?: string; purpose?: string;
  coordinator_id?: string; due_at?: string; timezone?: string;
  feedback_ids?: string[]; message_ids?: string[];
  source_refs?: string[]; evidence_requirements?: string[];
}
export interface TaskFeedback {
  feedback_id: string; task_id: string;
  kind: "PROGRESS" | "EXTENSION_REQUEST" | "RESULT_SUBMITTED";
  author_contact_id?: string; content?: string; evidence_refs?: string[];
  proposed_due_at?: string; submitted_at?: string;
}
export interface TaskListResponse {
  tasks: AssignmentTask[];
  feedback?: TaskFeedback[];
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
  | "boss.assignment.cancel" | "boss.simulation.feedback";
type Result = {
  task_id?: string; task?: { task_id: string; status: string; version: string };
  status?: string; version?: string; feedback_id?: string;
};
type Pending = {
  action: Action; payload: Record<string, unknown>;
  id: string; title: string; preview: string[];
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

function useTransaction(onReload: () => void, onCreated?: (id: string) => void) {
  const { client, getToken } = useClient();
  const [lookupBusy,setLookupBusy] = useState(false);
  const dialogRef = useRef<HTMLElement | null>(null);
  const busyRef = useRef(false);
  const [pending, setPending] = useState<Pending | null>(null);
  const [approved, setApproved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  busyRef.current = busy;
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
    setPending({ action, payload, id: "boss-" + crypto.randomUUID(), title, preview });
    setApproved(false); setError(""); setNotice("");
  }, []);
  const submit = useCallback(async () => {
    if (!pending || !approved || busy) return;
    setBusy(true); setError("");
    try {
      const result = await client.requestMutation<Result>(
        pending.action, { ...pending.payload, client_request_id: pending.id },
      );
      if (pending.action === "boss.assignment.create" && result.task_id) onCreated?.(result.task_id);
      setNotice("实际模拟业务已保存。状态：" + (result.status || result.task?.status || "已记录") +
        "；交办：" + (result.task_id || result.task?.task_id || "未知") + "。请重读当前状态。");
      setPending(null); setApproved(false); onReload();
    } catch (e) {
      // Keep the *same* idempotency key if network interruption leaves the
      // outcome unknown, never silently issue an alternative write.
      setError((e instanceof Error ? e.message : String(e)) +
        "。结果可能待核查，请先重读正式状态；本弹窗重试使用同一幂等标识。");
    } finally { setBusy(false); }
  }, [approved, busy, client, onCreated, onReload, pending]);
  const reconcile = useCallback(async () => {
    if (!pending || busy || lookupBusy) return;
    const token = getToken();
    if (!token) { setError("当前身份已失效，无法核查业务回执"); return; }
    setLookupBusy(true);setError("");
    try {
      const qs = new URLSearchParams({
        action: pending.action, client_request_id: pending.id,
      });
      const res = await fetch("/api/boss/ui/operation-status?" + qs.toString(), {
        headers: {Authorization:"Bearer "+token}, cache:"no-store",
      });
      if (!res.ok) throw new Error("幂等回执查询失败（HTTP " + res.status + "）");
      const body = await res.json() as {
        action:string;client_request_id:string;outcome:string;result?:Result;
      };
      if(body.action!==pending.action||body.client_request_id!==pending.id)
        throw new Error("操作回执身份与本次动作不匹配");
      if(body.outcome==="RECORDED"&&body.result){
        if(pending.action==="boss.assignment.create"&&body.result.task_id)
          onCreated?.(body.result.task_id);
        setNotice("已从实际 SQLite 幂等回执核实该交办动作已保存，任务状态正在重读。");
        setPending(null);setApproved(false);onReload();
      }else if(body.outcome==="NOT_FOUND_IN_CURRENT_STORE"){
        setError("当前没有该请求回执，但不能据此推定未执行。请先重读交办正式状态，再使用原请求编号重试。");
        onReload();
      }else throw new Error("服务端回执格式无效，不能假定已执行");
    } catch(e) {
      setError(e instanceof Error?e.message:String(e));
    }finally{setLookupBusy(false);}
  },[pending,busy,lookupBusy,getToken,onCreated,onReload]);
  const dialog = pending ? <div className="boss-confirm-backdrop">
    <section ref={dialogRef} tabIndex={-1} className="boss-confirm" role="dialog" aria-modal="true" aria-labelledby="boss-confirm-title">
      <h3 id="boss-confirm-title"><ShieldCheck size={19}/> {pending.title}</h3>
      <p>仅当前已认证身份能发起此项模拟业务操作。下面的字段将与授权、对象版本及唯一请求编号一同保存。</p>
      <dl>{pending.preview.map((line, index) => <div key={index}><dd>{line}</dd></div>)}</dl>
      <label className="boss-confirm-check">
        <input type="checkbox" checked={approved} disabled={busy} onChange={e=>setApproved(e.target.checked)}/>
        <span>本人确认以上具体对象、内容、期限和动作。</span>
      </label>
      {error && <p role="alert" className="boss-validation-error">{error}</p>}
      <footer className="boss-actions">
        <button type="button" className="boss-btn" disabled={busy||lookupBusy}
          onClick={() => {setPending(null);setApproved(false);}}>取消（不执行）</button>
        <button type="button" className="boss-btn" disabled={busy||lookupBusy}
          onClick={() => void reconcile()}>
          {lookupBusy && <Loader2 size={15} className="boss-spin"/>} 核查原请求结果</button>
        <button type="button" className="boss-btn boss-btn-primary" disabled={!approved||busy||lookupBusy}
          onClick={() => void submit()}>{busy && <Loader2 size={15} className="boss-spin"/>} 确认并提交</button>
      </footer>
    </section>
  </div> : null;
  return { propose, dialog, notice, busy };
}

export function BossAssignmentFlow({ tasks, selectedTaskId, onSelectTask, onReload, onViewSource, context,
  draft, onDraftChange, onDraftSaved, onOpenCoordinatorPicker, onOpenDuePicker }: {
  tasks: TaskListResponse | null; selectedTaskId: string;
  onSelectTask: (id: string) => void; onReload: () => void;
  onViewSource: () => void; context: AssignmentContext | null;
  draft: AssignmentDraft;
  onDraftChange: (key: keyof AssignmentDraft, value: string) => void;
  onDraftSaved: () => void;
  onOpenCoordinatorPicker: () => void; onOpenDuePicker: () => void;
}) {
  const { propose, dialog, notice, busy } = useTransaction(onReload, id => {
    onSelectTask(id); onDraftSaved();
  });
  const {purpose,coordinator,due,evidence,body,newDue,reason}=draft;
  const [error,setError]=useState("");
  const rows=tasks?.tasks||[];
  const current=rows.find(t=>t.task_id===selectedTaskId)||rows[0];
  const feedback=useMemo(()=>(tasks?.feedback||[]).filter(f=>current&&f.task_id===current.task_id),[current,tasks]);
  const completed=feedback.find(f=>f.kind==="RESULT_SUBMITTED"&&Boolean(f.evidence_refs?.length));
  const extension=[...feedback].reverse().find(f=>f.kind==="EXTENSION_REQUEST");
  const safe=(fn:()=>void)=>{setError("");try{fn()}catch(e){setError(e instanceof Error?e.message:String(e))}};
  const prepareCreate=()=>safe(()=>{
    if(!context?.meeting?.meeting_id||!context.event?.event_id||
      !context.assignment_source_ids?.includes("finance-note"))
      throw new Error("未取得关联会议、事件或有效资料，拒绝创建。");
    const purposeText=required(purpose,"交办目的"),proof=required(evidence,"证据要求");
    if(!coordinator||!context.contacts.some(c=>c.contact_id===coordinator))
      throw new Error("请选择获准的唯一负责人");
    const dueAt=shanghai(due);
    propose("boss.assignment.create",{
      purpose:purposeText,coordinator_id:coordinator,due_at:dueAt,
      timezone:"Asia/Shanghai",evidence_requirements:[proof],
      related_meeting_id:context.meeting.meeting_id,
      related_event_ids:[context.event.event_id],
      source_refs:["finance-note"],content_version:"1",
    },"核对并创建交办",[
      "目的："+purposeText,"负责人："+coordinator,"期限："+dueAt,
      "证据："+proof,"会议："+context.meeting.meeting_id,
      "关联事件："+context.event.event_id,"资料来源：finance-note",
    ]);
  });
  const prepareSend=()=>safe(()=>{
    if(!current||current.status!=="OPEN"||!current.version||!current.coordinator_id)
      throw new Error("仅 OPEN 且版本有效的交办可以发送。");
    const message=required(body,"模拟消息正文");
    propose("boss.assignment.send",{
      task_id:current.task_id,task_version:current.version,
      recipient_id:current.coordinator_id,body:message,content_version:"1",
    },"模拟发送前确认",[
      "交办："+current.task_id,"唯一收件人："+current.coordinator_id,
      "正文："+message,"仅写入模拟发件箱，不会真正发送至外部人员。",
    ]);
  });
  const prepareComplete=()=>safe(()=>{
    if(!current||!completed||current.status!=="RESULT_SUBMITTED"||!current.version)
      throw new Error("当前没有已经提交且具备证据的核查结果。");
    propose("boss.assignment.complete",{
      task_id:current.task_id,task_version:current.version,feedback_id:completed.feedback_id,
    },"老板确认完成",[
      "交办："+current.task_id,"结果提交："+completed.feedback_id,
      "证据："+(completed.evidence_refs||[]).join("、"),
      "仅在本人确认后更新为 COMPLETED_CONFIRMED。",
    ]);
  });
  const prepareExtend=()=>safe(()=>{
    if(!current||!extension||!current.version)throw new Error("未取得有效延期申请。");
    const date=shanghai(newDue);
    propose("boss.assignment.extend",{
      task_id:current.task_id,task_version:current.version,
      feedback_id:extension.feedback_id,due_at:date,
    },"老板批准延期",[
      "原期限："+displayTime(current.due_at),
      "延期依据："+extension.feedback_id,"新期限："+date,
      "未批准前旧期限持续有效。",
    ]);
  });
  const prepareCancel=()=>safe(()=>{
    if(!current||!current.version)throw new Error("请选择有效任务。");
    const why=required(reason,"取消原因");
    propose("boss.assignment.cancel",{
      task_id:current.task_id,task_version:current.version,reason:why,
    },"老板确认取消交办",[
      "交办："+current.task_id,"原因："+why,
      "先前已发送的模拟消息和历史反馈不会撤销。",
    ]);
  });
  return <>
    <div className="boss-columns">
      <div className="boss-column">
        <section className="boss-panel">
          <div className="boss-panel-head"><h2>创建交办</h2><small>F06 · 当前老板授权</small></div>
          <div className="boss-form-grid">
            <label>唯一负责人<select value={coordinator} onChange={e=>onDraftChange("coordinator",e.target.value)}>
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
          <label className="boss-label">交办目的</label>
          <textarea rows={3} value={purpose} onChange={e=>onDraftChange("purpose",e.target.value)}
            placeholder="说明目的、范围、要求与应交付的产物"/>
          <label className="boss-label">证据要求</label>
          <input className="boss-single-input" value={evidence} onChange={e=>onDraftChange("evidence",e.target.value)}/>
          <p className="boss-helper">会议：{context?.meeting?.meeting_id||"待读取"} ·
            关联事件：{context?.event?.event_id||"待读取"} · 资料：{context?.assignment_source_ids?.join("、")||"待读取"}</p>
          <div className="boss-actions">
            <button className="boss-btn boss-btn-primary" type="button" onClick={prepareCreate} disabled={busy}>
              <ShieldCheck size={15}/> 核对并创建</button>
            <button className="boss-btn" type="button" onClick={onViewSource}>查看来源</button>
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
        <section className="boss-panel">
          <div className="boss-panel-head"><h2>交办详情与模拟发送</h2><small>有效授权 · 当前对象版本</small></div>
          {current ? <>
            <div className="boss-kv"><span>任务 ID</span><strong>{current.task_id}</strong></div>
            <div className="boss-kv"><span>正式状态</span><strong>{current.status}</strong></div>
            <div className="boss-kv"><span>截止时间</span><strong>{displayTime(current.due_at)}</strong></div>
            <div className="boss-kv"><span>证据要求</span><strong>{current.evidence_requirements?.join("、")||"缺少"}</strong></div>
            <label className="boss-label">模拟发件内容</label>
            <textarea rows={3} value={body} onChange={e=>onDraftChange("body",e.target.value)} placeholder="输入准备发给唯一负责人的正文"/>
            <div className="boss-actions"><button className="boss-btn boss-btn-primary" type="button"
              disabled={current.status!=="OPEN"||busy} onClick={prepareSend}>
              <MessageSquareText size={15}/> 核对并模拟发送</button></div>
          </>:<p className="boss-helper">请先选择或创建交办。</p>}
          <p className="boss-helper">模拟 SENT 只代表本地发件箱已记录；任务仍需反馈。</p>
        </section>
        <section className="boss-panel">
          <div className="boss-panel-head"><h2>反馈与本人决定</h2><small>进展、结果提交、确认完成分别记录</small></div>
          {feedback.length ? feedback.map(f=><div className="boss-feedback" key={f.feedback_id}>
            <div><span className="boss-tag boss-tag-amber">{f.kind}</span><small>{displayTime(f.submitted_at)}</small></div>
            <p>{f.content||"未提供正文"}</p>
            <small>作者：{f.author_contact_id||"待核查"} · 证据：{f.evidence_refs?.join("、")||"无"}</small>
            {f.proposed_due_at && <small>申请新期限：{displayTime(f.proposed_due_at)}</small>}
          </div>):<p className="boss-helper">暂无署名反馈。不能提前认定完成。</p>}
          <div className="boss-actions">
            <button className="boss-btn boss-btn-primary" type="button"
              disabled={!current||current.status!=="RESULT_SUBMITTED"||!completed||busy} onClick={prepareComplete}>
              <CheckCircle2 size={15}/> 核查证据并确认完成</button>
          </div>
          <div className="boss-form-grid boss-form-below">
            <label>新期限（北京时间）<input type="datetime-local" value={newDue} onChange={e=>onDraftChange("newDue",e.target.value)}/></label>
          </div>
          <div className="boss-actions"><button type="button" className="boss-btn" disabled={!extension||busy}
            onClick={prepareExtend}><Clock3 size={15}/> 审阅延期申请</button></div>
          <label className="boss-label">取消原因</label>
          <input className="boss-single-input" value={reason} onChange={e=>onDraftChange("reason",e.target.value)} placeholder="说明本次取消的原因"/>
          <div className="boss-actions"><button type="button" className="boss-btn" onClick={prepareCancel}
            disabled={!current||busy||["CANCELED","COMPLETED_CONFIRMED"].includes(current.status)}>
            <XCircle size={15}/> 核对并取消交办</button></div>
        </section>
        {error && <div role="alert" className="boss-status boss-status-error"><AlertCircle size={16}/>{error}</div>}
        {notice && <div role="status" className="boss-status boss-status-ok"><CheckCircle2 size={16}/>{notice}</div>}
      </div>
    </div>
    {dialog}
  </>;
}

export function MaintainerFeedback({tasks,onReload}:{
  tasks:MaintenanceTaskRef[];onReload:()=>void;
}) {
  const {propose,dialog,notice}=useTransaction(onReload);
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
    <section className="boss-panel">
      <div className="boss-panel-head"><h2>模拟负责人反馈</h2><small>A04 · MAINTAINER 权限</small></div>
      <div className="boss-form-grid">
        <label>任务技术标识<select value={selected} onChange={e=>setSelected(e.target.value)}>
          <option value="">请选择待反馈交办</option>
          {tasks.filter(t=>!["CANCELED","COMPLETED_CONFIRMED"].includes(t.status)).map(t=>
            <option key={t.task_id} value={t.task_id}>{t.task_id} · {t.status} · v{t.version}</option>)}
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
    </section>
    {dialog}
  </>;
}
