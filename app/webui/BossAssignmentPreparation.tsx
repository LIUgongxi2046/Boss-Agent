import {useCallback,useEffect,useRef,useState} from "react";
import {useClient} from "@/providers/ClientProvider";

type Receipt={client_request_id:string;task_id:string;task_version:string;run_id:string|null;request_state:string;adoption_state:string;write_performed_by_lookup:false;
  preparation:{source_type:"SIMULATED";task:{task_id:string;version:string;status:string};source_review:{binding_state:string;review_sha256:string;result_evidence_requires_resubmission:boolean};owner_decision_required:true;business_authority_granted:false}|null};
const terminal=(state:string)=>["SUCCEEDED","FAILED","CANCELED","TIMED_OUT"].includes(state);

export function BossAssignmentPreparation({taskId,taskVersion}:{taskId:string;taskVersion:string}){
  const {client,getToken,token}=useClient();
  const [key,setKey]=useState(()=>{const values=new URLSearchParams(window.location.search);return values.get("assignmentPreparationTask")===taskId?values.get("assignmentPreparation")??"":"";});
  const [receipt,setReceipt]=useState<Receipt|null>(null),[busy,setBusy]=useState(false),[unknown,setUnknown]=useState(false),[error,setError]=useState("");
  const epoch=useRef(0),sequence=useRef(0);
  const read=useCallback(async(original:string,signal?:AbortSignal)=>{
    const current=epoch.current,request=++sequence.current;
    const response=await fetch("/api/boss/ui/assignment-preparation?"+new URLSearchParams({client_request_id:original}),{headers:{Authorization:"Bearer "+getToken()},cache:"no-store",signal});
    if(current!==epoch.current||request!==sequence.current||signal?.aborted)return;
    if(response.status===401||response.status===403){setReceipt(null);if(response.status===401)window.dispatchEvent(new Event("boss-auth-expired"));}
    if(!response.ok)throw new Error("交办原请求读取失败，HTTP "+response.status);
    const value=await response.json() as Receipt;
    if(current!==epoch.current||request!==sequence.current||signal?.aborted)return;
    if(value.client_request_id!==original||value.task_id!==taskId||value.write_performed_by_lookup!==false)throw new Error("原请求不属于当前交办");
    setReceipt(value);setUnknown(!terminal(value.request_state));if(terminal(value.request_state))setBusy(false);
  },[getToken,taskId]);
  useEffect(()=>{
    const current=++epoch.current,abort=new AbortController();setReceipt(null);setBusy(false);setUnknown(Boolean(key));setError("");
    if(key)void read(key,abort.signal).catch(failure=>{if(current===epoch.current&&!abort.signal.aborted)setError(failure.message);});
    return()=>{epoch.current++;sequence.current++;abort.abort();};
  },[token,taskId,taskVersion,read]);
  async function prepare(){
    if(busy||unknown)return;
    const current=epoch.current,original="fc07-read-"+crypto.randomUUID();setKey(original);setReceipt(null);setBusy(true);setUnknown(true);setError("");
    const url=new URL(window.location.href);url.searchParams.set("assignmentPreparation",original);url.searchParams.set("assignmentPreparationTask",taskId);window.history.replaceState(null,"",url);
    await client.requestMutation("boss.assignment.prepare",{client_request_id:original,task_id:taskId,task_version:taskVersion}).then(async()=>{
      if(current===epoch.current)await read(original);
    }).catch(failure=>{if(current===epoch.current){setError(failure.message+"；请读取原请求编号。");if([400,401,403,404,409,410,413,422].includes(failure.status))setUnknown(false);if([401,403].includes(failure.status))setReceipt(null);}});
    if(current===epoch.current)setBusy(false);
  }
  async function recover(){const current=epoch.current;setError("");await read(key).catch(failure=>{if(current===epoch.current)setError(failure.message);});}
  return <section className="boss-panel" aria-label="当前交办助手读取"><header className="boss-panel-head"><h2>当前交办与依据准备</h2><span className="boss-tag boss-tag-amber">SIMULATED</span></header>
    <p>当前交办 {taskId} · v{taskVersion}。助手只读取已选任务与来源，发送、催办和结束由本人分别确认。</p>
    <div className="boss-actions"><button className="boss-btn" type="button" disabled={busy||unknown} onClick={()=>void prepare()}>通过助手读取当前交办与依据</button>
      {key&&<button className="boss-btn" type="button" disabled={busy} onClick={()=>void recover()}>读取原交办准备结果</button>}</div>
    {key&&<p>准备原请求 {key} · {receipt?.request_state??(busy?"执行中":"结果待核查")}</p>}
    {unknown&&<p role="status">结果尚未确定，仅查询原编号。</p>}
    {receipt?.preparation&&receipt.adoption_state==="CURRENT"?<><p>实际工具已经读取同一任务及来源；当前任务状态 {receipt.preparation.task.status}，来源 {receipt.preparation.source_review.binding_state}。</p><p>运行 {receipt.run_id} · 未授予业务授权。</p></>:receipt?.adoption_state==="HISTORICAL_REQUIRES_REQUERY"&&<p role="status">任务或来源已经变化，请按当前对象重新读取。</p>}
    {error&&<p className="boss-status boss-status-error" role="alert">{error}</p>}
  </section>;
}
