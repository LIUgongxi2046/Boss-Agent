import { useEffect, useRef, useState } from "react";
import { AlertCircle, ArrowRight, CheckCircle2, ClipboardCheck,
  Clock3, FileSearch, Loader2, RefreshCw, ShieldCheck } from "lucide-react";
import { useClient } from "@/providers/ClientProvider";

type MinuteEntry = {
  entry_id: string; kind: string; text: string; source_anchor: string;
};
type Minute = {
  minute_id: string; meeting_id: string; version: string;
  state: "DRAFT_REVIEW" | "CONFIRMED";
  source_id: string; source_version: string; entries: MinuteEntry[];
};
type TaskLink = {
  minute_id: string; minute_version: string; entry_id: string;
  task_id: string; task_status: string; task_version: string;
  send_status: string; sent_message_count: number;
  authorization_id: string; source_id: string; source_version: string;
};
type Props = {
  minute: Minute | null;
  participants: string[];
  contacts: {contact_id:string;name:string;organization:string;
    responsibility:string;allowed_for_fixture_assignment:boolean}[];
  businessClock:string;
  links: TaskLink[];
  sourceCurrent: boolean;
  editingUnsaved: boolean;
  onReload: () => void;
  onTaskCreated: (id: string) => void;
  onNavigate: (id: string) => void;
};
type Pending = {
  id: string; action: "boss.minutes.assignment.create";
  fields: Record<string, unknown>; preview: string[];
};
type Receipt = {
  action: string; client_request_id: string; outcome: string;
  result?: {task_id?: string; status?: string; version?: string};
};

function dateShanghai(value: string) {
  if (!/^\d{4}-\d\d-\d\dT\d\d:\d\d$/.test(value)) {
    throw Error("期限必须填写完整的年月日与时分");
  }
  return value + ":00+08:00";
}

