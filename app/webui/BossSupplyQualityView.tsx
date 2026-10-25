import {useEffect, useRef, useState, type FormEvent} from "react";
import {useClient} from "@/providers/ClientProvider";
import {BossSupplyQualityPanel, type SupplyQualityEditor, type SupplyQualityProjection, type SupplyQualityReceipt} from "./BossSupplyQualityPanel";

type Props={interfaceId:"SI09"|"SI10";onOpenSource:(sourceId:string)=>void;onOpenTask:(taskId:string)=>void;
  editor:SupplyQualityEditor;onEditorChange:(changes:Partial<SupplyQualityEditor>)=>void};

type FilterResult={source_type:"SIMULATED";access:"BOSS_ONLY";interface_id:string;read_at:string;
  business_actions_performed:false;external_retrieval_performed:false;
  records:{record_id:string;entity_type:string;version:string|null;content_state:string;data:unknown;
    source_refs:{source_id:string;current_version:string|null;status:string}[]}[]};
const FILTER_FIELDS=[
  ["material_id","原料编号"],["product_ids","产品编号"],["legal_entity_id","法人编号"],
  ["asset_owner_id","资产归属编号"],["cost_owner_id","成本归属编号"],["batch_id","批次编号"],
  ["customer_id","客户编号"],["currency","币种"],["period_start","期间开始"],["period_end","期间结束"],
] as const;

function SupplyQualityFilters({interfaceId,onOpenSource}:Pick<Props,"interfaceId"|"onOpenSource">){
  const {client,getToken,token}=useClient();
  const [fields,setFields]=useState<Record<string,string>>({});
  const [result,setResult]=useState<FilterResult|null>(null);
  const [error,setError]=useState("");
  const [loading,setLoading]=useState(false);
  const active=useRef<AbortController|null>(null);
  useEffect(()=>{active.current?.abort();setFields({});setResult(null);setError("");setLoading(false);
    return ()=>active.current?.abort();},[client,token,interfaceId]);
  async function query(event:FormEvent){
    event.preventDefault();active.current?.abort();
    const abort=new AbortController();active.current=abort;
    setResult(null);setError("");setLoading(true);
    const parameters=new URLSearchParams({interface_id:interfaceId});
    for(const [name,text] of Object.entries(fields))if(text.trim())parameters.set(name,text.trim());
    if(Boolean(fields.period_start)!==Boolean(fields.period_end)){setLoading(false);setError("期间需要完整起止日期。");return;}
    const currentToken=getToken();
    if(!currentToken){setLoading(false);setError("当前身份令牌失效，请重新登录。");return;}
    await fetch("/api/boss/ui/simulation-query?"+parameters,{headers:{Authorization:"Bearer "+currentToken},cache:"no-store",signal:abort.signal}).then(async response=>{
      if(!response.ok)throw new Error("筛选资料读取失败（HTTP "+response.status+"）");
      const value=await response.json() as FilterResult;
      if(value.interface_id!==interfaceId||value.source_type!=="SIMULATED"||value.access!=="BOSS_ONLY"||value.business_actions_performed!==false||value.external_retrieval_performed!==false)throw new Error("筛选资料与当前范围不符。");
      return value;
    }).then(value=>{if(!abort.signal.aborted){setResult(value);setLoading(false);}},(reason:unknown)=>{if(!abort.signal.aborted){setError(reason instanceof Error?reason.message:String(reason));setLoading(false);}});
  }
  return <section className="boss-panel" aria-label="采购品质资料范围查询">
    <h2>查询当前资料范围</h2>
    <form onSubmit={event=>void query(event)}><fieldset disabled={loading}>
      <legend>使用当前本人权限查询</legend>
      {FILTER_FIELDS.map(([name,label])=><label className="boss-field" key={name}>{label}<input aria-label={label} type={name.startsWith("period_")?"date":"text"} maxLength={128} value={fields[name]??""} onChange={event=>{setFields(current=>({...current,[name]:event.target.value}));setResult(null);}}/></label>)}
      <button type="submit" className="boss-btn boss-btn-primary">查询当前范围资料</button>
    </fieldset></form>
    <p className="boss-helper">期间按本人业务时区选择完整报告；跨越期间边界的金额不进行分摊。筛选结果为当前原始记录，下方库存与协调区域保留完整来源计算。</p>
    {loading&&<p role="status">正在查询当前范围资料</p>}{error&&<p role="alert">{error}</p>}
    {result&&<section aria-label="当前筛选结果"><p role="status">当前范围共 {result.records.length} 条记录 · SIMULATED · {result.read_at}</p>
      {result.records.map(record=><details key={record.entity_type+":"+record.record_id}><summary>{record.entity_type} · {record.record_id} · v{record.version??"未知"} · {record.content_state}</summary>
        {record.data===null?<p>当前正文需要核查来源。</p>:<pre>{JSON.stringify(record.data,null,2)}</pre>}
        {record.source_refs.map(source=><p key={source.source_id}>{source.source_id} · v{source.current_version??"未知"} · {source.status} <button type="button" className="boss-btn" onClick={()=>onOpenSource(source.source_id)}>打开筛选记录来源</button></p>)}
      </details>)}
    </section>}
  </section>;
}

