import {useCallback,useEffect,useRef,useState} from "react";
import {useClient} from "@/providers/ClientProvider";

type Receipt={client_request_id:string;run_id:string|null;request_state:string;adoption_state:"CURRENT"|"HISTORICAL_REQUIRES_REQUERY";projection_sha256:string;write_performed_by_lookup:false;
  preparation:{source_type:"SIMULATED";owner_decision_required:true;business_authority_granted:false;projection:{events:{event_id:string;version:string}[];rules:{version:string}[];dispatches:unknown[]}}|null};
const terminal=(state:string)=>["SUCCEEDED","FAILED","CANCELED","TIMED_OUT"].includes(state);

export function BossReminderPreparation({revision}:{revision:number}){
  const {client,getToken,token}=useClient();
  const [key,setKey]=useState(()=>new URLSearchParams(window.location.search).get("reminderPreparation")??"");
  const [receipt,setReceipt]=useState<Receipt|null>(null),[busy,setBusy]=useState(false),[unknown,setUnknown]=useState(Boolean(key)),[error,setError]=useState("");
  const epoch=useRef(0),sequence=useRef(0);
  const read=useCallback(async(original:string,signal?:AbortSignal)=>{
    const current=epoch.current,request=++sequence.current;
    const response=await fetch("/api/boss/ui/reminder-preparation?"+new URLSearchParams({client_request_id:original}),{headers:{Authorization:"Bearer "+getToken()},cache:"no-store",signal});
    if(current!==epoch.current||request!==sequence.current||signal?.aborted)return;
    if(response.status===401)window.dispatchEvent(new Event("boss-auth-expired"));
    if(!response.ok)throw new Error("提醒原准备结果读取失败，HTTP "+response.status);
    const value=await response.json() as Receipt;
    if(current!==epoch.current||request!==sequence.current||signal?.aborted)return;
    if(value.client_request_id!==original||value.write_performed_by_lookup!==false)throw new Error("提醒原请求标识不符");
    setReceipt(value);setUnknown(!terminal(value.request_state));
  },[getToken]);
  useEffect(()=>{const current=++epoch.current,abort=new AbortController();setReceipt(null);setBusy(false);setUnknown(Boolean(key));setError("");if(key)void read(key,abort.signal).catch(failure=>{if(current===epoch.current&&!abort.signal.aborted)setError(failure.message);});return()=>{epoch.current++;sequence.current++;abort.abort();};},[token,revision,read]);
  async function prepare(){
    if(busy||unknown)return;const current=epoch.current,original="fc04-read-"+crypto.randomUUID();sequence.current++;setKey(original);setReceipt(null);setBusy(true);setUnknown(true);setError("");
    const url=new URL(window.location.href);url.searchParams.set("reminderPreparation",original);window.history.replaceState(null,"",url);
    await client.requestMutation("boss.reminder.prepare",{client_request_id:original}).then(async()=>{if(current===epoch.current)await read(original);}).catch(failure=>{if(current===epoch.current){setError(failure.message+"；请核查原请求编号。");if([400,401,403,404,409,410,413,422].includes(failure.status))setUnknown(false);}});
    if(current===epoch.current)setBusy(false);
  }
  async function recover(){if(busy)return;const current=epoch.current;setBusy(true);setError("");await read(key).catch(failure=>{if(current===epoch.current)setError(failure.message);});if(current===epoch.current)setBusy(false);}
  return <section className="boss-panel boss-fc04-reminders" aria-label="当前提醒助手读取">
    <header className="boss-panel-head"><h2>当前提醒与规则准备</h2><span className="boss-tag boss-tag-amber">SIMULATED</span></header>
    <p>助手读取实际事件、有效规则及当前处理状态；读取不执行调度或本人决定。</p>
    <div className="boss-actions"><button type="button" className="boss-btn" disabled={busy||unknown} onClick={()=>void prepare()}>通过助手读取当前提醒与规则</button>{key&&<button type="button" className="boss-btn" disabled={busy} onClick={()=>void recover()}>读取原提醒准备结果</button>}</div>
    {key&&<p>原准备编号 {key} · {receipt?.request_state??(busy?"执行中":"结果待核查")}</p>}
    {unknown&&<p role="status">结果尚未确定，仅查询原请求编号。</p>}
    {receipt?.adoption_state==="CURRENT"&&receipt.preparation&&<p>实际工具已读取 {receipt.preparation.projection.events.length} 项当前事件；规则版本 {receipt.preparation.projection.rules.map(rule=>rule.version).join("、")||"尚未设置"}；运行 {receipt.run_id}。没有授予业务授权。</p>}
    {receipt?.adoption_state==="HISTORICAL_REQUIRES_REQUERY"&&<p role="status">当前规则、事件或处理状态已经变化，请核查当前投影后重新读取。</p>}
    {error&&<p role="alert" className="boss-status boss-status-error">{error}</p>}
  </section>;
}
