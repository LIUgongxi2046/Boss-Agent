import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {
  AlertCircle, ArrowLeft, ArrowRight, CheckCircle2, Clock3,
  ClipboardCheck, FileSearch, FolderOpen, Plus, RefreshCw,
  ShieldCheck, Trash2,
} from "lucide-react";
import { useClient } from "@/providers/ClientProvider";
import { BossMinutesAssignmentActions } from "./BossMinutesAssignmentActions";
import {useTransaction} from "./BossAssignmentFlow";
import type {DraftLeaveRegistration} from "./draft-leave";
import {V7Panel, V7Empty, V7Steps, V7Tabs} from "./BossV7UI";
import {readLibraryContext} from "./library-context";
import "./boss-v6.css";

type Kind = "OPINION" | "SUGGESTION" | "DECISION" | "ASSIGNMENT_DRAFT";
type Entry = { kind: Kind; text: string; source_anchor: string };
type MinutesResponse = {
  source_type: "SIMULATED"; projection: "minutes"; data_version: string;
  meeting: { meeting_id: string; version: string; starts_at: string;
    timezone: string; participant_ids: string[] };
  minute: {
    minute_id: string; meeting_id: string; version: string; state: "DRAFT_REVIEW" | "CONFIRMED";
    source_reference_state?: "CURRENT" | "NEEDS_REVIEW";
    source_id: string; source_version: string; updated_at: string;
    confirmed_at: string | null; entries: (Entry & {entry_id: string})[];
    task_count_created: number; message_count_sent: number;
  } | null;
  source_index: {source_id: string; version: string; withdrawn: boolean}[];
  eligible_assignment_contacts: {
    contact_id:string;name:string;organization:string;responsibility:string;
    allowed_for_fixture_assignment:boolean;
  }[];
  business_clock:string;
  linked_assignments: {
    minute_id: string;minute_version: string;entry_id: string;
    task_id: string;task_status: string;task_version: string;
    send_status: string;sent_message_count: number;
    authorization_id: string;source_id: string;source_version: string;
  }[];
  task_created_by_minutes: boolean;message_sent_by_minutes: boolean;
  revisions: {version: string; state: string; updated_at: string}[];
};
type Approval = {
  application_id: string; title: string; description?: string;
  state: string; version: string; amount: string; currency: string;
  source_id: string; source_version: string;
  applicant_contact_id: string;
  attachment_status: "CURRENT" | "WITHDRAWN" | "MISSING_OR_CHANGED";
  decision_id: string | null; source_type: "SIMULATED";
  missing_items?:string[];
  version_changes?:{field:string;previous:string|null;current:string|null;previous_version:string;current_version:string}[];
};
type Decisions = {
  source_type: "SIMULATED"; projection: "approvals" | "approval-admin";
  applications: Approval[];
  decisions?: {
    decision_id: string; application_id: string; application_version: string;
    action: "APPROVE" | "REJECT" | "REQUEST_MORE";
    amount: string; currency: string; comment: string;
    recorded_at: string; authorization_id: string;
  }[];
  eligible_applicant_contact_ids?: string[];
  data_version: string;
};
type Evidence = {source_id: string; version: string; content: string; source_type: string};

const KIND_LABELS: Record<Kind,string> = {
  OPINION: "讨论意见", SUGGESTION: "建议",
  DECISION: "明确决定", ASSIGNMENT_DRAFT: "交办草稿",
};
const TABS: Kind[] = ["OPINION", "SUGGESTION", "DECISION", "ASSIGNMENT_DRAFT"];
function time(raw: string | null | undefined) {return raw?new Intl.DateTimeFormat("zh-CN",{timeZone:"Asia/Shanghai",dateStyle:"short",timeStyle:"medium"}).format(new Date(raw))+" · Asia/Shanghai":"待核查";}
function approvalSignature(value:Approval){return JSON.stringify([value.application_id,value.version,value.amount,value.currency,value.source_id,value.source_version,value.attachment_status,value.state]);}
function minuteSignature(value:MinutesResponse,source:Evidence){return JSON.stringify([value.meeting.meeting_id,value.meeting.version,value.minute?.version??"0",value.minute?.state,value.minute?.source_reference_state,source.source_id,source.version]);}
function ifText(value: string, max: number, label: string) {
  if (!value.trim() || value.length > max) throw Error(label+"须填写，且最多"+max+"字");
  return value.trim();
}
function Tip({children, warning=false}: {children: ReactNode;warning?:boolean}) {
  return <div className={"boss-status "+(warning?"boss-status-warn":"")}>
    {warning?<AlertCircle size={16}/>:<Clock3 size={16}/>}
    <span>{children}</span>
  </div>;
}
function Panel({title,note,children}:{title:string;note?:string;children:ReactNode}) {
  return <section className="boss-panel">
    <div className="boss-panel-head"><h2>{title}</h2>{note&&<small>{note}</small>}</div>
    {children}
  </section>;
}
function Empty({children}: {children:ReactNode}) {
  return <div className="boss-empty"><FolderOpen size={20}/><div><strong>没有符合当前范围的记录</strong><p>{children}</p></div></div>;
}
function EntryRow({entry}: {entry:Entry}) {
  return <div className="boss-minutes-row">
    <span className="boss-tag boss-tag-blue">{KIND_LABELS[entry.kind]}</span>
    <p>{entry.text||"原文已撤销或版本变化，不能作为当前执行依据"}</p>
    <small>原文位置：{entry.source_anchor||"待重新核查"}</small>
  </div>;
}
function VersionValue({label,value}:{label:string;value?:string|number|null}) {
  return <div className="boss-kv"><span>{label}</span><strong>{value??"未知"}</strong></div>;
}