export function BossSupplyQualityView({interfaceId,onOpenSource,onOpenTask,editor,onEditorChange}:Props){
  const {client,getToken,token}=useClient();
  const [data,setData]=useState<SupplyQualityProjection|null>(null);
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState("");
  const [revision,setRevision]=useState(0);
  const reload=()=>setRevision(current=>current+1);
  useEffect(()=>{
    const abort=new AbortController();
    const token=getToken();
    setData(null);setError("");
    if(!token){setError("当前身份令牌失效，请重新登录。");return;}
    setLoading(true);
    void fetch("/api/boss/ui/supply-quality?interface_id="+interfaceId,{headers:{Authorization:"Bearer "+token},cache:"no-store",signal:abort.signal}).then(async response=>{
      if(!response.ok)throw new Error("业务资料读取失败（HTTP "+response.status+"）");
      const result=await response.json() as SupplyQualityProjection;
      if(result.interface_id!==interfaceId||result.source_type!=="SIMULATED"||result.external_service_invoked!==false||result.purchase_executed!==false||result.quality_release_executed!==false)throw new Error("业务资料范围与当前页面不符。");
      return result;
    }).then(result=>{if(abort.signal.aborted)return;setData(result);setLoading(false);},(error:unknown)=>{
      if(abort.signal.aborted)return;setError(error instanceof Error?error.message:String(error));setLoading(false);
    });
    return ()=>abort.abort();
  },[interfaceId,getToken,revision,client,token]);
  async function command(action:string,payload:Record<string,unknown>){
    if(!client)throw new Error("当前认证通道尚未连接。");
    return client.requestMutation<unknown>(action,payload);
  }
  async function receipt(action:string,key:string){
    const token=getToken();
    if(!token)throw new Error("当前身份令牌失效，请重新登录。");
    const parameters=new URLSearchParams({action,client_request_id:key});
    const response=await fetch("/api/boss/ui/supply-quality-receipt?"+parameters.toString(),{headers:{Authorization:"Bearer "+token},cache:"no-store"});
    if(!response.ok)throw new Error("原请求回执读取失败（HTTP "+response.status+"）");
    return response.json() as Promise<SupplyQualityReceipt>;
  }
  return <><SupplyQualityFilters interfaceId={interfaceId} onOpenSource={onOpenSource}/><BossSupplyQualityPanel key={interfaceId} data={data} loading={loading} error={error} onReload={reload} onOpenSource={onOpenSource} onOpenTask={onOpenTask} onCommand={command} onReceipt={receipt} editor={editor} onEditorChange={onEditorChange}/></>;
}
