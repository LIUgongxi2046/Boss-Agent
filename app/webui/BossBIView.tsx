import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useClient } from "@/providers/ClientProvider";

type ScopeValue = string | string[] | null | Record<string, string | string[] | null>;
type Scope = Record<string, ScopeValue>;
type Dimensions = { source_type: string; available_dimensions: Record<string,string[]>; periods: Record<string,string[]>;
  metric_definitions: {metric_id:string;definition_version:string}[]; source_id:string;source_version:string;coverage_state:string;missing_fields:string[] };
type MetricValue = {metric_id:string;period_scope:string;value:string|null;unit:string;formula:string;definition_version:string;display_rounding:string;scope_description:string};
type Query = {query_id:string;context_snapshot:Scope;parent_query_id:string|null;overridden_fields:string[];source_type:string;queried_at:string;
  values:MetricValue[];detail_refs:string[];sources:{source_id:string;version:string;source_type:string;coverage:string;business_as_of:string;source_updated_at:string;quality_state:string}[];
  coverage:{state:string;periods:Record<string,{record_count:number;region_ids:string[];period_start:string;period_end:string}>;missing_regions:string[];delayed_regions:string[]|null;unsynchronized_regions:string[]|null};
  comparison:{state:string;reasons:string[]};missing_fields:string[];unexplained_causes:string[]};
type Read = {adoption_state:string;result:Query};
type Receipt = {client_request_id:string;request_state:string;run_id:string|null;receipt:{outcome:string;query:Read|null}|null;cancel_requested?:boolean};
type History = {requests:{client_request_id:string;created_at:string;run_id:string|null}[]};
type Evidence = {query_id:string;result:{definition_version:string;original_records:{record_id:string;version:string;content:unknown}[];conflicts:string[];missing_fields:string[]}};
const LABELS:Record<string,string>={sales_quantity:"销量",revenue:"营业收入",cost:"成本",gross_profit:"毛利",gross_margin:"毛利率",gross_profit_per_tonne:"单吨毛利"};
const FIELDS:[string,string][]=[["region_id","地区"],["region_ids","地区范围"],["product_ids","产品范围"],["legal_entity_id","法人"],
  ["currency","币种"],["quantity_unit","数量单位"],["trade_scope","交易范围"],["definition_version","定义版本"],
  ["business_basis","业务口径"],["settlement_state","结算状态"],["target_version","目标版本"],["customer_id","客户"],
  ["ownership_type","归属类型"],["asset_owner_id","资产归属"],["cost_owner_id","成本归属"]];
const OPTIONAL=new Set(["target_version","customer_id","ownership_type","asset_owner_id","cost_owner_id"]);
const ARRAYS=new Set(["region_ids","product_ids","metric_ids"]);
const DATES:[string,string][]=[["period_start","当前期间开始"],["period_end","当前期间结束"],["comparison_start","比较期间开始"],["comparison_end","比较期间结束"]];
function businessScope(snapshot:Scope):Scope{return Object.fromEntries(Object.entries(snapshot).filter(([field])=>!["envelope","query_mode","question","parent_query_id"].includes(field)));}
function Panel({title,children}:{title:string;children:ReactNode}){return <section className="boss-panel"><header className="boss-panel-head"><h2>{title}</h2></header>{children}</section>;}
function valueText(value:ScopeValue|undefined){return Array.isArray(value)?value.join("、"):value===null?"未知":typeof value==="object"?JSON.stringify(value):value??"未提供";}
class BIReadError extends Error {
  constructor(readonly status:number,message:string){super(message);this.name="BIReadError";}
}

