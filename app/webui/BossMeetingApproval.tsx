import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  AlertCircle, ArrowLeft, ArrowRight, CheckCircle2, Clock3,
  ClipboardCheck, FileSearch, FolderOpen, Loader2, Plus, RefreshCw,
  ShieldCheck, Trash2,
} from "lucide-react";
import { useClient } from "@/providers/ClientProvider";
import { BossMinutesAssignmentActions } from "./BossMinutesAssignmentActions";
import "./boss-v6.css";

type Kind = "OPINION" | "SUGGESTION" | "DECISION" | "ASSIGNMENT_DRAFT";
type Entry = { kind: Kind; text: string; source_anchor: string };
type MinutesResponse = {
  source_type: "SIMULATED"; projection: "minutes"; data_version: string;
  meeting: { meeting_id: string; version: string; starts_at: string;
    timezone: string; participant_ids: string[] };
  minute: {
    minute_id: string; meeting_id: string; version: string; state: "DRAFT_REVIEW" | "CONFIRMED";
    source_id: string; source_version: string; updated_at: string;
    confirmed_at: string | null; entries: (Entry & {entry_id: string})[];
    task_count_created: number; message_count_sent: number;
  } | null;
  source_index: {source_id: string; version: string; withdrawn: boolean}[];
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
type Pending = {
  action: string; title: string; details: string[];
  payload: Record<string,unknown>; key: string;
};
type MutationResult = {
  version?: string; state?: string; minute_id?: string; application_id?: string;
  tasks_created?: number; messages_sent?: number;
  funds_transferred?: boolean; authorization_id?: string;
};

const KIND_LABELS: Record<Kind,string> = {
  OPINION: "讨论意见", SUGGESTION: "建议",
  DECISION: "明确决定", ASSIGNMENT_DRAFT: "交办草稿",
};
const TABS: Kind[] = ["OPINION", "SUGGESTION", "DECISION", "ASSIGNMENT_DRAFT"];
function time(raw: string | null | undefined) {return raw?raw.replace("T"," "):"待核查";}
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
    <p>{entry.text}</p><small>原文位置：{entry.source_anchor}</small>
  </div>;
}
function VersionValue({label,value}:{label:string;value?:string|number|null}) {
  return <div className="boss-kv"><span>{label}</span><strong>{value??"未知"}</strong></div>;
}

