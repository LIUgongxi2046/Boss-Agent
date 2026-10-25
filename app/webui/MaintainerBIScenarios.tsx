import {useCallback,useEffect,useRef,useState} from "react";
import {useClient} from "@/providers/ClientProvider";

type Loaded={scenario_id:string;version:string;record_count:number;source_ids:string[]};
type Catalog={source_type:"SIMULATED";generator_version:string;seed:number;allowed_use:string;description:string;
  scenarios:Record<string,{purpose:string}>;loaded_scenarios:Loaded[]};
type LoadResult={client_request_id:string;scenario_id:string;version:string;source_ids:string[];source_versions:Record<string,string>;
  generator_version:string;seed:number;manifest_sha256:string;record_count:number;allowed_use:string;external_service_invoked:false};
type Receipt={client_request_id:string;outcome:"RECORDED"|"NOT_FOUND_IN_CURRENT_STORE";result:LoadResult|null};
export function MaintainerBIScenarios(){
  const {client,getToken,token}=useClient();
  const [catalog,setCatalog]=useState<Catalog|null>(null),[selected,setSelected]=useState(""),[result,setResult]=useState<LoadResult|null>(null);
  const [key,setKey]=useState(""),[receipt,setReceipt]=useState<Receipt|null>(null),[uncertain,setUncertain]=useState(false);
  const [busy,setBusy]=useState(false),[error,setError]=useState("");
  const epoch=useRef(0);
  const read=useCallback(async<T,>(path:string):Promise<T>=>{
    const response=await fetch(path,{headers:{Authorization:"Bearer "+getToken()},cache:"no-store"});
    if(response.status===401){window.dispatchEvent(new Event("boss-auth-expired"));throw new Error("身份已经失效，请重新认证");}
    const body=await response.json();if(!response.ok)throw new Error("HTTP "+response.status+" · "+body.error);return body as T;
  },[getToken]);
  const refresh=useCallback(async()=>{
    const current=epoch.current;
    const value=await read<Catalog>("/api/boss/ui/admin/bi-scenarios");
    if(current===epoch.current){setCatalog(value);setSelected(previous=>previous||Object.keys(value.scenarios)[0]||"");}
  },[read]);
  const readReceipt=useCallback(async(requestId:string)=>{
    const current=epoch.current;
    const value=await read<Receipt>("/api/boss/ui/admin/bi-scenario-receipt?"+new URLSearchParams({client_request_id:requestId}));
    if(current===epoch.current){setReceipt(value);setResult(value.result);setUncertain(value.outcome!=="RECORDED");}
    return value;
  },[read]);
  useEffect(()=>{
    const current=++epoch.current;setCatalog(null);setSelected("");setResult(null);setReceipt(null);setError("");setUncertain(false);setBusy(false);
    const original=new URLSearchParams(window.location.search).get("biLoadRequest")??"";setKey(original);
    void refresh().catch(failure=>{if(current===epoch.current)setError(failure.message);});
    if(original){setUncertain(true);void readReceipt(original).catch(failure=>{if(current===epoch.current)setError(failure.message);});}
    return()=>{epoch.current++;};
  },[token,refresh,readReceipt]);
  async function load(){
    if(!catalog||busy||uncertain||!selected)return;
    const current=epoch.current,requestId=crypto.randomUUID();setKey(requestId);setBusy(true);setError("");setResult(null);setReceipt(null);setUncertain(true);
    const address=new URL(window.location.href);address.searchParams.set("biLoadRequest",requestId);window.history.replaceState(window.history.state,"",address);
    const payload={client_request_id:requestId,mode:"SIMULATED",scenario_id:selected,generator_version:catalog.generator_version,seed:catalog.seed,
      expected_version:catalog.loaded_scenarios.find(row=>row.scenario_id===selected)?.version??"0"};
    await client.requestMutation<LoadResult>("boss.simulation.bi_scenario.load",payload).then(async value=>{
      if(current!==epoch.current)return;setResult(value);setReceipt({client_request_id:requestId,outcome:"RECORDED",result:value});setUncertain(false);await refresh().catch(failure=>{if(current===epoch.current)setError("载入已经记录，目录读取失败："+failure.message);});
    },failure=>{
      if(current!==epoch.current)return;setError(failure.message+"。原载入请求 "+requestId);
      if([400,401,403,404,409,410,413].includes(failure.status))setUncertain(false);
    });
    if(current===epoch.current)setBusy(false);
  }
  async function recover(){if(!key||busy)return;const current=epoch.current;setBusy(true);setError("");await readReceipt(key).then(async()=>refresh().catch(failure=>{if(current===epoch.current)setError("回执已经读取，目录读取失败："+failure.message);}),failure=>{if(current===epoch.current)setError(failure.message);});if(current===epoch.current)setBusy(false);}
  return <section className="boss-panel boss-bi-maintainer" aria-label="经营场景维护">
    <div className="boss-panel-head"><h2>经营边界资料</h2><small>A04 · SIMULATED</small></div>
    <p>{catalog?.description??"正在读取正式经营场景目录。"}</p>
    {error&&<p role="alert" className="boss-status boss-status-error">{error}</p>}
    <div className="boss-form-grid boss-bi-fields"><label>经营验证场景<select aria-label="经营验证场景" value={selected} disabled={busy||uncertain||!catalog} onChange={event=>{setSelected(event.target.value);setResult(null);}}>
      {Object.entries(catalog?.scenarios??{}).map(([identifier,definition])=><option key={identifier} value={identifier}>{identifier} · {definition.purpose}</option>)}</select></label>
      <label>当前场景版本<input aria-label="当前场景版本" readOnly value={catalog?.loaded_scenarios.find(row=>row.scenario_id===selected)?.version??"0"}/></label></div>
    <p>生成版本 {catalog?.generator_version??"未知"} · seed {catalog?.seed??"未知"} · 用途 {catalog?.allowed_use??"未知"}</p>
    <div className="boss-actions"><button className="boss-btn boss-btn-primary" disabled={busy||uncertain||!catalog||!selected} onClick={()=>void load()}>{busy?"正在处理":"载入经营场景"}</button>
      <button className="boss-btn" disabled={busy||!key} onClick={()=>void recover()}>读取原载入回执</button>
      <button className="boss-btn" disabled={busy} onClick={()=>void refresh().catch(failure=>setError(failure.message))}>刷新场景目录</button></div>
    <p>原载入请求 {key||"尚未提交"} · 回执 {receipt?.outcome??"尚未确认"}</p>
    {uncertain&&<p role="status">载入结果尚未确认，仅查询同一原请求回执。</p>}
    {result&&<div className="boss-workspace-item"><p>{result.scenario_id} · 版本 {result.version} · {result.record_count} 条记录</p>
      <p>来源 {result.source_ids.join("、")}</p><p>参数摘要 {result.manifest_sha256} · 外部调用 {String(result.external_service_invoked)}</p></div>}
    <ul>{catalog?.loaded_scenarios.map(row=><li key={row.scenario_id}>{row.scenario_id} · v{row.version} · {row.record_count} 条记录</li>)}</ul>
    <p>资料由正式本地生成器创建，仅用于程序行为验证；载入不产生本人业务授权。</p>
  </section>;
}
