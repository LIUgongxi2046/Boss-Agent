import {useEffect,useRef,useState} from "react";
import {AlertCircle,CheckCircle2,Clock3,ShieldCheck,XCircle} from "lucide-react";
import {useClient} from "@/providers/ClientProvider";
import {useTransaction} from "./BossAssignmentFlow";

export type SelfCommitment={commitment_id:string;purpose:string;status:"ACTIVE"|"COMPLETED_CONFIRMED"|"CANCELED";version:string;due_at:string;timezone:string;importance:string;
  evidence_requirements:string[];source_refs:{source_id:string;version:string}[];completion_evidence?:{source_id:string;version:string}[];source_reference_state?:"CURRENT"|"NEEDS_REVIEW"};
type DueEvent={commitment_id:string;event_id:string;event_state:string;due_at:string};
type Source={source_id:string;version:string;content:string;published_at?:string;original_locator?:unknown};
type Props={items:SelfCommitment[];sources:{source_id:string;version:string;title:string}[];businessClock?:string;onReload:()=>void;onDirtyChange:(value:boolean)=>void;dueEvents?:DueEvent[];revisions?:SelfCommitment[]};
const STATES={ACTIVE:"进行中",COMPLETED_CONFIRMED:"已完成",CANCELED:"已取消"};
function time(value:string){return new Intl.DateTimeFormat("zh-CN",{timeZone:"Asia/Shanghai",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false}).format(new Date(value));}
function shanghai(text:string){if(!/^\d{4}-\d\d-\d\dT\d\d:\d\d$/.test(text))throw new Error("请填写完整北京时间和分钟");return text+":00+08:00";}
function input(value:string,label:string,limit=1500){if(!value.trim()||value.length>limit)throw new Error(label+"须填写且不能超过 "+limit+" 字");return value.trim();}