function useConfirmedMutation(onSuccess: ()=>void) {
  const {client,getToken}=useClient();
  const [lookupBusy,setLookupBusy]=useState(false);
  const [pending,setPending]=useState<Pending|null>(null);
  const [checked,setChecked]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const dialogRef=useRef<HTMLElement|null>(null);
  const busyRef=useRef(false);
  busyRef.current=busy;
  useEffect(()=>{
    if(!pending)return;
    const before=document.activeElement instanceof HTMLElement?document.activeElement:null;
    dialogRef.current?.focus();
    const keyboard=(e:KeyboardEvent)=>{
      if(e.key==="Escape"&&!busyRef.current) {
        e.preventDefault();setPending(null);setChecked(false);
      }
      if(e.key!=="Tab"||!dialogRef.current)return;
      const items=Array.from(dialogRef.current.querySelectorAll<HTMLElement>(
        "button:not([disabled]), input:not([disabled])"
      )).filter(item=>item.getClientRects().length>0);
      if(!items.length)return;
      if(e.shiftKey&&document.activeElement===items[0]) {
        e.preventDefault();items[items.length-1].focus();
      }else if(!e.shiftKey&&document.activeElement===items[items.length-1]) {
        e.preventDefault();items[0].focus();
      }
    };
    document.addEventListener("keydown",keyboard);
    return ()=>{document.removeEventListener("keydown",keyboard);before?.focus();};
  },[pending?.key]);
  const propose=useCallback((action:string,payload:Record<string,unknown>,title:string,details:string[])=>{
    setPending({action,payload,title,details,key:"boss-"+crypto.randomUUID()});
    setChecked(false);setError("");setNotice("");
  },[]);
  const commit=async()=>{
    if(!pending||!checked||busy)return;
    setBusy(true);setError("");
    try{
      const result=await client.requestMutation<MutationResult>(pending.action,{
        ...pending.payload,client_request_id:pending.key,
      });
      setNotice("当前模拟操作已保存："+(result.state||"已记录")+
        " · 版本 "+(result.version||"待核查")+
        "。纪要、审批、交办和消息会分别回读，不会推定发生资金交易或实际发送。");
      setPending(null);setChecked(false);
      onSuccess();
    }catch(e){
      setError((e instanceof Error?e.message:String(e))+
        "。该操作可能已经保存；请先重新读取，必要时使用本弹窗原请求编号重试。");
    }finally{setBusy(false);}
  };
  const reconcile=async()=>{
    if(!pending||busy||lookupBusy)return;
    const token=getToken();
    if(!token){setError("身份已失效，不能查询本次请求");return;}
    setLookupBusy(true);setError("");
    try{
      const query=new URLSearchParams({
        action:pending.action,client_request_id:pending.key,
      });
      const response=await fetch("/api/boss/ui/operation-status?"+query.toString(),{
        headers:{Authorization:"Bearer "+token},cache:"no-store",
      });
      if(!response.ok)throw Error("当前操作回执读取失败（HTTP "+response.status+"）");
      const result=await response.json() as {
        action:string;client_request_id:string;outcome:string;result?:MutationResult;
      };
      if(result.action!==pending.action||result.client_request_id!==pending.key)
        throw Error("服务端回执与本次操作标识不匹配");
      if(result.outcome==="RECORDED"&&result.result){
        setNotice("已通过实际 SQLite 回执确认本次纪要/审批操作完成，现重新读取版本与决定。");
        setPending(null);setChecked(false);onSuccess();
      }else if(result.outcome==="NOT_FOUND_IN_CURRENT_STORE"){
        setError("当前没有发现原请求回执，不能因此断定没有执行。先重读正式状态，必要时使用本确认框同一请求编号重试。");
        onSuccess();
      }else throw Error("服务端结果无法核验，不重新提交");
    }catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setLookupBusy(false);}
  };
  const dialog=pending?<div className="boss-confirm-backdrop">
    <section ref={dialogRef} tabIndex={-1} role="dialog" aria-modal="true"
      aria-labelledby="boss-meeting-approval-confirm" className="boss-confirm">
      <h3 id="boss-meeting-approval-confirm"><ShieldCheck size={18}/>{pending.title}</h3>
      <p>本次动作只限当前已认证身份、对象、内容及版本。由服务端原子检查授权、来源和幂等请求。</p>
      <dl>{pending.details.map((detail,i)=><div key={i}><dd>{detail}</dd></div>)}</dl>
      <label className="boss-confirm-check">
        <input type="checkbox" checked={checked} disabled={busy}
          onChange={e=>setChecked(e.target.checked)}/>
        <span>我已经核对具体材料与本次处理后果，同意提交上述模拟操作。</span>
      </label>
      {error&&<p className="boss-validation-error" role="alert">{error}</p>}
      <footer className="boss-actions">
        <button className="boss-btn" type="button" disabled={busy||lookupBusy}
          onClick={()=>{setPending(null);setChecked(false);}}>取消（零写入）</button>
        <button className="boss-btn" type="button" disabled={busy||lookupBusy}
          onClick={()=>void reconcile()}>
          {lookupBusy&&<Loader2 size={15} className="boss-spin"/>} 核对原请求回执
        </button>
        <button type="button" className="boss-btn boss-btn-primary" disabled={!checked||busy||lookupBusy}
          onClick={()=>void commit()}>{busy&&<Loader2 className="boss-spin" size={15}/>} 确认并提交</button>
      </footer>
    </section>
  </div>:null;
  return {propose,dialog,notice,error,pending,busy,resetNotice:()=>setNotice("")};
}