export function BossMinutesAssignmentActions({
  minute, participants, contacts, businessClock, links, sourceCurrent, editingUnsaved,
  onReload, onTaskCreated, onNavigate,
}: Props) {
  const {client, getToken} = useClient();
  const candidates = minute?.entries.filter(x=>x.kind==="ASSIGNMENT_DRAFT") || [];
  const [entryId,setEntryId] = useState("");
  const [purpose,setPurpose] = useState("");
  const [coordinator,setCoordinator] = useState("");
  const [due,setDue] = useState("");
  const [evidence,setEvidence] = useState("");
  const [pending,setPending] = useState<Pending|null>(null);
  const [approved,setApproved] = useState(false);
  const [busy,setBusy] = useState(false);
  const [lookupBusy,setLookupBusy] = useState(false);
  const [error,setError] = useState("");
  const [notice,setNotice] = useState("");
  const dialogRef = useRef<HTMLElement|null>(null);
  const busyRef = useRef(false);
  busyRef.current = busy || lookupBusy;

  const entry = candidates.find(x=>x.entry_id===entryId);
  const alreadyLinked = links.find(x=>x.entry_id===entryId && x.minute_version===minute?.version);
  useEffect(()=>{
    if(!entryId || !candidates.some(x=>x.entry_id===entryId)){
      setEntryId(candidates[0]?.entry_id||"");
    }
  },[minute?.version,entryId,candidates.length]);
  useEffect(()=>{
    if(entry) setPurpose(entry.text);
    setError("");
  },[entry?.entry_id,minute?.version]);
  useEffect(()=>{
    if(!pending)return;
    const lastFocus = document.activeElement instanceof HTMLElement
      ? document.activeElement : null;
    dialogRef.current?.focus();
    const key=(e:KeyboardEvent)=>{
      if(e.key==="Escape"&&!busyRef.current){
        setPending(null);setApproved(false);return;
      }
      if(e.key!=="Tab"||!dialogRef.current)return;
      const nodes=Array.from(dialogRef.current.querySelectorAll<HTMLElement>(
        "button:not([disabled]),input:not([disabled])",
      )).filter(x=>x.getClientRects().length>0);
      if(!nodes.length){e.preventDefault();dialogRef.current.focus();return;}
      if(e.shiftKey&&document.activeElement===nodes[0]){
        e.preventDefault();nodes[nodes.length-1].focus();
      }else if(!e.shiftKey&&document.activeElement===nodes[nodes.length-1]){
        e.preventDefault();nodes[0].focus();
      }
    };
    document.addEventListener("keydown",key);
    return ()=>{document.removeEventListener("keydown",key);lastFocus?.focus();};
  },[pending?.id]);

  function propose(){
    setError("");setNotice("");
    try{
      if(!minute||minute.state!=="CONFIRMED")throw Error("必须先确认当前版本纪要");
      if(!entry||entry.kind!=="ASSIGNMENT_DRAFT")throw Error("请选择已确认纪要中的交办草稿");
      if(!sourceCurrent)throw Error("原始会议来源已失效，不能创建关联交办");
      if(editingUnsaved)throw Error("存在未保存的纪要修改，先保存并重读确认版本");
      if(alreadyLinked)throw Error("本条纪要已有关联交办，请直接打开原任务");
      const eligible = contacts.find(c=>c.contact_id===coordinator);
      if(!coordinator||!participants.includes(coordinator)||!eligible?.allowed_for_fixture_assignment)
        throw Error("须选择当前模拟业务时钟下获准的唯一负责人");
      if(!purpose.trim()||purpose.length>1600)throw Error("交办目的须为1—1600字");
      if(!evidence.trim()||evidence.length>160)throw Error("交付证据须为1—160字");
      const until=dateShanghai(due);
      if (businessClock && new Date(until).getTime() <= new Date(businessClock).getTime())
        throw Error("交办期限必须晚于当前模拟业务时钟");
      const fields:Record<string,unknown>={
        meeting_id:minute.meeting_id,minute_version:minute.version,
        entry_id:entry.entry_id,purpose:purpose.trim(),
        coordinator_id:coordinator,due_at:until,timezone:"Asia/Shanghai",
        evidence_requirements:[evidence.trim()],
      };
      setPending({
        id:"boss-"+crypto.randomUUID(),action:"boss.minutes.assignment.create",fields,
        preview:[
          "纪要："+minute.minute_id+" v"+minute.version,
          "条目："+entry.entry_id+"（已确认交办草稿）",
          "原文："+minute.source_id+" v"+minute.source_version+" · "+entry.source_anchor,
          "目标："+purpose.trim(),"唯一负责人："+coordinator,
          "截止："+until,"所需产物与证据："+evidence.trim(),
          "只创建 OPEN 任务；发送必须另行进入 F06 本人授权。",
        ],
      });
      setApproved(false);
    }catch(e){setError(e instanceof Error?e.message:String(e));}
  }

  async function send(){
    if(!pending||!approved||busy||lookupBusy)return;
    setBusy(true);setError("");
    try{
      const result=await client.requestMutation<{
        task_id: string; status: string; minute_version: string;
        message_sent: boolean; version: string;
      }>(pending.action,{...pending.fields,client_request_id:pending.id});
      if(!result.task_id||result.status!=="OPEN"||result.message_sent!==false)
        throw Error("当前交办结果不符合未发送的业务约束，必须重新读取");
      onTaskCreated(result.task_id);
      setNotice("已按已确认纪要条目单独创建 OPEN 交办。尚未发送，进入 F06 需再次确认。");
      setPending(null);setApproved(false);onReload();
    }catch(e){
      setError((e instanceof Error?e.message:String(e))+
        "。结果不确定时先查原请求回执，避免重复创建任务。");
    }finally{setBusy(false);}
  }
  async function reconcile(){
    if(!pending||busy||lookupBusy)return;
    const token=getToken();
    if(!token){setError("身份失效，无法核查原请求");return;}
    setLookupBusy(true);setError("");
    try{
      const qs=new URLSearchParams({
        action:pending.action,client_request_id:pending.id,
      });
      const response=await fetch("/api/boss/ui/operation-status?"+qs.toString(),{
        headers:{"Authorization":"Bearer "+token},cache:"no-store",
      });
      if(!response.ok)throw Error("原请求回执读取失败（HTTP "+response.status+"）");
      const outcome=await response.json() as Receipt;
      if(outcome.action!==pending.action||outcome.client_request_id!==pending.id)
        throw Error("当前回执与操作意图不匹配");
      if(outcome.outcome==="RECORDED"&&outcome.result?.task_id){
        onTaskCreated(outcome.result.task_id);
        setNotice("已从真实 SQLite 幂等回执确认交办已创建，请查看 F06 正式状态。");
        setPending(null);setApproved(false);onReload();
      }else if(outcome.outcome==="NOT_FOUND_IN_CURRENT_STORE"){
        setError("当前未发现原请求回执，但不能推定没有执行。请先重读状态，再使用相同编号重试。");
        onReload();
      }else throw Error("无法核实本次交办是否已执行");
    }catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setLookupBusy(false);}
  }

  return <section className="boss-panel" aria-label="已确认纪要逐项交办">
    <div className="boss-panel-head">
      <h2>逐项交办 · 与 F06 正式任务关联</h2>
      <small>已确认原文 / 唯一负责人 / 期限 / 证据</small>
    </div>
    {minute?.state!=="CONFIRMED"&&<div className="boss-status boss-status-warn">
      <Clock3 size={16}/> 先保存并确认当前纪要。意见、建议和未确认草稿不能创建交办。
    </div>}
    {minute?.state==="CONFIRMED"&&<div className="boss-status">
      <ShieldCheck size={16}/>
      已确认纪要 {minute.minute_id} · v{minute.version}。创建与发送仍是两次独立本人决定。
    </div>}
    {links.some(x=>x.minute_version!==minute?.version)&&
      <div className="boss-status boss-status-warn">
        <Clock3 size={16}/> 这份会议存在旧版本纪要关联的历史交办。当前只允许按最新已确认版本逐项授权，旧任务仍在 F06 保留。
      </div>}
    {candidates.length ? <>
      <label className="boss-label" htmlFor="boss-minute-entry">选择已确认交办草稿</label>
      <select id="boss-minute-entry" className="boss-single-input" value={entryId}
        onChange={e=>setEntryId(e.target.value)}>
        {candidates.map(item=><option key={item.entry_id} value={item.entry_id}>
          {item.entry_id} · {item.text.slice(0,48)}
        </option>)}
      </select>
      {entry&&<div className="boss-minutes-row">
        <strong>已确认纪要原文</strong>
        <p>{entry.text}</p>
        <small>来源位置：{entry.source_anchor} · {minute?.source_id} v{minute?.source_version}</small>
      </div>}
      {alreadyLinked ? <>
        <div className="boss-status boss-status-ok" role="status">
          <CheckCircle2 size={16}/> 已关联交办 {alreadyLinked.task_id}，状态 {alreadyLinked.task_status}，
          发送 {alreadyLinked.send_status}，不得再次创建。
        </div>
        <button type="button" className="boss-btn boss-btn-primary"
          onClick={()=>{onTaskCreated(alreadyLinked.task_id);onNavigate("F06");}}>
          <ArrowRight size={15}/> 查看 F06 原任务与进展
        </button>
      </> : <>
        <div className="boss-form-grid">
          <label>唯一负责人
            <select value={coordinator} onChange={e=>setCoordinator(e.target.value)}>
              <option value="">请选择当前联系人 ID</option>
              {contacts.filter(c=>participants.includes(c.contact_id)).map(c=>
                <option key={c.contact_id} value={c.contact_id}
                  disabled={!c.allowed_for_fixture_assignment}>
                  {c.name} · {c.organization} · {c.responsibility} [{c.contact_id}]
                  {!c.allowed_for_fixture_assignment?" · 当前无有效交办权限":""}
                </option>)}
            </select>
          </label>
          <label>期限（Asia/Shanghai）
            <input type="datetime-local" value={due} onChange={e=>setDue(e.target.value)}/>
          </label>
        </div>
        <label className="boss-label" htmlFor="boss-minute-purpose">交办目的与产物</label>
        <textarea id="boss-minute-purpose" rows={3} value={purpose}
          onChange={e=>setPurpose(e.target.value)} placeholder="请核对纪要草稿和实际交付内容"/>
        <label className="boss-label" htmlFor="boss-minute-evidence">证据要求</label>
        <input id="boss-minute-evidence" className="boss-single-input"
          value={evidence} onChange={e=>setEvidence(e.target.value)}
          placeholder="例如：经营原始明细及核对来源"/>
        <div className="boss-actions">
          <button type="button" className="boss-btn boss-btn-primary"
            disabled={!sourceCurrent||minute?.state!=="CONFIRMED"||editingUnsaved||busy}
            onClick={propose}>
            <ClipboardCheck size={16}/> 审阅并创建单项交办
          </button>
          <button type="button" className="boss-btn" onClick={onReload}>
            <RefreshCw size={15}/> 核对纪要与任务版本
          </button>
        </div>
        <p className="boss-helper">
          本次仅将经本人选择的交办条目创建为 OPEN 任务。必须单独在 F06 确认发送，
          不会因纪要确认而自动生成或发出全部任务。
        </p>
      </>}
    </> : <div className="boss-empty">
      <FileSearch size={18}/>
      <div><strong>当前纪要没有交办草稿</strong>
        <p>不能将讨论意见、建议或已确认决定自动替代成具体交办。</p></div>
    </div>}
    {error&&<div className="boss-status boss-status-error" role="alert">
      <AlertCircle size={16}/>{error}
    </div>}
    {notice&&<div className="boss-status boss-status-ok" role="status">
      <CheckCircle2 size={16}/>{notice}
    </div>}
    {pending&&<div className="boss-confirm-backdrop">
      <section className="boss-confirm" ref={dialogRef} tabIndex={-1}
        role="dialog" aria-modal="true" aria-labelledby="boss-minute-task-confirm">
        <h3 id="boss-minute-task-confirm"><ShieldCheck size={18}/> 本人确认逐项创建交办</h3>
        <p>每项关联原纪要条目与版本，产生唯一任务。请核对全部字段；此次不会发送消息。</p>
        <dl>{pending.preview.map((row,i)=><div key={i}><dd>{row}</dd></div>)}</dl>
        <label className="boss-confirm-check">
          <input type="checkbox" checked={approved} disabled={busy||lookupBusy}
            onChange={e=>setApproved(e.target.checked)}/>
          <span>我确认本条交办的负责人、期限、证据与原文版本，并同意仅创建任务。</span>
        </label>
        {error&&<p className="boss-validation-error" role="alert">{error}</p>}
        <footer className="boss-actions">
          <button className="boss-btn" type="button" disabled={busy||lookupBusy}
            onClick={()=>{setPending(null);setApproved(false);}}>取消（零写入）</button>
          <button className="boss-btn" type="button" disabled={busy||lookupBusy}
            onClick={()=>void reconcile()}>
            {lookupBusy&&<Loader2 size={15} className="boss-spin"/>} 核查原请求回执
          </button>
          <button className="boss-btn boss-btn-primary" type="button"
            disabled={!approved||busy||lookupBusy} onClick={()=>void send()}>
            {busy&&<Loader2 size={15} className="boss-spin"/>} 确认创建 OPEN 任务
          </button>
        </footer>
      </section>
    </div>}
  </section>;
}