function useConfirmedMutation(onSuccess:(action?:string)=>void){
  return useTransaction((recorded,action)=>{if(recorded)onSuccess(action);},undefined,undefined,"meetingApproval");
}

type ViewProps={
  pageId:"F05"|"F07";
  onViewSource:(sourceId:string)=>void;
  onNavigate:(pageId:string)=>void;
  onTaskCreated:(taskId:string)=>void;
  onDirtyChange:(dirty:boolean)=>void;
  refreshVersion?:number;
  onDraftLeaveChange?:DraftLeaveRegistration;
};
export function BossMeetingApprovalView(props:ViewProps){
  const {token}=useClient(),identity=useRef({token,sequence:0});
  if(identity.current.token!==token)identity.current={token,sequence:identity.current.sequence+1};
  return <MeetingApprovalView key={props.pageId+identity.current.sequence} {...props}/>;
}
function MeetingApprovalView({pageId,onViewSource,onNavigate,onTaskCreated,onDirtyChange,refreshVersion,onDraftLeaveChange}:ViewProps) {
  const {getToken}=useClient();
  const [data,setData]=useState<MinutesResponse|Decisions|null>(null);
  const [source,setSource]=useState<Evidence|null>(null);
  const [revision,setRevision]=useState(0);
  const [error,setError]=useState("");
  const [loading,setLoading]=useState(true);
  const [dirty,setDirty]=useState(false);
  const [assignmentEdited,setAssignmentEdited]=useState(false);
  const [entries,setEntries]=useState<Entry[]>([]);
  const [kind,setKind]=useState<Kind>("OPINION");
  const [text,setText]=useState("");
  const [anchor,setAnchor]=useState("");
  const [selectedApplication,setSelectedApplication]=useState("");
  const [decision,setDecision]=useState<""|"APPROVE"|"REJECT"|"REQUEST_MORE">("");
  const [comment,setComment]=useState("");
  const [basis,setBasis]=useState("");
  const [nextApplication,setNextApplication]=useState<string|null>(null);
  const [versionFilter,setVersionFilter]=useState(""),[materialFilter,setMaterialFilter]=useState("");
  const edited=dirty||Boolean(text.trim()||anchor||decision||comment.trim());
  const dirtyRef=useRef(edited);dirtyRef.current=edited;
  const reload=()=>setRevision(x=>x+1);
  const savedLeave=useRef<(()=>void)|null>(null);
  const mutation=useConfirmedMutation(action=>{dirtyRef.current=false;setDirty(false);setText("");setAnchor("");setDecision("");setComment("");setBasis("");reload();if(action==="boss.minutes.save"){const finish=savedLeave.current;savedLeave.current=null;finish?.();}});
  useEffect(()=>{if(!mutation.dialog&&!mutation.busy)savedLeave.current=null;},[mutation.dialog,mutation.busy]);
  useEffect(()=>{onDirtyChange(edited||assignmentEdited||mutation.busy||Boolean(mutation.dialog));},[edited,assignmentEdited,mutation.busy,mutation.dialog,onDirtyChange]);
  useEffect(()=>{const prevent=(event:BeforeUnloadEvent)=>{if(dirtyRef.current||mutation.busy){event.preventDefault();event.returnValue="";}};window.addEventListener("beforeunload",prevent);return()=>window.removeEventListener("beforeunload",prevent);},[mutation.busy]);

  useEffect(()=>{
    const abort=new AbortController();
    const token=getToken();
    if(!token){setError("身份已过期，请重新认证");return;}
    const segment=pageId==="F05"?"minutes":"approvals";
    setLoading(true);setError("");setSource(null);setData(null);
    const headers={Authorization:"Bearer "+token};
    void fetch("/api/boss/ui/workspace/"+segment,{
      headers,cache:"no-store",signal:abort.signal,
    }).then(async res=>{
      if(res.status===401)window.dispatchEvent(new Event("boss-auth-expired"));
      if(!res.ok)throw Error("读取会议或审批数据失败，HTTP "+res.status);
      return await res.json() as MinutesResponse|Decisions;
    }).then(async result=>{
      if(abort.signal.aborted)return;
      if(result.source_type!=="SIMULATED"||result.projection!==segment)throw Error("业务投影来源不符");
      setData(result);setLoading(false);
      if(!dirtyRef.current){
        const context=readLibraryContext();
        if(pageId==="F07"&&context?.kind==="approval"){
          const target=(result as Decisions).applications.find(row=>row.application_id===context.id);
          if(target){setSelectedApplication(target.application_id);setBasis(approvalSignature(target));setDecision("");setComment("");}
          else setError("原申请不在当前目录，请重新选择。");
        }
        if(pageId==="F05"&&context?.kind==="meeting"&&context.id!==((result as MinutesResponse).meeting?.meeting_id)){
          setError("原会议不在当前目录，请返回会议资料重新选择。");
        }
      }
      if(pageId==="F05"){
        const minutes=result as MinutesResponse;
        if(!dirtyRef.current){
          setEntries((minutes.minute?.entries??[]).map(row=>({
            kind:row.kind,text:row.text,source_anchor:row.source_anchor,
          })));
        }
        const id=minutes.minute?.source_id || "meeting-minutes";
        const response=await fetch("/api/boss/ui/evidence?source="+encodeURIComponent(id),{
          headers,cache:"no-store",signal:abort.signal,
        });
        if(response.ok){
          const value=await response.json() as Evidence;
          if(!abort.signal.aborted&&value.source_type==="SIMULATED"){setSource(value);if(!dirtyRef.current)setBasis(minuteSignature(minutes,value));}
        }
      }
    }).catch(e=>{
      if(abort.signal.aborted)return;
      setError(e instanceof Error?e.message:String(e));setLoading(false);
    });
    return ()=>abort.abort();
  },[pageId,revision,getToken,refreshVersion]);

  const minutes=pageId==="F05"?data as MinutesResponse|null:null;
  const approvals=pageId==="F07"?data as Decisions|null:null;
  const fragments=useMemo(()=>{
    if(!source?.content)return [];
    return source.content.split(/[。；\n]/g).map(x=>x.trim()).filter(Boolean).map(
      phrase=>phrase.length>80?phrase.slice(0,80):phrase);
  },[source?.content]);
  const app=approvals?.applications.find(x=>x.application_id===selectedApplication);
  const selected=app?.application_id||"";
  const minute=minutes?.minute;
  const stale=Boolean(basis&&(pageId==="F05"?minutes&&source&&basis!==minuteSignature(minutes,source):app&&basis!==approvalSignature(app)));
  const disabled=loading||mutation.busy||!data||!basis||stale;
  useEffect(()=>{if(app&&!dirtyRef.current)setBasis(approvalSignature(app));},[app]);
  function selectApplication(id:string){const selected=approvals?.applications.find(row=>row.application_id===id);setSelectedApplication(id);setDecision("");setComment("");setDirty(false);setBasis(selected?approvalSignature(selected):"");setNextApplication(null);}
  function restoreEditor(){if(pageId==="F05"){setEntries((minute?.entries??[]).map(({kind,text,source_anchor})=>({kind,text,source_anchor})));setText("");setAnchor("");if(minutes&&source)setBasis(minuteSignature(minutes,source));}else{setDecision("");setComment("");if(app)setBasis(approvalSignature(app));}setDirty(false);setError("");}
  const save=()=>{
    if(disabled)return false;
    setError("");
    if(!minutes?.meeting){setError("原始会议尚未载入");return false;}
    if(!source){setError("当前未能读取原始纪要，请先核对资料");return false;}
    if(entries.length<1){setError("先逐条记录并分类意见、建议、决定或交办草稿");return false;}
    if(text.trim()||anchor){setError("当前输入尚未加入分类条目，请完成条目后保存。");return false;}
    return mutation.propose("boss.minutes.save",{
      meeting_id:minutes.meeting.meeting_id,
      meeting_version:minutes.meeting.version,
      source_id:source.source_id,source_version:source.version,
      expected_version:minute?.version||"0",
      entries:entries.map(e=>({...e})),
    },"保存本次会议纪要草稿",[
      "会议："+minutes.meeting.meeting_id+" · 版本 "+minutes.meeting.version,
      "原始材料："+source.source_id+" · 版本 "+source.version,
      "纪要条目："+entries.length+"条；其中明确决定 "+
        entries.filter(e=>e.kind==="DECISION").length+"条",
      "保存草稿不会授权创建任务或发送任何消息。",
    ]);
  };
  useEffect(()=>{
    if(pageId!=="F05"){onDraftLeaveChange?.(null);return;}
    const canSave=edited&&!assignmentEdited&&!disabled&&!mutation.dialog&&entries.length>0&&!text.trim()&&!anchor;
    onDraftLeaveChange?.({object:minutes?.meeting?.meeting_id??"会议纪要",version:minute?.version??"尚未保存",changedFields:[...(dirty?["纪要分类与条目"]:[]),...(text.trim()||anchor?["尚未加入条目的正文与原文位置"]:[]),...(assignmentEdited?["关联交办编辑"]:[])],canSave,unavailableReason:assignmentEdited?"关联交办还有独立编辑，需要返回原表单核查。":text.trim()||anchor?"请将当前输入加入分类条目后保存。":stale?"来源或纪要版本已经变化，请重新核查。":"当前草稿或保存条件尚未就绪。",beginSave:finish=>{if(!canSave)return false;savedLeave.current=finish;const started=save();if(!started)savedLeave.current=null;return started;}});
    return()=>onDraftLeaveChange?.(null);
  });
  const confirmMinutes=()=>{
    if(disabled)return;
    setError("");
    if(!minute||minute.state!=="DRAFT_REVIEW"||!source||source.source_id!==minute.source_id||source.version!==minute.source_version||minute.source_reference_state!=="CURRENT"){
      setError("当前没有可确认的最新纪要草稿或原始材料已失效");return;
    }
    if(edited){setError("还有尚未保存的编辑。请先保存草稿并核对最新版本");return;}
    mutation.propose("boss.minutes.confirm",{
      meeting_id:minute.meeting_id,expected_version:minute.version,
      source_id:minute.source_id,source_version:minute.source_version,
    },"本人确认当前纪要内容与分类",[
      "当前纪要版本："+minute.version,
      "有权原文："+minute.source_id+" v"+minute.source_version,
      "明确决定仅记录为老板认可的纪要内容。",
      "交办草稿不会自动变为任务，也不会自动发出消息。",
    ]);
  };
  const addEntry=()=>{
    setError("");
    try{
      const value=ifText(text,1400,"纪要正文");
      const ref=ifText(anchor,200,"原文位置");
      if(!source?.content.includes(ref))throw Error("选用的原文片段不在当前资料版本中");
      if(entries.length>=30)throw Error("每份纪要最多30条");
      setEntries(prev=>[...prev,{kind,text:value,source_anchor:ref}]);
      setText("");setDirty(true);
    }catch(e){setError(e instanceof Error?e.message:String(e));}
  };
  const submitDecision=()=>{
    if(disabled)return;
    setError("");
    if(!app){setError("当前没有经过维护端录入的模拟审批申请");return;}
    if(!decision){setError("须由本人明确选择同意、拒绝或请求补充");return;}
    if(decision!=="REQUEST_MORE"&&(!app.amount||!app.currency)){setError("金额或币种缺少，请请求补充当前材料。");return;}
    if(decision!=="REQUEST_MORE"&&app.attachment_status!=="CURRENT"){
      setError("申请附件已变化或撤销。不能凭旧版本批准或拒绝，须请求补充");return;
    }
    let approvedComment="";
    try{approvedComment=ifText(comment,1200,"本人意见");}
    catch(e){setError(e instanceof Error?e.message:String(e));return;}
    mutation.propose("boss.approval.decide",{
      application_id:app.application_id,expected_version:app.version,
      source_id:app.source_id,source_version:app.source_version,
      amount:app.amount,currency:app.currency,
      decision,comment:approvedComment,
    },"老板提交当前版本模拟审批决定",[
      "申请："+app.application_id+" · 版本 "+app.version,
      "金额："+app.amount+" "+app.currency,
      "附件："+app.source_id+" · 版本 "+app.source_version,
      "决定："+({APPROVE:"同意",REJECT:"拒绝",REQUEST_MORE:"请求补充"}[decision]),
      "本人意见："+approvedComment,
      "该操作只记录模拟审批决定，不执行资金交易或专业放行。",
    ]);
  };

  return <div className={pageId==="F05"?"boss-minutes-view":"boss-approval-view"}>
    {loading&&<Tip>正在读取获准的原始材料、申请版本与已有决定…</Tip>}
    {error&&<div className="boss-status boss-status-error" role="alert"><AlertCircle size={16}/>{error}</div>}
    {mutation.notice&&<div className="boss-status boss-status-ok" role="status">
      <CheckCircle2 size={16}/>{mutation.notice}</div>}
    {mutation.recovery}
    {stale&&<Tip warning>原对象、金额或资料版本已经变化，当前编辑继续保留。请核查新版本并恢复当前保存内容后重新决定。</Tip>}
    <div className="boss-columns">
      <div className="boss-column">
        {pageId==="F05" ? <>
          <Panel title="会议、资料与版本" note="原会议与原始资料分别核查">
            <VersionValue label="原始会议" value={minutes?.meeting.meeting_id}/>
            <VersionValue label="会议时间" value={minutes?time(minutes.meeting.starts_at):undefined}/>
            <VersionValue label="会议时区" value={minutes?.meeting.timezone}/>
            <VersionValue label="原始资料" value={source?.source_id}/>
            <VersionValue label="原文版本" value={source?.version}/>
            <VersionValue label="当前纪要版本" value={minute?.version}/>
          </Panel>
          <Panel title="会议纪要 · 四类内容" note="意见 / 建议 / 明确决定 / 交办草稿">
            {minutes?<>
              <V7Tabs label="纪要内容分类" value={kind} onChange={setKind} items={TABS.map(k=>({id:k,title:KIND_LABELS[k],count:entries.filter(e=>e.kind===k).length}))}/>
              <fieldset className="boss-minutes-editor" disabled={disabled||!source}>
                <label className="boss-label" htmlFor="boss-minutes-text">{KIND_LABELS[kind]}的具体内容</label>
                <textarea id="boss-minutes-text" rows={3} value={text}
                  onChange={e=>setText(e.target.value)}
                  placeholder="只整理已有事实与本人明确意见。未确认的建议不能当作决定。"/>
                <label className="boss-label" htmlFor="boss-minutes-anchor">对应原文位置</label>
                <select id="boss-minutes-anchor" value={anchor}
                  onChange={e=>setAnchor(e.target.value)} className="boss-single-input">
                  <option value="">选择当前有效原文片段</option>
                  {fragments.map((part,i)=><option key={i} value={part}>{part}</option>)}
                </select>
                <div className="boss-actions">
                  <button className="boss-btn" type="button" onClick={addEntry}
                    disabled={!source||disabled}><Plus size={16}/> 添加本条内容</button>
                </div>
              </fieldset>
              {entries.some(entry=>entry.kind===kind)?entries.map((e,i)=>e.kind===kind&&<div key={i} className="boss-minutes-edit-row">
                <EntryRow entry={e}/>
                <button type="button" aria-label={"移除第"+(i+1)+"条内容"} onClick={()=>{
                  setEntries(old=>old.filter((_,j)=>j!==i));setDirty(true);
                }}><Trash2 size={16}/></button>
              </div>):<Empty>当前分类还没有内容。请依据原文添加并核查。</Empty>}
              <div className="boss-actions">
                <button type="button" className="boss-btn" onClick={save} disabled={!entries.length||disabled}>
                  保存纪要草稿</button>
                <button type="button" className="boss-btn boss-btn-primary" onClick={confirmMinutes}
                  disabled={!minute||minute.state!=="DRAFT_REVIEW"||edited||disabled}>
                  <ShieldCheck size={15}/> 确认已保存的当前版本
                </button>
                <button type="button" className="boss-btn" onClick={reload}>
                  <RefreshCw size={15}/> 重读版本
                </button>
                <button type="button" className="boss-btn" disabled={loading||mutation.busy} onClick={restoreEditor}>恢复保存内容</button>
              </div>
              <Tip warning>确认纪要与发送交办是不同的本人决定。逐项创建只能在纪要已确认、来源仍有效且用户再次明确授权后执行。</Tip>
            </>:!loading&&<Empty>尚无可用会议资料。</Empty>}
          </Panel>
          <BossMinutesAssignmentActions
            minute={minute||null} participants={minutes?.meeting.participant_ids||[]}
            contacts={minutes?.eligible_assignment_contacts||[]}
            businessClock={minutes?.business_clock||""}
            links={minutes?.linked_assignments||[]}
            sourceCurrent={Boolean(source&&minute&&source.source_id===minute.source_id&&source.version===minute.source_version)}
            editingUnsaved={edited||stale} onReload={reload}
            onTaskCreated={onTaskCreated} onNavigate={onNavigate}
            onDirtyChange={setAssignmentEdited}
          />
        </>:<>
          <Panel title="内容与配置" note="申请对象、金额、币种及附件版本">
            <div className="boss-form-grid"><label>当前版本<input value={versionFilter} onChange={event=>setVersionFilter(event.target.value)}/></label><label>材料状态<select value={materialFilter} onChange={event=>setMaterialFilter(event.target.value)}><option value="">全部材料状态</option><option value="CURRENT">当前有效</option><option value="WITHDRAWN">已撤销</option><option value="MISSING_OR_CHANGED">缺少或已经变化</option></select></label></div>
            {approvals?.applications.length?<>
              <label className="boss-label" htmlFor="boss-application-select">选择申请</label>
              <select className="boss-single-input" id="boss-application-select"
                value={selected} onChange={e=>{if(edited)setNextApplication(e.target.value);else selectApplication(e.target.value);}}>
                <option value="">请选择当前申请</option>
                {approvals.applications.filter(a=>a.application_id===selected||(!versionFilter||a.version===versionFilter)&&(!materialFilter||a.attachment_status===materialFilter)).map(a=><option value={a.application_id} key={a.application_id}>
                  {a.title} · {a.application_id}
                </option>)}
              </select>
              {app&&<>
                <VersionValue label="申请 ID" value={app.application_id}/>
                <VersionValue label="申请版本" value={app.version}/>
                <VersionValue label="金额与币种" value={(app.amount??"未知金额")+" "+(app.currency??"未知币种")}/>
                <VersionValue label="当前状态" value={app.state}/>
                <VersionValue label="附件状态" value={app.attachment_status}/>
                <h3>编辑内容与说明</h3>
                <div className="boss-approval-description">{app.description||"摘要尚未提供"}</div>
                <h3>前后版本差异</h3>
                {app.version_changes?.length?<div className="boss-v7-table-scroll"><table className="boss-v7-table"><thead><tr><th>字段</th><th>原版本</th><th>当前版本</th></tr></thead><tbody>{app.version_changes.map(row=><tr key={row.field}><td>{row.field}</td><td>{row.previous??"尚未提供"}<small>v{row.previous_version}</small></td><td>{row.current??"尚未提供"}<small>v{row.current_version}</small></td></tr>)}</tbody></table></div>:<V7Empty title={app.version_changes?"当前没有已记录的版本差异":"服务尚未提供逐项版本差异"}/>}
                <div className="boss-actions">
                  <button type="button" className="boss-btn" onClick={()=>onViewSource(app.source_id)}
                    disabled={app.attachment_status!=="CURRENT"}>
                    <FileSearch size={16}/> 打开附件原文 v{app.source_version}
                  </button>
                </div>
                <div className="boss-approval-decisions" role="group" aria-label="本人决定">
                  {([
                    ["APPROVE","同意"],["REJECT","拒绝"],["REQUEST_MORE","请求补充"],
                  ] as const).map(([value,label])=><label key={value}
                    className={decision===value?"selected":""}>
                    <input type="radio" name="boss-approval-action" value={value}
                      checked={decision===value}
                      disabled={disabled||!["PENDING_DECISION","WAITING_MATERIAL"].includes(app.state) ||
                        (value!=="REQUEST_MORE"&&app.attachment_status!=="CURRENT")}
                      onChange={()=>setDecision(value)}/>
                    <span>{label}</span>
                  </label>)}
                </div>
                <label className="boss-label" htmlFor="boss-approval-comment">本人意见（必填）</label>
                <textarea rows={3} id="boss-approval-comment" value={comment}
                  onChange={e=>setComment(e.target.value)}
                  placeholder="说明对当前版本申请的批准范围、拒绝原因或必须补充的材料。"/>
              </>}
            </>:!loading&&<Empty>尚未录入获准的模拟审批申请。</Empty>}
            <Tip warning>本界面只保存申请版本对应的模拟审批记录。没有资金交易、专业放行或真实外部消息发送。</Tip>
          </Panel>
          <Panel title="关联内容与处理边界" note="当前申请的本人决定与原版本">
            {(approvals?.decisions||[]).some(x=>x.application_id===selected)?(approvals?.decisions||[]).filter(x=>x.application_id===selected).map(x=><div
              className="boss-minutes-row" key={x.decision_id}>
              <span className="boss-tag boss-tag-green">{x.action}</span>
              <p>{x.comment}</p>
              <small>申请：{x.application_id} · v{x.application_version} ·
                金额：{x.amount} {x.currency} · {time(x.recorded_at)}</small>
            </div>):<Empty>当前没有已保存的老板审批决定。</Empty>}
          </Panel>
        </>}
      </div>
      <div className="boss-column">
        {pageId==="F05" ? <>
          <Panel title="当前纪要版本与操作结果" note="证据有效性与正式记录分别读取">
            <VersionValue label="原始会议" value={minutes?.meeting.meeting_id}/>
            <VersionValue label="原文版本" value={source?.version}/>
            <VersionValue label="已保存纪要版本" value={minute?.version}/>
            <VersionValue label="已确认时间" value={time(minute?.confirmed_at)}/>
            {source?.content?<details><summary>阅读当前原文</summary><blockquote className="boss-source">{source.content}</blockquote></details>
              :<Tip warning>资料已撤销、未获取或当前身份无权读取，不能确认纪要。</Tip>}
            {source&&<div className="boss-actions"><button className="boss-btn" type="button"
              onClick={()=>onViewSource(source.source_id)}>查看完整原文 <ArrowRight size={15}/></button></div>}
            {(minutes?.revisions||[]).length>0&&<div className="boss-minutes-history">
              <h3>历史纪要版本</h3>
              {minutes?.revisions.map(x=><p key={x.version}>v{x.version} · {x.state} · {time(x.updated_at)}</p>)}
            </div>}
          </Panel>
          <Panel title="关联">
            <VersionValue label="人工逐项创建的任务" value={minutes?.linked_assignments.length}/>
            <VersionValue label="已经模拟发送的关联交办" value={
              minutes?.linked_assignments.filter(x=>x.send_status==="SENT_SIMULATED").length}/>
            <VersionValue label="是否自动创建交办" value="否"/>
            <VersionValue label="是否自动发送" value="否"/>
            <div className="boss-actions">
              <button className="boss-btn boss-btn-primary" type="button"
                onClick={()=>onNavigate("F06")}><ClipboardCheck size={15}/> 进入 F06 交办详情</button>
            </div>
          </Panel>
        </>:<>
          <Panel title="来源与依据" note="仅当前申请版本">
            <VersionValue label="申请状态" value={app?.state}/>
            <VersionValue label="附件 ID" value={app?.source_id}/>
            <VersionValue label="附件版本" value={app?.source_version}/>
            <VersionValue label="材料完整性" value={app?.attachment_status}/>
            <VersionValue label="授权动作" value={decision||"尚未选择"}/>
            <h3>资料缺口</h3>{app?.missing_items?.length?<ul>{app.missing_items.map(value=><li key={value}>{value}</li>)}</ul>:<p>{app?.missing_items?"当前没有已记录的缺少项":"服务尚未提供完整材料缺口清单"}</p>}
            <VersionValue label="真实资金交易" value="未执行"/>
            <Tip warning>没有真实交易系统连接。发生附件撤销、申请版本变更、金额或币种变化时，原选择不能继续使用。</Tip>
          </Panel>
          <Panel title="状态与核查">
            <VersionValue label="当前申请" value={app?.application_id}/>
            <VersionValue label="当前版本" value={app?.version}/>
            <VersionValue label="原决定" value={app?.decision_id}/>
            <VersionValue label="版本核查" value={stale?"原编辑版本已经变化":app?"当前读取版本":"尚未选择"}/>
            <div className="boss-actions">
              <button className="boss-btn" type="button" onClick={()=>onNavigate("N04")}>
                <ArrowLeft size={15}/> 会议与资料
              </button>
              <button className="boss-btn" type="button" onClick={()=>onNavigate("N10")}>
                本人授权记录
              </button>
            </div>
          </Panel>
        </>}
      </div>
    </div>
    {pageId==="F05"&&<div className="boss-v7-addendum">
      <V7Panel title="逐项创建、发送及补充核查" description="每条交办分别关联纪要版本、任务和本人授权。">
        {minute?.entries.some(entry=>entry.kind==="ASSIGNMENT_DRAFT")?<div className="boss-v7-table-scroll"><table className="boss-v7-table"><thead><tr><th>纪要条目</th><th>来源版本</th><th>创建任务</th><th>发送状态</th><th>授权引用</th></tr></thead><tbody>{minute.entries.filter(entry=>entry.kind==="ASSIGNMENT_DRAFT").map(entry=>{
          const linked=minutes?.linked_assignments.find(item=>item.entry_id===entry.entry_id&&item.minute_version===minute.version);
          return <tr key={entry.entry_id}><td>{entry.text||"来源需要复核"}<small>{entry.entry_id}</small></td><td>v{minute.source_version}<small>{minute.source_reference_state}</small></td><td>{linked?<button className="boss-btn" onClick={()=>{onTaskCreated(linked.task_id);onNavigate("F06");}}>{linked.task_id}</button>:"尚未创建"}</td><td>{linked?.send_status==="SENT_SIMULATED"?"已模拟发送":"尚未发送"}</td><td>{linked?.authorization_id||"尚无当前动作授权"}</td></tr>;
        })}</tbody></table></div>:<V7Empty title="尚无交办草稿">在交办草稿分类中整理具体事项，确认纪要后逐项创建。</V7Empty>}
      </V7Panel>
      <div className="boss-v7-equal-columns">
      <V7Panel title="交办草稿检查">
        <V7Steps steps={[
          {title:"原文有效",description:source?"已读取原文 v"+source.version:"等待可用原文",state:source?"complete":"waiting"},
          {title:"分类内容",description:minutes?entries.length+" 条内容 · "+(edited?"存在未保存编辑":"当前保存内容"):"尚未读取分类内容",state:entries.length?(edited?"current":"complete"):"waiting"},
          {title:"本人确认",description:minute?.state==="CONFIRMED"?"纪要 v"+minute.version+" 已确认":"等待核查当前保存版本",state:minute?.state==="CONFIRMED"?"complete":"waiting"},
          {title:"任务关联",description:minutes?minutes.linked_assignments.length+" 个任务已经关联":"尚未读取任务关联",state:minutes?.linked_assignments.length?"complete":"waiting"},
        ]}/>
      </V7Panel>
      <V7Panel title="与当前事项联动"><div className="boss-actions"><button className="boss-btn" onClick={()=>onNavigate("N04")}>会议与资料</button><button className="boss-btn" onClick={()=>onNavigate("N05")}>任务与承诺</button><button className="boss-btn" onClick={()=>onNavigate("N11")}>历史决定</button></div></V7Panel>
      </div>
    </div>}
    {pageId==="F07"&&<footer className="boss-owner-actions"><button type="button" className="boss-btn boss-btn-primary" onClick={submitDecision} disabled={disabled||!app||!decision||!comment.trim()||!["PENDING_DECISION","WAITING_MATERIAL"].includes(app.state)}><ShieldCheck size={15}/>提交当前版本决定</button><button type="button" className="boss-btn" onClick={restoreEditor} disabled={loading||mutation.busy}>取消未执行操作</button><button type="button" className="boss-btn" onClick={reload} disabled={loading||mutation.busy}><RefreshCw size={15}/>重读正式状态</button></footer>}
    {mutation.dialog}
    <Dialog.Root open={nextApplication!==null} onOpenChange={open=>{if(!open)setNextApplication(null);}}><Dialog.Portal><Dialog.Overlay className="boss-v7-dialog-overlay"/><Dialog.Content className="boss-v7-dialog"><Dialog.Title>当前申请存在未提交意见</Dialog.Title><Dialog.Description>切换申请前可以继续编辑，或者放弃当前尚未提交的意见。已经保存的本人决定继续保留。</Dialog.Description><div className="boss-actions"><Dialog.Close asChild><button className="boss-btn">继续编辑</button></Dialog.Close><button className="boss-btn" disabled={mutation.busy} onClick={()=>{if(nextApplication!==null)selectApplication(nextApplication);}}>放弃编辑并切换申请</button></div></Dialog.Content></Dialog.Portal></Dialog.Root>
  </div>;
}