export function BossPersonalCommitments({items,sources,businessClock,onReload,onDirtyChange,dueEvents=[],revisions=[]}:Props){
  const {getToken,token}=useClient();
  const [purpose,setPurpose]=useState(""),[due,setDue]=useState(""),[importance,setImportance]=useState("NORMAL"),[requiredProof,setRequiredProof]=useState("");
  const [currentId,setCurrentId]=useState(()=>new URLSearchParams(window.location.search).get("bossCommitment")??"");
  const [sourceId,setSourceId]=useState(""),[sourceVersion,setSourceVersion]=useState(""),[proofId,setProofId]=useState(""),[proofVersion,setProofVersion]=useState("");
  const [newDue,setNewDue]=useState(""),[reason,setReason]=useState(""),[error,setError]=useState(""),[document,setDocument]=useState<{kind:"create"|"complete";value:Source}|null>(null);
  const sourceRequest=useRef<AbortController|null>(null),epoch=useRef(0);
  const active=currentId?items.find(item=>item.commitment_id===currentId):items.find(item=>item.status==="ACTIVE")??items[0];
  const sourceTitle=(id:string)=>sources.find(source=>source.source_id===id)?.title??"相关材料";
  function chooseSource(kind:"create"|"complete",id:string){const source=sources.find(item=>item.source_id===id);if(kind==="create"){setSourceId(id);setSourceVersion(source?.version??"");}else{setProofId(id);setProofVersion(source?.version??"");}}
  function saved(){setPurpose("");setDue("");setRequiredProof("");setSourceId("");setSourceVersion("");setProofId("");setProofVersion("");setNewDue("");setReason("");setDocument(null);onReload();}
  function select(id:string){setCurrentId(id);const url=new URL(window.location.href);url.searchParams.set("bossCommitment",id);window.history.replaceState(window.history.state,"",url);}
  const {propose,dialog,recovery,notice,busy}=useTransaction(saved,select,undefined,"commitment");
  useEffect(()=>{epoch.current++;sourceRequest.current?.abort();setDocument(null);return()=>{epoch.current++;sourceRequest.current?.abort();};},[token,active?.commitment_id,sourceId,sourceVersion,proofId,proofVersion]);
  useEffect(()=>{onDirtyChange(Boolean(purpose||due||requiredProof||sourceId||sourceVersion||proofId||proofVersion||newDue||reason||busy));},[purpose,due,requiredProof,sourceId,sourceVersion,proofId,proofVersion,newDue,reason,busy,onDirtyChange]);
  async function readSource(kind:"create"|"complete"){
    const id=kind==="create"?sourceId:proofId,version=kind==="create"?sourceVersion:proofVersion,current=epoch.current;
    if(!id.trim()||!version.trim()){setError("请选择需要阅读的材料");return;}
    sourceRequest.current?.abort();const abort=new AbortController();sourceRequest.current=abort;setError("");setDocument(null);
    await fetch("/api/boss/ui/evidence?"+new URLSearchParams({source:id.trim()}),{headers:{Authorization:"Bearer "+getToken()},cache:"no-store",signal:abort.signal}).then(async response=>{
      if(current!==epoch.current||abort.signal.aborted)return;
      if(response.status===401||response.status===403){setDocument(null);if(response.status===401)window.dispatchEvent(new Event("boss-auth-expired"));}
      if(!response.ok)throw new Error("承诺原文读取失败，HTTP "+response.status);
      const value=await response.json() as Source;if(current!==epoch.current||abort.signal.aborted)return;
      if(value.source_id!==id.trim()||value.version!==version.trim())throw new Error("材料已经更新，请重新选择并阅读");
      setDocument({kind,value});
    }).catch(failure=>{if(current===epoch.current&&!abort.signal.aborted)setError(failure.message);});
  }
  function make(){
    setError("");
    if(!document||document.kind!=="create"||document.value.source_id!==sourceId.trim()||document.value.version!==sourceVersion.trim()){setError("请阅读并核查本人承诺的相关材料");return;}
    const body=input(purpose,"本人承诺"),proof=input(requiredProof,"核查证据要求",160),target=shanghai(due);
    propose("boss.commitment.create",{purpose:body,due_at:target,timezone:"Asia/Shanghai",evidence_requirements:[proof],source_refs:[{source_id:sourceId.trim(),version:sourceVersion.trim()}],importance},"创建老板本人的承诺",[
      "本人承诺："+body,"截止时间："+time(target),"重要程度："+(importance==="IMPORTANT"?"重要":"普通"),"完成要求："+proof,"相关材料："+sourceTitle(sourceId)]);
  }
  function decide(kind:"complete"|"extend"|"cancel"){
    setError("");if(!active||active.status!=="ACTIVE"){setError("请选择当前有效的本人承诺");return;}
    const common={commitment_id:active.commitment_id,expected_version:active.version};
    if(kind==="complete"){
      if(!document||document.kind!=="complete"||document.value.source_id!==proofId.trim()||document.value.version!==proofVersion.trim()){setError("请阅读并核查完成材料");return;}
      propose("boss.commitment.complete",{...common,evidence_refs:[{source_id:proofId.trim(),version:proofVersion.trim()}]},"确认完成本人承诺",["本人承诺："+active.purpose,"完成材料："+sourceTitle(proofId),"确认后结束承诺并停止提醒。"]);
    }else if(kind==="extend"){
      const target=shanghai(newDue),note=input(reason,"延期原因",500);
      propose("boss.commitment.extend",{...common,due_at:target,reason:note},"确认调整承诺期限",["本人承诺："+active.purpose,"原期限："+time(active.due_at),"新期限："+time(target),"原因："+note]);
    }else{
      const note=input(reason,"取消原因",500);propose("boss.commitment.cancel",{...common,reason:note},"确认取消承诺",["本人承诺："+active.purpose,"原因："+note,"历史记录保留，到期提醒停止。"]);
    }
  }
  function checked(action:()=>void){try{action();}catch(failure){setError(failure instanceof Error?failure.message:String(failure));}}
  return <><section className="boss-panel boss-commitments" aria-label="本人承诺">
    <header className="boss-panel-head"><h2>本人承诺</h2></header>
    <fieldset disabled={busy}><div className="boss-form-grid">
      <label>承诺目标<input value={purpose} onChange={event=>setPurpose(event.target.value)} placeholder="写清本人拟完成的工作和产物"/></label>
      <label>本人原定期限（北京时间）<input type="datetime-local" value={due} onChange={event=>setDue(event.target.value)}/></label>
      <label>重要程度<select value={importance} onChange={event=>setImportance(event.target.value)}><option value="NORMAL">普通</option><option value="IMPORTANT">重要</option></select></label>
      <label>完成核查证据要求<input value={requiredProof} onChange={event=>setRequiredProof(event.target.value)}/></label>
      <label>相关材料<select value={sourceId} onChange={event=>chooseSource("create",event.target.value)}><option value="">请选择材料</option>{sources.map(source=><option key={source.source_id} value={source.source_id}>{source.title}</option>)}</select></label>
    </div><div className="boss-actions"><button className="boss-btn" type="button" onClick={()=>void readSource("create")}>读取本人承诺依据</button><button className="boss-btn boss-btn-primary" type="button" onClick={()=>checked(make)}><ShieldCheck size={15}/> 本人核对并创建承诺</button></div></fieldset>
    {items.length?items.map(item=><button type="button" className={"boss-task-row "+(active?.commitment_id===item.commitment_id?"selected":"")} key={item.commitment_id} disabled={busy} onClick={()=>select(item.commitment_id)}><CheckCircle2 size={17}/><span><strong>{item.purpose}</strong><small>{STATES[item.status]} · {item.importance==="IMPORTANT"?"重要":"普通"}</small><small>截止 {time(item.due_at)}{item.status==="ACTIVE"&&businessClock&&Date.parse(item.due_at)<Date.parse(businessClock)?" · 已经逾期":""}</small></span></button>):<p>当前没有本人承诺。</p>}
    {active&&<><h3>{active.purpose}</h3><p>完成要求：{active.evidence_requirements.join("；")}</p>
      <p>相关材料：{active.source_refs.map(reference=>sourceTitle(reference.source_id)).join("；")}</p><p>完成材料：{active.completion_evidence?.map(reference=>sourceTitle(reference.source_id)).join("；")||"尚未确认"}</p>
      {active.source_reference_state==="NEEDS_REVIEW"&&<p role="status"><AlertCircle size={15}/> 当前来源已经变化，需要重新核查。</p>}
      <fieldset disabled={busy||active.status!=="ACTIVE"}><div className="boss-form-grid"><label>完成材料<select value={proofId} onChange={event=>chooseSource("complete",event.target.value)}><option value="">请选择材料</option>{sources.map(source=><option key={source.source_id} value={source.source_id}>{source.title}</option>)}</select></label><label>调整后的期限<input type="datetime-local" value={newDue} onChange={event=>setNewDue(event.target.value)}/></label><label>延期或取消的原因<input value={reason} onChange={event=>setReason(event.target.value)}/></label></div>
        <div className="boss-actions"><button className="boss-btn" type="button" onClick={()=>void readSource("complete")}>读取当前完成证据</button><button className="boss-btn boss-btn-primary" type="button" disabled={active.source_reference_state!=="CURRENT"} onClick={()=>checked(()=>decide("complete"))}><CheckCircle2 size={15}/> 核查证据并确认完成</button><button className="boss-btn" type="button" disabled={active.source_reference_state!=="CURRENT"} onClick={()=>checked(()=>decide("extend"))}><Clock3 size={15}/> 本人批准延期</button><button className="boss-btn" type="button" onClick={()=>checked(()=>decide("cancel"))}><XCircle size={15}/> 取消本人承诺</button></div></fieldset>
      {dueEvents.filter(event=>event.commitment_id===active.commitment_id&&event.event_state==="OPEN").map(event=><p key={event.event_id}>到期提醒：{time(event.due_at)}</p>)}
      {revisions.filter(item=>item.commitment_id===active.commitment_id).map(item=><p key={item.version}>历史记录：{STATES[item.status]} · 截止 {time(item.due_at)}</p>)}
    </>}
    {document&&<article className="boss-document-source"><h3>{sourceTitle(document.value.source_id)}</h3>{document.value.published_at&&<p>发布时间：{time(document.value.published_at)}</p>}<blockquote>{document.value.content}</blockquote></article>}
    {error&&<p className="boss-status boss-status-error" role="alert">{error}</p>}{notice&&<p className="boss-status boss-status-ok" role="status">{notice}</p>}
  </section>{dialog}{recovery}</>;
}