export function BossMeetingApprovalView({pageId,onViewSource,onNavigate,onTaskCreated}:{
  pageId:"F05"|"F07";
  onViewSource:(sourceId:string)=>void;
  onNavigate:(pageId:string)=>void;
  onTaskCreated:(taskId:string)=>void;
}) {
  const {getToken}=useClient();
  const [data,setData]=useState<MinutesResponse|Decisions|null>(null);
  const [source,setSource]=useState<Evidence|null>(null);
  const [revision,setRevision]=useState(0);
  const [error,setError]=useState("");
  const [loading,setLoading]=useState(false);
  const [dirty,setDirty]=useState(false);
  const [entries,setEntries]=useState<Entry[]>([]);
  const [kind,setKind]=useState<Kind>("OPINION");
  const [text,setText]=useState("");
  const [anchor,setAnchor]=useState("");
  const [selectedApplication,setSelectedApplication]=useState("");
  const [decision,setDecision]=useState<""|"APPROVE"|"REJECT"|"REQUEST_MORE">("");
  const [comment,setComment]=useState("");
  const reload=()=>setRevision(x=>x+1);
  const mutation=useConfirmedMutation(()=>{setDirty(false);reload();});

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
      if(!res.ok)throw Error("读取会议或审批数据失败，HTTP "+res.status);
      return await res.json() as MinutesResponse|Decisions;
    }).then(async result=>{
      if(abort.signal.aborted)return;
      if(result.source_type!=="SIMULATED"||result.projection!==segment)throw Error("业务投影来源不符");
      setData(result);setLoading(false);
      if(pageId==="F05"){
        const minutes=result as MinutesResponse;
        if(minutes.minute&&!dirty){
          setEntries(minutes.minute.entries.map(row=>({
            kind:row.kind,text:row.text,source_anchor:row.source_anchor,
          })));
        }
        const id=minutes.minute?.source_id || "meeting-minutes";
        const response=await fetch("/api/boss/ui/evidence?source="+encodeURIComponent(id),{
          headers,cache:"no-store",signal:abort.signal,
        });
        if(response.ok){
          const value=await response.json() as Evidence;
          if(!abort.signal.aborted&&value.source_type==="SIMULATED")setSource(value);
        }
      }
    }).catch(e=>{
      if(abort.signal.aborted)return;
      setError(e instanceof Error?e.message:String(e));setLoading(false);
    });
    return ()=>abort.abort();
  },[pageId,revision,getToken]);

  const minutes=pageId==="F05"?data as MinutesResponse|null:null;
  const approvals=pageId==="F07"?data as Decisions|null:null;
  const fragments=useMemo(()=>{
    if(!source?.content)return [];
    return source.content.split(/[。；\n]/g).map(x=>x.trim()).filter(Boolean).map(
      phrase=>phrase.length>80?phrase.slice(0,80):phrase);
  },[source?.content]);
  const app=approvals?.applications.find(x=>x.application_id===selectedApplication)||
    approvals?.applications[0];
  const selected=app?.application_id||"";
  const minute=minutes?.minute;
  const save=()=>{
    setError("");
    if(!minutes?.meeting){setError("原始会议尚未载入");return;}
    if(!source){setError("当前未能读取原始纪要，请先核对资料");return;}
    if(entries.length<1){setError("先逐条记录并分类意见、建议、决定或交办草稿");return;}
    mutation.propose("boss.minutes.save",{
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
  const confirmMinutes=()=>{
    setError("");
    if(!minute||minute.state!=="DRAFT_REVIEW"||!source){
      setError("当前没有可确认的最新纪要草稿或原始材料已失效");return;
    }
    if(dirty){setError("还有尚未保存的编辑。请先保存草稿并核对最新版本");return;}
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
    setError("");
    if(!app){setError("当前没有经过维护端录入的模拟审批申请");return;}
    if(!decision){setError("须由本人明确选择同意、拒绝或请求补充");return;}
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

  return <>
    {loading&&<Tip>正在读取获准的原始材料、申请版本与已有决定…</Tip>}
    {error&&<div className="boss-status boss-status-error" role="alert"><AlertCircle size={16}/>{error}</div>}
    {mutation.notice&&<div className="boss-status boss-status-ok" role="status">
      <CheckCircle2 size={16}/>{mutation.notice}</div>}
    <div className="boss-columns">
      <div className="boss-column">
        {pageId==="F05" ? <>
          <Panel title="会议纪要 · 分类核查" note="意见 / 建议 / 明确决定 / 交办草稿">
            {minutes?<>
              <div className="boss-form-grid">
                <label>会议标识<input readOnly value={minutes.meeting.meeting_id}/></label>
                <label>会议版本<input readOnly value={minutes.meeting.version}/></label>
                <label>会议时间<input readOnly value={time(minutes.meeting.starts_at)}/></label>
                <label>当前纪要状态<input readOnly value={minute?.state||"尚未保存"}/></label>
              </div>
              <div className="boss-minutes-tabs">
                {TABS.map(k=><button type="button" key={k} className={kind===k?"selected":""}
                  onClick={()=>setKind(k)}>{KIND_LABELS[k]} <span>{entries.filter(e=>e.kind===k).length}</span></button>)}
              </div>
              <div className="boss-minutes-editor">
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
                    disabled={!source}><Plus size={16}/> 添加本条内容</button>
                </div>
              </div>
              {entries.length?entries.map((e,i)=><div key={i} className="boss-minutes-edit-row">
                <EntryRow entry={e}/>
                <button type="button" aria-label={"移除第"+(i+1)+"条内容"} onClick={()=>{
                  setEntries(old=>old.filter((_,j)=>j!==i));setDirty(true);
                }}><Trash2 size={16}/></button>
              </div>):<Empty>还没有分类的纪要内容。不会从静态示例自动生成老板决定或任务。</Empty>}
              <div className="boss-actions">
                <button type="button" className="boss-btn" onClick={save} disabled={!entries.length||mutation.busy}>
                  保存纪要草稿</button>
                <button type="button" className="boss-btn boss-btn-primary" onClick={confirmMinutes}
                  disabled={!minute||minute.state!=="DRAFT_REVIEW"||dirty||mutation.busy}>
                  <ShieldCheck size={15}/> 确认已保存的当前版本
                </button>
                <button type="button" className="boss-btn" onClick={reload}>
                  <RefreshCw size={15}/> 重读版本
                </button>
              </div>
              <Tip warning>确认纪要与发送交办是不同的本人决定。逐项创建只能在纪要已确认、来源仍有效且用户再次明确授权后执行。</Tip>
            </>:!loading&&<Empty>尚无可用会议资料。</Empty>}
          </Panel>
          <BossMinutesAssignmentActions
            minute={minute||null} participants={minutes?.meeting.participant_ids||[]}
            links={minutes?.linked_assignments||[]}
            sourceCurrent={Boolean(source&&minute&&source.source_id===minute.source_id&&source.version===minute.source_version)}
            editingUnsaved={dirty} onReload={reload}
            onTaskCreated={onTaskCreated} onNavigate={onNavigate}
          />
        </>:<>
          <Panel title="当前模拟申请" note="F07 · 对象 / 金额 / 币种 / 附件版本">
            {approvals?.applications.length?<>
              <label className="boss-label" htmlFor="boss-application-select">选择申请</label>
              <select className="boss-single-input" id="boss-application-select"
                value={selected} onChange={e=>{setSelectedApplication(e.target.value);setDecision("");setComment("");}}>
                {approvals.applications.map(a=><option value={a.application_id} key={a.application_id}>
                  {a.title} · {a.application_id}
                </option>)}
              </select>
              {app&&<>
                <VersionValue label="申请 ID" value={app.application_id}/>
                <VersionValue label="申请版本" value={app.version}/>
                <VersionValue label="金额与币种" value={app.amount+" "+app.currency}/>
                <VersionValue label="当前状态" value={app.state}/>
                <VersionValue label="附件状态" value={app.attachment_status}/>
                <div className="boss-approval-description">{app.description||"摘要尚未提供"}</div>
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
                      disabled={!["PENDING_DECISION","WAITING_MATERIAL"].includes(app.state) ||
                        (value!=="REQUEST_MORE"&&app.attachment_status!=="CURRENT")}
                      onChange={()=>setDecision(value)}/>
                    <span>{label}</span>
                  </label>)}
                </div>
                <label className="boss-label" htmlFor="boss-approval-comment">本人意见（必填）</label>
                <textarea rows={3} id="boss-approval-comment" value={comment}
                  onChange={e=>setComment(e.target.value)}
                  placeholder="说明对当前版本申请的批准范围、拒绝原因或必须补充的材料。"/>
                <div className="boss-actions">
                  <button type="button" className="boss-btn boss-btn-primary"
                    onClick={submitDecision} disabled={!decision||!comment.trim()||
                    mutation.busy||!["PENDING_DECISION","WAITING_MATERIAL"].includes(app.state)}>
                    <ShieldCheck size={15}/> 确认并提交本人决定
                  </button>
                  <button type="button" className="boss-btn" onClick={reload}>
                    <RefreshCw size={15}/> 重读正式状态
                  </button>
                </div>
              </>}
            </>:<Empty>尚未录入获准的模拟审批申请。维护者只能准备模拟材料，不能代替本人作出审批。</Empty>}
            <Tip warning>本界面只保存申请版本对应的模拟审批记录。没有资金交易、专业放行或真实外部消息发送。</Tip>
          </Panel>
          <Panel title="已经记录的本人决定" note="实际状态，不以按钮点击推断成功">
            {(approvals?.decisions||[]).length?(approvals?.decisions||[]).map(x=><div
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
          <Panel title="原文与草稿对应" note="证据有效性实时读取">
            <VersionValue label="原始会议" value={minutes?.meeting.meeting_id}/>
            <VersionValue label="原文版本" value={source?.version}/>
            <VersionValue label="已保存纪要版本" value={minute?.version}/>
            <VersionValue label="已确认时间" value={time(minute?.confirmed_at)}/>
            {source?.content?<blockquote className="boss-source">{source.content}</blockquote>
              :<Tip warning>资料已撤销、未获取或当前身份无权读取，不能确认纪要。</Tip>}
            {source&&<div className="boss-actions"><button className="boss-btn" type="button"
              onClick={()=>onViewSource(source.source_id)}>查看完整原文 <ArrowRight size={15}/></button></div>}
            {(minutes?.revisions||[]).length>0&&<div className="boss-minutes-history">
              <h3>历史纪要版本</h3>
              {minutes?.revisions.map(x=><p key={x.version}>v{x.version} · {x.state} · {time(x.updated_at)}</p>)}
            </div>}
          </Panel>
          <Panel title="关联交办与模拟发送回读">
            <VersionValue label="人工逐项创建的任务" value={minutes?.linked_assignments.length||0}/>
            <VersionValue label="已经模拟发送的关联交办" value={
              minutes?.linked_assignments.filter(x=>x.send_status==="SENT_SIMULATED").length||0}/>
            <VersionValue label="是否自动创建交办" value="否"/>
            <VersionValue label="是否自动发送" value="否"/>
            <div className="boss-actions">
              <button className="boss-btn boss-btn-primary" type="button"
                onClick={()=>onNavigate("F06")}><ClipboardCheck size={15}/> 进入 F06 交办详情</button>
            </div>
          </Panel>
        </>:<>
          <Panel title="审批安全边界" note="仅当前申请版本">
            <VersionValue label="申请状态" value={app?.state}/>
            <VersionValue label="附件 ID" value={app?.source_id}/>
            <VersionValue label="附件版本" value={app?.source_version}/>
            <VersionValue label="材料完整性" value={app?.attachment_status}/>
            <VersionValue label="授权动作" value={decision||"尚未选择"}/>
            <VersionValue label="真实资金交易" value="未执行"/>
            <Tip warning>没有真实交易系统连接。发生附件撤销、申请版本变更、金额或币种变化时，原选择不能继续使用。</Tip>
          </Panel>
          <Panel title="相关业务入口">
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
    {mutation.dialog}
  </>;
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
        <textarea rows={3} value={description} onChange={e=>setDescription(e.target.value)}/>
        <label className="boss-label">模拟申请附件内容（12—2500 字）</label>
        <textarea rows={4} value={attachment} onChange={e=>setAttachment(e.target.value)}
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
  </>;
}