export function MaintainerApplicationSeed() {
  const {getToken}=useClient();
  const [data,setData]=useState<Decisions|null>(null);
  const [revision,setRevision]=useState(0);
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState("");
  const [applicant,setApplicant]=useState("");
  const [amount,setAmount]=useState("");
  const [title,setTitle]=useState("");
  const [description,setDescription]=useState("");
  const [attachment,setAttachment]=useState("");
  const mutation=useConfirmedMutation(()=>setRevision(x=>x+1));
  useEffect(()=>{
    const abort=new AbortController();const token=getToken();
    if(!token){setError("技术身份尚未认证");return;}
    setLoading(true);setError("");
    void fetch("/api/boss/ui/workspace/approval-admin",{
      headers:{Authorization:"Bearer "+token},signal:abort.signal,cache:"no-store",
    }).then(async res=>{
      if(!res.ok)throw Error("技术身份无权读取模拟申请目录（HTTP "+res.status+"）");
      return await res.json() as Decisions;
    }).then(data=>{
      if(abort.signal.aborted)return;
      if(data.projection!=="approval-admin"||data.source_type!=="SIMULATED")
        throw Error("模拟资料来源不符");
      setData(data);setLoading(false);
      const existing=data.applications.find(x=>x.application_id==="application-1");
      if(existing?.state==="WAITING_MATERIAL"){
        setApplicant(existing.applicant_contact_id);
        setAmount(existing.amount);
        setTitle(existing.title);
      }
    }).catch(e=>{
      if(abort.signal.aborted)return;
      setError(e instanceof Error?e.message:String(e));setLoading(false);
    });
    return ()=>abort.abort();
  },[revision,getToken]);
  const seed=()=>{
    setError("");
    const current=(data?.applications||[]).find(x=>x.application_id==="application-1");
    const revising=current?.state==="WAITING_MATERIAL";
    if(current&&!revising){
      setError("申请已经存在。只有老板明确请求补充后，维护端才能更新这个模拟版本。");return;
    }
    if(!data?.eligible_applicant_contact_ids?.includes(applicant)){
      setError("请选择获准模拟内部申请联系人");return;
    }
    if(!/^\d{1,12}(\.\d{1,2})?$/.test(amount)||Number(amount)<=0){
      setError("申请金额必须为正的 CNY 数值，最多两位小数");return;
    }
    try{
      const t=ifText(title,100,"标题");
      const d=ifText(description,1500,"申请说明");
      const a=ifText(attachment,2500,"模拟附件");
      if(a.length<12)throw Error("附件至少需要12个字的模拟资料内容");
      mutation.propose(revising?"boss.simulation.application.revise":"boss.simulation.application.seed",{
        application_id:"application-1",
        ...(revising?{expected_version:current?.version}:{}),
        applicant_contact_id:applicant,
        amount_cny:amount,title:t,description:d,attachment_text:a,
      },revising?"确认补充申请材料并递增版本":"确认录入模拟审批申请",[
        "申请 ID：application-1",
        ...(revising?["上一申请版本："+current?.version+"（仅在WAITING_MATERIAL状态下更新）"]:[]),
        "模拟申请人标识："+applicant,
        "金额："+amount+" CNY（不是实付或待交易资金）",
        "标题："+t,"说明："+d,"附件内容："+a,
        "此动作只由维护者录入模拟资料，不替老板批准。",
      ]);
    }catch(e){setError(e instanceof Error?e.message:String(e));}
  };
  return <>
    <Panel title="模拟审批申请数据" note="A03 · 维护录入，不授予老板权限">
      <Tip>只有明确录入了模拟申请，老板的 F07 才会出现真实申请对象。金额、币种和附件均不从其他经营记录猜测。</Tip>
      {(data?.applications||[]).map(app=><div className="boss-minutes-row" key={app.application_id}>
        <span className="boss-tag boss-tag-blue">{app.state}</span>
        <p>{app.title}</p><small>{app.application_id} · v{app.version} · {app.amount} {app.currency}</small>
        <small>附件：{app.source_id} v{app.source_version} · {app.attachment_status}</small>
      </div>)}
      {!data?.applications?.length&&!loading&&<Empty>当前没有模拟申请。</Empty>}
      {(!data?.applications?.length||data.applications.some(x=>x.state==="WAITING_MATERIAL"))&&<>
        {data?.applications?.some(x=>x.state==="WAITING_MATERIAL")&&<Tip warning>老板已请求补充材料。只能依照当前申请版本录入新说明、金额及附件；旧申请和原始附件会保留历史版本。</Tip>}
        <div className="boss-form-grid">
          <label>模拟申请人<select value={applicant} onChange={e=>setApplicant(e.target.value)}>
            <option value="">请选择内部合成联系人</option>
            {(data?.eligible_applicant_contact_ids||[]).map(id=><option key={id} value={id}>{id}</option>)}
          </select></label>
          <label>申请金额（CNY）<input value={amount} onChange={e=>setAmount(e.target.value)}
            inputMode="decimal" placeholder="例如：3000.00"/></label>
          <label>申请标题<input value={title} onChange={e=>setTitle(e.target.value)} placeholder="模拟申请的具体标题"/></label>
        </div>
        <label className="boss-label">申请说明</label>
        <textarea aria-label="申请说明" rows={3} value={description} onChange={e=>setDescription(e.target.value)}/>
        <label className="boss-label">模拟申请附件内容（12—2500 字）</label>
        <textarea aria-label="模拟申请附件内容" rows={4} value={attachment} onChange={e=>setAttachment(e.target.value)}
          placeholder="必须写入获准的模拟资料。此正文只供老板端按权限查看。"/>
        <div className="boss-actions">
          <button type="button" className="boss-btn boss-btn-primary" onClick={seed}
            disabled={!data||mutation.busy}><ShieldCheck size={15}/> {data?.applications?.some(x=>x.state==="WAITING_MATERIAL")?"核对并补充当前申请材料":"审阅并录入模拟申请"}</button>
        </div>
      </>}
      <div className="boss-actions"><button className="boss-btn" type="button"
        onClick={()=>setRevision(x=>x+1)}><RefreshCw size={15}/> 重读数据集</button></div>
      {error&&<div role="alert" className="boss-status boss-status-error"><AlertCircle size={16}/>{error}</div>}
      {mutation.notice&&<div role="status" className="boss-status boss-status-ok">{mutation.notice}</div>}
    </Panel>
    {mutation.dialog}
    {mutation.recovery}
  </>;
}
