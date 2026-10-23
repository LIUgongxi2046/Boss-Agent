import { useEffect, useRef, useState } from "react";
import { AlertCircle, CheckCircle2, Clock3, Loader2, ShieldCheck, XCircle } from "lucide-react";
import { useClient } from "@/providers/ClientProvider";

export type SelfCommitment = {
  commitment_id:string; purpose:string; status:"ACTIVE"|"COMPLETED_CONFIRMED"|"CANCELED";
  version:string;due_at:string;timezone:string;importance:string;
  evidence_requirements:string[];source_refs:{source_id:string;version:string}[];
  completion_evidence?:{source_id:string;version:string}[];
  source_reference_state?:"CURRENT"|"NEEDS_REVIEW";
};
type Props={items:SelfCommitment[];businessClock?:string;onReload:()=>void};
type Pending={action:string;id:string;payload:Record<string,unknown>;
  title:string;details:string[]};
function shanghai(text:string){
  if(!/^\d{4}-\d\d-\d\dT\d\d:\d\d$/.test(text))throw Error("请填写完整北京时间和分钟");
  return text+":00+08:00";
}
function input(value:string,label:string,limit=1500){
  if(!value.trim()||value.length>limit)throw Error(label+"须填写且不能超过 "+limit+" 字");
  return value.trim();
}
export function BossPersonalCommitments({items,businessClock,onReload}:Props){
  const {client,getToken}=useClient();
  const [purpose,setPurpose]=useState("");
  const [due,setDue]=useState("");
  const [importance,setImportance]=useState("NORMAL");
  const [requiredProof,setRequiredProof]=useState("");
  const [currentId,setCurrentId]=useState("");
  const [proofId,setProofId]=useState("");
  const [proofVersion,setProofVersion]=useState("1");
  const [newDue,setNewDue]=useState("");
  const [reason,setReason]=useState("");
  const [error,setError]=useState("");
  const [success,setSuccess]=useState("");
  const [pending,setPending]=useState<Pending|null>(null);
  const [approved,setApproved]=useState(false);
  const [busy,setBusy]=useState(false);
  const [checking,setChecking]=useState(false);
  const dialog=useRef<HTMLElement|null>(null);
  const active=items.find(x=>x.commitment_id===currentId)||items.find(x=>x.status==="ACTIVE")||null;
  useEffect(()=>{
    if(!pending)return;
    const old=document.activeElement instanceof HTMLElement?document.activeElement:null;
    dialog.current?.focus();
    const key=(event:KeyboardEvent)=>{
      if(event.key==="Escape"&&!busy&&!checking){setPending(null);setApproved(false);}
      if(event.key!=="Tab"||!dialog.current)return;
      const els=Array.from(dialog.current.querySelectorAll<HTMLElement>(
        "button:not([disabled]),input:not([disabled])")).filter(x=>x.getClientRects().length>0);
      if(!els.length)return;
      if(event.shiftKey&&document.activeElement===els[0]){
        event.preventDefault();els[els.length-1].focus();
      }else if(!event.shiftKey&&document.activeElement===els[els.length-1]){
        event.preventDefault();els[0].focus();
      }
    };
    document.addEventListener("keydown",key);
    return()=>{document.removeEventListener("keydown",key);old?.focus();};
  },[pending?.id,busy,checking]);
  function propose(action:string,payload:Record<string,unknown>,title:string,details:string[]){
    setError("");setSuccess("");setApproved(false);
    setPending({action,payload,id:"boss-"+crypto.randomUUID(),title,details});
  }
  function make(){
    try{
      const body=input(purpose,"本人承诺");
      const proof=input(requiredProof,"核查证据要求",160);
      const target=shanghai(due);
      propose("boss.commitment.create",{
        purpose:body,due_at:target,timezone:"Asia/Shanghai",
        evidence_requirements:[proof],source_refs:[],importance,
      },"创建老板本人的承诺",[
        "本人承诺："+body,"目标时点："+target,
        "重要程度："+importance,"完成核查要求："+proof,
        "不会发送给他人，不会创建任何员工账号或模拟发件。",
      ]);
    }catch(e){setError(e instanceof Error?e.message:String(e));}
  }
  function decide(kind:"complete"|"extend"|"cancel"){
    try{
      if(!active||active.status!=="ACTIVE")throw Error("请选择实际有效的本人承诺");
      const common={commitment_id:active.commitment_id,expected_version:active.version};
      if(kind==="complete"){
        if(!proofId.trim()||!proofVersion.trim())throw Error("确认完成必须包含当前可核验的原文证据及版本");
        propose("boss.commitment.complete",{
          ...common,evidence_refs:[{source_id:proofId.trim(),version:proofVersion.trim()}],
        },"核对证据并确认完成本人承诺",[
          "本人承诺："+active.commitment_id+" v"+active.version,
          "证据："+proofId+" v"+proofVersion,
          "源资料须经服务端再次验证当前有效，完成后停止未来提醒。",
        ]);
      }else if(kind==="extend"){
        const target=shanghai(newDue);
        const note=input(reason,"延期原因",500);
        propose("boss.commitment.extend",{
          ...common,due_at:target,reason:note,
        },"本人确认调整承诺期限",[
          "对象："+active.commitment_id+" v"+active.version,
          "原期限："+active.due_at,"新期限："+target,
          "原因："+note,"新期限只有本人确认后生效。",
        ]);
      }else{
        const note=input(reason,"取消原因",500);
        propose("boss.commitment.cancel",{...common,reason:note},
          "本人确认取消承诺",[
            "对象："+active.commitment_id+" v"+active.version,
            "原因："+note,"任务历史和原提醒记录保留，新的到期提示停止。",
          ]);
      }
    }catch(e){setError(e instanceof Error?e.message:String(e));}
  }
  async function submit(){
    if(!pending||!approved||busy||checking)return;
    setBusy(true);setError("");
    try{
      const result=await client.requestMutation<{
        status?:string;version?:string;commitment_id?:string;
      }>(pending.action,{...pending.payload,client_request_id:pending.id});
      if(result.commitment_id)setCurrentId(result.commitment_id);
      setSuccess("已保存真实本人承诺状态："+(result.status||"待核查")+
        "，版本 "+(result.version||"待核查")+"。");
      setPending(null);setApproved(false);onReload();
    }catch(e){
      setError((e instanceof Error?e.message:String(e))+
        "。结果不确定，请先核查本次原请求回执，不要使用新编号重复操作。");
    }finally{setBusy(false);}
  }
  async function reconcile(){
    if(!pending||busy||checking)return;
    const token=getToken();
    if(!token){setError("身份过期，无法查询原请求");return;}
    setChecking(true);setError("");
    try{
      const query=new URLSearchParams({
        action:pending.action,client_request_id:pending.id,
      });
      const res=await fetch("/api/boss/ui/operation-status?"+query.toString(),{
        headers:{Authorization:"Bearer "+token},cache:"no-store",
      });
      if(!res.ok)throw Error("查询回执失败，HTTP "+res.status);
      const record=await res.json() as {
        outcome:string;action:string;client_request_id:string;
        result?:{commitment_id?:string;status?:string;version?:string};
      };
      if(record.action!==pending.action||record.client_request_id!==pending.id)
        throw Error("回执 ID 与本次动作不一致");
      if(record.outcome==="RECORDED"&&record.result){
        if(record.result.commitment_id)setCurrentId(record.result.commitment_id);
        setSuccess("服务端已确认原请求持久化："+(record.result.status||"已记录"));
        setPending(null);setApproved(false);onReload();
      }else if(record.outcome==="NOT_FOUND_IN_CURRENT_STORE"){
        setError("当前没有查询到回执，但不等于没有执行。请重读正式状态，必要时复用此编号重试。");
        onReload();
      }else throw Error("未知回执，不能直接重发");
    }catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setChecking(false);}
  }
  return <>
    <section className="boss-panel">
      <div className="boss-panel-head"><h2>本人承诺</h2>
        <small>独立于他人交办 · 创建、延期、取消和本人证据确认</small>
      </div>
      <div className="boss-form-grid">
        <label>承诺目标<input value={purpose} onChange={e=>setPurpose(e.target.value)}
          placeholder="写清本人拟完成的工作和产物"/></label>
        <label>本人原定期限（北京时间）<input type="datetime-local" value={due}
          onChange={e=>setDue(e.target.value)}/></label>
        <label>重要程度
          <select value={importance} onChange={e=>setImportance(e.target.value)}>
            <option value="NORMAL">普通</option><option value="IMPORTANT">重要</option>
          </select>
        </label>
        <label>完成核查证据要求<input value={requiredProof}
          onChange={e=>setRequiredProof(e.target.value)}
          placeholder="例如：当前版本的原始经营依据"/></label>
      </div>
      <div className="boss-actions">
        <button type="button" className="boss-btn boss-btn-primary" disabled={busy}
          onClick={make}><ShieldCheck size={15}/> 本人核对并创建承诺</button>
      </div>
      <div className="boss-status">
        <Clock3 size={16}/> 本人承诺与对他人交办是两个独立业务对象。不会自动给任何员工发消息；
        到期提醒属于本地模拟调度，实际外部通知仍未接入。
      </div>
      {items.length?items.map(row=><button key={row.commitment_id} type="button"
        className={"boss-task-row "+(active?.commitment_id===row.commitment_id?"selected":"")}
        onClick={()=>setCurrentId(row.commitment_id)}>
        <span className="boss-task-icon"><CheckCircle2 size={17}/></span>
        <span><strong>{row.purpose}</strong>
          <small>{row.commitment_id} · v{row.version} · {row.status}</small>
          <small>期限 {row.due_at.replace("T"," ")} · 重要程度 {row.importance}</small>
        </span>
      </button>):<div className="boss-empty"><p>当前没有本次会话创建的本人承诺；不使用历史记录伪装新任务。</p></div>}
      {active&&<>
        <div className="boss-kv"><span>当前选中状态</span><strong>{active.status}</strong></div>
        <div className="boss-kv"><span>版本</span><strong>{active.version}</strong></div>
        <div className="boss-kv"><span>当前到期</span><strong>{active.due_at.replace("T"," ")}</strong></div>
        <div className="boss-kv"><span>资料证据有效性</span><strong>{active.source_reference_state||"尚未核查"}</strong></div>
        {active.source_reference_state==="NEEDS_REVIEW"&&<div className="boss-status boss-status-warn"><AlertCircle size={15}/> 本人承诺原始来源已撤销或版本变化，需重新核查当前证据。</div>}
        <div className="boss-kv"><span>当前模拟业务时钟</span><strong>{businessClock?.replace("T"," ")||"未知"}</strong></div>
        <div className="boss-form-grid">
          <label>核查证据来源 ID<input value={proofId}
            onChange={e=>setProofId(e.target.value)} placeholder="例如 finance-note"/></label>
          <label>来源当前版本<input value={proofVersion}
            onChange={e=>setProofVersion(e.target.value)} placeholder="1"/></label>
          <label>调整后的期限<input type="datetime-local" value={newDue}
            onChange={e=>setNewDue(e.target.value)}/></label>
          <label>延期或取消的原因<input value={reason}
            onChange={e=>setReason(e.target.value)}/></label>
        </div>
        <div className="boss-actions">
          <button type="button" className="boss-btn boss-btn-primary"
            disabled={active.status!=="ACTIVE"||busy} onClick={()=>decide("complete")}>
            <CheckCircle2 size={15}/> 核查证据并确认完成</button>
          <button type="button" className="boss-btn"
            disabled={active.status!=="ACTIVE"||busy} onClick={()=>decide("extend")}>
            <Clock3 size={15}/> 本人批准延期</button>
          <button type="button" className="boss-btn"
            disabled={active.status!=="ACTIVE"||busy} onClick={()=>decide("cancel")}>
            <XCircle size={15}/> 取消本人承诺</button>
        </div>
      </>}
      {error&&<div className="boss-status boss-status-error" role="alert">
        <AlertCircle size={16}/>{error}</div>}
      {success&&<div className="boss-status boss-status-ok" role="status">
        <CheckCircle2 size={16}/>{success}</div>}
    </section>
    {pending&&<div className="boss-confirm-backdrop">
      <section ref={dialog} tabIndex={-1} role="dialog" aria-modal="true"
        aria-labelledby="boss-self-promise-confirm" className="boss-confirm">
        <h3 id="boss-self-promise-confirm"><ShieldCheck size={19}/>{pending.title}</h3>
        <p>这是本人承诺的独立写入，不替代任何对外交办，不自动确认无证据的完成。</p>
        <dl>{pending.details.map((line,i)=><div key={i}><dd>{line}</dd></div>)}</dl>
        <label className="boss-confirm-check">
          <input type="checkbox" checked={approved} disabled={busy}
            onChange={e=>setApproved(e.target.checked)}/>
          <span>我核对了当前承诺、期限及证据，确认本次操作。</span>
        </label>
        {error&&<p className="boss-validation-error" role="alert">{error}</p>}
        <footer className="boss-actions">
          <button className="boss-btn" type="button" disabled={busy||checking}
            onClick={()=>setPending(null)}>取消</button>
          <button className="boss-btn" type="button" disabled={busy||checking}
            onClick={()=>void reconcile()}>
            {checking&&<Loader2 size={15} className="boss-spin"/>} 核查原请求
          </button>
          <button className="boss-btn boss-btn-primary" type="button"
            disabled={!approved||busy||checking} onClick={()=>void submit()}>
            {busy&&<Loader2 size={15} className="boss-spin"/>} 确认并保存
          </button>
        </footer>
      </section>
    </div>}
  </>;
}