export function BossBIView({getToken,onSource}:{getToken:()=>string;onSource:(id:string)=>void}){
  const {client}=useClient();
  const [dimensions,setDimensions]=useState<Dimensions|null>(null),[scope,setScope]=useState<Scope>({});
  const [question,setQuestion]=useState("查询当前经营指标及变化"),[mode,setMode]=useState<"NEW"|"FOLLOW_UP">("NEW");
  const [read,setRead]=useState<Read|null>(null),[receipt,setReceipt]=useState<Receipt|null>(null),[history,setHistory]=useState<History>({requests:[]});
  const [changed,setChanged]=useState<Set<string>>(new Set()),[busy,setBusy]=useState(false),[error,setError]=useState("");
  const [sourceError,setSourceError]=useState(""),[historyError,setHistoryError]=useState(""),[receiptError,setReceiptError]=useState("");
  const [historyLoading,setHistoryLoading]=useState(true),[receiptLoading,setReceiptLoading]=useState(false),[requestKey,setRequestKey]=useState("");
  const [accessDenied,setAccessDenied]=useState(false);
  const [evidence,setEvidence]=useState<Evidence|null>(null),[reading,setReading]=useState(false),[dirty,setDirty]=useState(false);
  const generation=useRef(0),activeRequest=useRef(""),readId=useRef<string|null>(null),mounted=useRef(true);
  const identityEpoch=useRef(0),denied=useRef(false),restoredScope=useRef(false),receiptSequence=useRef(0),historySequence=useRef(0);
  readId.current=read?.result.query_id??null;
  const clearProtected=useCallback(()=>{
    setDimensions(null);setScope({});setRead(null);setReceipt(null);setHistory({requests:[]});setEvidence(null);
    setRequestKey("");activeRequest.current="";readId.current=null;restoredScope.current=false;
    setQuestion("查询当前经营指标及变化");setMode("NEW");
    setChanged(new Set());setDirty(false);setBusy(false);setReading(false);setReceiptLoading(false);setHistoryLoading(false);
    setSourceError("");setHistoryError("");setReceiptError("");generation.current++;receiptSequence.current++;historySequence.current++;
  },[]);
  const fetchJSON=useCallback(async <T,>(path:string,signal?:AbortSignal):Promise<T>=>{
    const epoch=identityEpoch.current;
    if(denied.current)throw new DOMException("当前读取范围已经失效","AbortError");
    const response=await fetch(path,{headers:{Authorization:"Bearer "+getToken()},signal});
    if(epoch!==identityEpoch.current||denied.current||signal?.aborted)throw new DOMException("当前读取已经终止","AbortError");
    // 身份失效后，其他未完成读取的成功响应也不能恢复受保护内容。
    if(response.status===401||response.status===403){
      denied.current=true;setAccessDenied(true);clearProtected();
      const message=response.status===401?"身份已经失效，请重新认证":"当前身份或数据范围无权访问";
      setError(message);if(response.status===401)window.dispatchEvent(new Event("boss-auth-expired"));
      throw new BIReadError(response.status,message);
    }
    const body=await response.json();
    if(epoch!==identityEpoch.current||denied.current||signal?.aborted)throw new DOMException("当前读取已经终止","AbortError");
    if(!response.ok)throw new BIReadError(response.status,typeof body.error==="string"?body.error:"当前经营请求被拒绝");
    return body as T;
  },[getToken,clearProtected]);
  const applyReceipt=useCallback((value:Receipt)=>{
    if(denied.current)return;
    setReceipt(value);activeRequest.current=value.client_request_id;setRequestKey(value.client_request_id);
    const result=value.receipt?.query;
    restoredScope.current=Boolean(result);
    setRead(result??null);setEvidence(null);setReading(false);setDirty(false);setChanged(new Set());
    if(result){setScope(businessScope(result.result.context_snapshot));setQuestion(String(result.result.context_snapshot.question??"继续查询当前范围"));setMode(result.adoption_state==="HISTORICAL_REQUIRES_REQUERY"?"NEW":"FOLLOW_UP");}
  },[]);
  const loadReceipt=useCallback(async(key:string,signal?:AbortSignal)=>{
    const epoch=identityEpoch.current,sequence=++receiptSequence.current;
    const current=()=>mounted.current&&!denied.current&&epoch===identityEpoch.current&&sequence===receiptSequence.current&&!signal?.aborted;
    activeRequest.current=key;setRequestKey(key);setReceiptLoading(true);setReceiptError("");setReceipt(null);setRead(null);setEvidence(null);
    await fetchJSON<Receipt>("/api/boss/ui/bi/receipt?"+new URLSearchParams({client_request_id:key}),signal).then(value=>{
      if(current())applyReceipt(value);
    },failure=>{if(current())setReceiptError(failure.message);});
    if(current())setReceiptLoading(false);
  },[fetchJSON,applyReceipt]);
  useEffect(()=>{
    const abort=new AbortController(),epoch=++identityEpoch.current;
    mounted.current=true;denied.current=false;setAccessDenied(false);clearProtected();setError("");setHistoryLoading(true);
    const current=()=>mounted.current&&!denied.current&&epoch===identityEpoch.current&&!abort.signal.aborted;
    const historyRequest=++historySequence.current;
    const requested=new URLSearchParams(window.location.search).get("biRequest");
    void fetchJSON<Dimensions>("/api/boss/ui/bi/dimensions",abort.signal).then(data=>{
      if(!current())return;setDimensions(data);
      if(restoredScope.current)return;
      const available=data.available_dimensions,next:Scope={};
      for(const [field] of FIELDS){const dimension=field==="region_ids"?"region_id":field==="product_ids"?"product_id":field;
        next[field]=OPTIONAL.has(field)?null:ARRAYS.has(field)?available[dimension]??[]:available[dimension]?.[0]??"";}
      next.metric_ids=data.metric_definitions.map(item=>item.metric_id);
      next.definition_version=data.metric_definitions[0]?.definition_version??"";
      next.period_start=data.periods.CURRENT[0];next.period_end=data.periods.CURRENT[1];next.comparison_start=data.periods.BASE[0];next.comparison_end=data.periods.BASE[1];
      setScope(next);
    },failure=>{if(current())setSourceError(failure.message);});
    void fetchJSON<History>("/api/boss/ui/bi/history",abort.signal).then(saved=>{
      if(!current()||historyRequest!==historySequence.current)return;setHistory(saved);setHistoryLoading(false);
      const latest=saved.requests[0]?.client_request_id;
      if(!requested&&!activeRequest.current&&latest)void loadReceipt(latest,abort.signal);
    },failure=>{if(current()&&historyRequest===historySequence.current){setHistoryError(failure.message);setHistoryLoading(false);}});
    if(requested)void loadReceipt(requested,abort.signal);
    return()=>{mounted.current=false;identityEpoch.current++;generation.current++;receiptSequence.current++;abort.abort();};
  },[fetchJSON,loadReceipt,clearProtected]);
  function edit(field:string,value:ScopeValue){setScope(current=>({...current,[field]:value}));setChanged(current=>new Set([...current,field]));setDirty(true);setEvidence(null);generation.current++;}
  function remember(key:string){const address=new URL(window.location.href);address.searchParams.set("biRequest",key);window.history.replaceState(null,"",address);}
  async function submit(){
    if(busy||!dimensions||denied.current||receiptLoading)return;
    const key=crypto.randomUUID(),version=++generation.current,epoch=identityEpoch.current;activeRequest.current=key;setRequestKey(key);remember(key);
    receiptSequence.current++;setReceiptLoading(false);setReceiptError("");
    setBusy(true);setError("");setEvidence(null);setRead(null);setReceipt(null);
    const previous=read;
    const payload=mode==="FOLLOW_UP"&&previous?{client_request_id:key,question,parent_query_id:previous.result.query_id,
      overrides:Object.fromEntries([...changed].map(field=>[field,scope[field]]))}:{client_request_id:key,question,scope};
    await client.requestMutation<Receipt>(mode==="FOLLOW_UP"&&previous?"boss.bi.follow_up":"boss.bi.query",payload).then(async value=>{
      if(mounted.current&&!denied.current&&identityEpoch.current===epoch&&generation.current===version)applyReceipt(value);
      if(mounted.current&&!denied.current&&identityEpoch.current===epoch){
        const historyRequest=++historySequence.current;
        const current=()=>mounted.current&&!denied.current&&identityEpoch.current===epoch&&historyRequest===historySequence.current;
        await fetchJSON<History>("/api/boss/ui/bi/history").then(saved=>{if(current()){setHistory(saved);setHistoryError("");setHistoryLoading(false);}},failure=>{if(current()){setHistoryError(failure.message);setHistoryLoading(false);}});
      }
    },failure=>{if(mounted.current&&!denied.current&&identityEpoch.current===epoch)setError(failure.message+"。请读取原请求结果，编号 "+key);});
    if(mounted.current&&!denied.current&&identityEpoch.current===epoch)setBusy(false);
  }
  async function restore(key:string){if(denied.current)return;const epoch=identityEpoch.current;setError("");setBusy(true);generation.current++;remember(key);await loadReceipt(key);if(mounted.current&&!denied.current&&identityEpoch.current===epoch)setBusy(false);}
  async function cancel(){if(!activeRequest.current||denied.current)return;const epoch=identityEpoch.current;
    const current=()=>mounted.current&&!denied.current&&identityEpoch.current===epoch;
    await client.requestMutation<Receipt>("boss.bi.cancel",{client_request_id:activeRequest.current}).then(value=>{if(current()){setReceipt(value);setError("取消已请求，请读取原请求结果确认终态。");}},failure=>{if(current())setError(failure.message);});}
  async function readEvidence(){
    if(!read||reading||dirty||denied.current||read.adoption_state==="HISTORICAL_REQUIRES_REQUERY")return;const queryId=read.result.query_id,version=generation.current;setReading(true);setEvidence(null);setError("");
    await fetchJSON<Evidence>("/api/boss/ui/metrics-evidence?"+new URLSearchParams({query_id:queryId})).then(value=>{
      if(mounted.current&&readId.current===queryId&&generation.current===version)setEvidence(value);
    },failure=>{if(mounted.current&&!denied.current&&generation.current===version)setError(failure.message);});if(mounted.current&&!denied.current&&generation.current===version)setReading(false);
  }
  const visible=dirty?null:read?.result, comparison=scope.comparison_scope as Record<string,string|string[]|null>|undefined;
  const formDisabled=busy||!dimensions||accessDenied||receiptLoading;
  const options=(field:string)=>dimensions?.available_dimensions[field==="product_ids"?"product_id":field==="region_ids"?"region_id":field]??[];
  function fieldInput(field:string,label:string,current:ScopeValue|undefined,onChange:(value:ScopeValue)=>void,prefix="current"){
    const id=prefix+"-"+field;
    const choices=dimensions?options(field):Array.isArray(current)?current:[];
    if(ARRAYS.has(field))return <label key={id}>{label}<select aria-label={prefix==="compare"?"比较条件"+label:label} multiple value={Array.isArray(current)?current:[]} disabled={formDisabled}
      onChange={event=>onChange([...event.target.selectedOptions].map(option=>option.value))}>{choices.map(value=><option key={value} value={value}>{value}</option>)}</select></label>;
    return <label key={id}>{label}<input aria-label={prefix==="compare"?"比较条件"+label:label} list={id+"-options"} value={typeof current==="string"?current:""} disabled={formDisabled}
      placeholder={OPTIONAL.has(field)?"未知，尚未提供":"请输入明确条件"} onChange={event=>onChange(event.target.value===""&&OPTIONAL.has(field)?null:event.target.value)}/>
      <datalist id={id+"-options"}>{options(field).map(value=><option key={value} value={value}/>)}</datalist></label>;
  }
  return <div className="boss-columns boss-bi-view"><div className="boss-column">
    <Panel title="经营指标查询">
      <p>当前资料属性 {dimensions?.source_type??(accessDenied?"无权访问":sourceError?"不可采用":"正在读取")} · 已知覆盖 {dimensions?.coverage_state??"未知"}</p>
      {sourceError&&<p role="alert" className="boss-status boss-status-warn">当前来源：{sourceError}</p>}
      {error&&<p role="alert" className="boss-status boss-status-warn">{error}</p>}
      <form onSubmit={event=>{event.preventDefault();void submit();}}>
        <div className="boss-form-grid boss-bi-fields"><label>查询方式<select aria-label="查询方式" value={mode} disabled={formDisabled} onChange={event=>{setMode(event.target.value as "NEW"|"FOLLOW_UP");setDirty(true);setEvidence(null);generation.current++;}}>
          <option value="NEW">完整条件查询</option><option value="FOLLOW_UP" disabled={!read||read.adoption_state==="HISTORICAL_REQUIRES_REQUERY"}>继承当前查询继续追问</option></select></label>
          <label>经营问题<textarea aria-label="经营问题" required value={question} disabled={formDisabled} onChange={event=>{setQuestion(event.target.value);setDirty(true);setEvidence(null);generation.current++;}}/></label>
          <label>指标范围<select aria-label="指标范围" multiple required value={Array.isArray(scope.metric_ids)?scope.metric_ids:[]} disabled={formDisabled} onChange={event=>edit("metric_ids",[...event.target.selectedOptions].map(option=>option.value))}>
            {(dimensions?dimensions.metric_definitions.map(item=>item.metric_id):read?.result.context_snapshot.metric_ids as string[]??[]).map(metric=><option key={metric} value={metric}>{LABELS[metric]??metric}</option>)}</select></label>
          {FIELDS.map(([field,label])=>fieldInput(field,label,scope[field],value=>edit(field,value)))}
          {DATES.map(([field,label])=><label key={field}>{label}<input type="date" aria-label={label} required value={String(scope[field]??"")} disabled={formDisabled} onChange={event=>edit(field,event.target.value)}/></label>)}
        </div>
        <details className="boss-workspace-item"><summary>比较期间的业务条件</summary><p>未单独指定的条件继承当前业务范围。</p>
          {FIELDS.map(([field,label])=><div key={field} className="boss-bi-compare-field"><label><input type="checkbox" checked={comparison!==undefined&&field in comparison} disabled={formDisabled}
            onChange={event=>{const next={...comparison};if(event.target.checked)next[field]=scope[field] as string|string[]|null;else delete next[field];edit("comparison_scope",next);}}/>单独指定{label}</label>
            {comparison&&field in comparison&&fieldInput(field,label,comparison[field],value=>edit("comparison_scope",{...comparison,[field]:value} as ScopeValue),"compare")}</div>)}
        </details>
        {mode==="FOLLOW_UP"&&read&&<div className="boss-workspace-item"><p>继承查询 {read.result.query_id}</p><p>明确覆盖：{[...changed].map(field=>FIELDS.find(item=>item[0]===field)?.[1]??DATES.find(item=>item[0]===field)?.[1]??field).join("、")||"尚未指定"}</p>
          <dl className="boss-kv">{Object.entries(businessScope(read.result.context_snapshot)).filter(([field])=>!changed.has(field)).map(([field,value])=><div key={field}><dt>{FIELDS.find(item=>item[0]===field)?.[1]??DATES.find(item=>item[0]===field)?.[1]??field}</dt><dd>{valueText(value)}</dd></div>)}</dl></div>}
        <div className="boss-actions"><button className="boss-button boss-button-primary" type="submit" disabled={formDisabled||!question.trim()||mode==="FOLLOW_UP"&&!read}>{busy?"正在查询":"提交查询"}</button>
          <button className="boss-button" type="button" disabled={!busy} onClick={()=>void cancel()}>取消当前查询</button></div>
      </form>
    </Panel>
    <Panel title="经营对比">
      {dirty&&<p role="status">条件已经编辑，请提交查询获取对应结果。</p>}
      {visible?<><p>{read?.adoption_state} · 查询 {visible.query_id} · {visible.queried_at}</p><div className="boss-table-scroll"><table className="boss-table boss-bi-table"><thead><tr><th>指标</th><th>基准期</th><th>当前期</th><th>单位</th><th>变化量</th></tr></thead>
        <tbody>{(visible.context_snapshot.metric_ids as string[]).map(metric=>{const find=(period:string)=>visible.values.find(value=>value.metric_id===metric&&value.period_scope===period);const base=find("BASE"),current=find("CURRENT"),change=find("CHANGE");return <tr key={metric}><th scope="row">{LABELS[metric]??metric}</th><td>{base?.value??"未定义"}</td><td>{current?.value??"未定义"}</td><td>{current?.unit}</td><td>{change?.value??"未定义"} {change?.unit}</td></tr>;})}</tbody></table></div>
        <p>比较状态 {visible.comparison.state} · {visible.comparison.reasons.join("、")}</p></>:<p>当前条件尚未取得查询结果。</p>}
      {read?.adoption_state==="HISTORICAL_REQUIRES_REQUERY"&&<p role="status">历史查询需要重新查询，当前原始依据不可采用。历史条件与原始数值保留供查阅。</p>}
    </Panel>
    {visible&&<Panel title="原始精度与计算公式">{visible.values.map(value=><details className="boss-workspace-item" key={value.metric_id+value.period_scope}><summary>{LABELS[value.metric_id]??value.metric_id} · {value.period_scope}</summary><p>原始值 {value.value??"未定义"} · {value.unit} · 定义版本 {value.definition_version}</p><p>{value.formula}</p><p>{value.display_rounding}</p><p>{value.scope_description}</p></details>)}</Panel>}
    <Panel title="本次查询原始依据"><button className="boss-button" disabled={!visible||reading||read?.adoption_state==="HISTORICAL_REQUIRES_REQUERY"} onClick={()=>void readEvidence()}>{reading?"正在读取本次依据":"读取本次查询原始依据"}</button>
      {evidence&&<><p>查询 {evidence.query_id} · 定义版本 {evidence.result.definition_version}</p>{evidence.result.original_records.map(record=><details key={record.record_id} className="boss-workspace-item"><summary>{record.record_id} · v{record.version}</summary><pre>{JSON.stringify(record.content,null,2)}</pre></details>)}{evidence.result.conflicts.map(text=><p key={text}>{text}</p>)}</>}
    </Panel>
  </div><div className="boss-column">
    <Panel title="原请求与查询恢复"><p>刷新、重新登录和连接中断后，可以读取保存的原请求。</p><p>当前请求 {receipt?.client_request_id??(requestKey||"尚未提交")}</p><p>运行状态 {receiptLoading?"正在读取":receipt?.request_state??(requestKey?"尚未确认":"尚未提交")} · 查询回执 {receipt?.receipt?.outcome??"未知"}</p>
      {receiptError&&<p role="alert" className="boss-status boss-status-warn">原请求读取失败：{receiptError}</p>}
      <button className="boss-button" disabled={!requestKey||receiptLoading||accessDenied} onClick={()=>void restore(requestKey)}>读取原请求结果</button>
      {historyLoading&&<p role="status">正在读取历史请求。</p>}
      {historyError&&<p role="alert" className="boss-status boss-status-warn">历史请求读取失败：{historyError}</p>}
      {!historyLoading&&!historyError&&!accessDenied&&history.requests.length===0&&<p>尚无历史请求。</p>}
      <ul className="boss-bi-history">{history.requests.map(item=><li key={item.client_request_id}><button className="boss-button" disabled={busy||accessDenied} onClick={()=>void restore(item.client_request_id)}>{item.created_at} · {item.client_request_id}</button></li>)}</ul>
    </Panel>
    <Panel title="指标来源与覆盖">{visible?<><p>覆盖 {visible.coverage.state} · 缺少地区 {visible.coverage.missing_regions.join("、")||"当前选择范围没有额外缺少地区"}</p>
      <p>延迟地区 {visible.coverage.delayed_regions?.join("、")??"未知"} · 未同步地区 {visible.coverage.unsynchronized_regions?.join("、")??"未知"}</p>
      {Object.entries(visible.coverage.periods).map(([period,coverage])=><p key={period}>{period} · {coverage.period_start} 至 {coverage.period_end} · {coverage.record_count} 条明细 · {coverage.region_ids.join("、")}</p>)}
      {visible.sources.map(source=><div className="boss-workspace-item" key={source.source_id}><p>{source.source_id} · v{source.version} · {source.source_type} · {source.quality_state}</p><p>覆盖 {source.coverage} · 业务截至 {source.business_as_of} · 来源更新 {source.source_updated_at}</p><button className="boss-button" disabled={accessDenied||read?.adoption_state==="HISTORICAL_REQUIRES_REQUERY"} onClick={()=>onSource(source.source_id)}>打开当前来源原文</button></div>)}</>:<p>来源 {dimensions?.source_id??(sourceError?"当前不可采用":"正在读取")} · v{dimensions?.source_version??"未知"}</p>}</Panel>
    <Panel title="可解释性与缺口">{(visible?[...visible.unexplained_causes,...visible.missing_fields]:dimensions?.missing_fields??[]).map((text,index)=><p key={index} className="boss-status boss-status-warn">{text}</p>)}<p>查询与讨论不产生交办、批准或发送授权。</p></Panel>
  </div></div>;
}
