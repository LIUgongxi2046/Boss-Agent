import {useCallback,useEffect,useRef,useState} from "react";
import {useClient} from "@/providers/ClientProvider";

type Catalog={definition:{generator_version:string;seed:number;allowed_use:string;description:string};business_clock:string;loaded:{date:string;timezone:string;version:string;source_id:string;source_version:string}[]};
type Receipt={client_request_id:string;outcome:string;result:{date:string;timezone:string;version:string;source_id:string;source_version:string;author_kind:string;allowed_use:string}|null;write_performed_by_lookup?:false};
export function MaintainerMorningCoverage(){
  const {client,getToken,token}=useClient();
  const [catalog,setCatalog]=useState<Catalog|null>(null),[date,setDate]=useState(""),[timezone,setTimezone]=useState("Asia/Shanghai");
  const [key,setKey]=useState(""),[receipt,setReceipt]=useState<Receipt|null>(null),[busy,setBusy]=useState(false),[uncertain,setUncertain]=useState(false),[error,setError]=useState("");
  const epoch=useRef(0);
  const read=useCallback(async<T,>(path:string):Promise<T>=>{
    const response=await fetch(path,{headers:{Authorization:"Bearer "+getToken()},cache:"no-store"});
    if(response.status===401||response.status===403){epoch.current++;setCatalog(null);setReceipt(null);if(response.status===401)window.dispatchEvent(new Event("boss-auth-expired"));throw new Error("当前身份无法读取覆盖资料");}
    const body=await response.json();if(!response.ok)throw new Error("HTTP "+response.status+" · "+body.error);return body as T;
  },[getToken]);
  const refresh=useCallback(async()=>{const current=epoch.current;const value=await read<Catalog>("/api/boss/ui/admin/morning-coverage");if(current===epoch.current){setCatalog(value);setDate(previous=>previous||value.business_clock.slice(0,10));}},[read]);
  const recover=useCallback(async(original:string)=>{
    const current=epoch.current,value=await read<Receipt>("/api/boss/ui/admin/morning-coverage-receipt?"+new URLSearchParams({client_request_id:original}));
    if(current===epoch.current){setReceipt(value);setUncertain(value.outcome!=="RECORDED");await refresh();}
  },[read,refresh]);
  useEffect(()=>{
    const current=++epoch.current,original=new URLSearchParams(window.location.search).get("morningCoverageRequest")??"";
    setCatalog(null);setReceipt(null);setKey(original);setUncertain(Boolean(original));setBusy(false);setDate("");setTimezone("Asia/Shanghai");setError("");
    void refresh().catch(failure=>{if(current===epoch.current)setError(failure.message);});
    if(original)void recover(original).catch(failure=>{if(current===epoch.current)setError(failure.message);});
    return()=>{epoch.current++;};
  },[token,refresh,recover]);
  async function load(){
    if(!catalog||busy||uncertain||!date||!timezone)return;
    const current=epoch.current,original="morning-coverage-"+crypto.randomUUID();setKey(original);setReceipt(null);setError("");setBusy(true);setUncertain(true);
    const address=new URL(window.location.href);address.searchParams.set("morningCoverageRequest",original);window.history.replaceState(window.history.state,"",address);
    await client.requestMutation<NonNullable<Receipt["result"]>>("boss.simulation.morning_coverage.load",{client_request_id:original,date,timezone,mode:"SIMULATED",generator_version:catalog.definition.generator_version,seed:catalog.definition.seed,
      expected_version:catalog.loaded.find(value=>value.date===date&&value.timezone===timezone)?.version??"0"}).then(async result=>{
      if(current===epoch.current){setReceipt({client_request_id:original,outcome:"RECORDED",result});setUncertain(false);await refresh();}
    },failure=>{if(current===epoch.current){setError(failure.message+"；原请求 "+original);if([400,401,403,404,409,410,413].includes(failure.status))setUncertain(false);}});
    if(current===epoch.current)setBusy(false);
  }
  return <section className="boss-panel boss-morning-view" aria-label="晨间覆盖维护"><header className="boss-panel-head"><h2>晨间资料覆盖</h2><small>SIMULATED · 程序行为验证</small></header>
    <p>{catalog?.definition.description??"正在读取覆盖资料定义"}</p>{error&&<p role="alert" className="boss-status boss-status-error">{error}</p>}
    <div className="boss-form-grid boss-morning-fields"><label>覆盖业务日期<input aria-label="覆盖业务日期" type="date" value={date} disabled={busy||uncertain} onChange={event=>setDate(event.target.value)}/></label>
      <label>覆盖 IANA 时区<input aria-label="覆盖 IANA 时区" value={timezone} disabled={busy||uncertain} onChange={event=>setTimezone(event.target.value)}/></label></div>
    <p>生成版本 {catalog?.definition.generator_version??"未知"} · 用途 {catalog?.definition.allowed_use??"未知"}</p>
    <div className="boss-actions"><button className="boss-btn boss-btn-primary" disabled={busy||uncertain||!catalog||!date||!timezone} onClick={()=>void load()}>载入晨间覆盖资料</button>
      <button className="boss-btn" disabled={busy||!key} onClick={()=>void recover(key).catch(failure=>setError(failure.message))}>读取原覆盖载入回执</button></div>
    <p>原覆盖请求 {key||"尚未提交"} · 回执 {receipt?.outcome??"未知"}</p>{uncertain&&<p role="status">结果尚未确认，仅查询同一原编号。</p>}
    {receipt?.result&&<p>{receipt.result.date} · {receipt.result.timezone} · 版本 {receipt.result.version} · 来源 {receipt.result.source_id} / v{receipt.result.source_version} · 作者 {receipt.result.author_kind}</p>}
    {catalog?.loaded.map(value=><p key={value.date+value.timezone}>{value.date} · {value.timezone} · 覆盖版本 {value.version} · 来源 {value.source_id} / v{value.source_version}</p>)}
  </section>;
}
