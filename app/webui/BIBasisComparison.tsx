import {useEffect,useRef,useState} from "react";
import type {Read,Evidence,Scope} from "./BossBIView";

type Request=<T>(path:string,signal?:AbortSignal)=>Promise<T>;
type Entry={id:string;read:Read|null;evidence:Evidence|null;error:string};
const LABELS:Record<string,string>={sales_quantity:"销量",revenue:"营业收入",cost:"成本",gross_profit:"毛利",gross_margin:"毛利率",gross_profit_per_tonne:"单吨毛利"};
function comparable(scope:Scope){
  const excluded=new Set(["question","envelope","parent_query_id","source_ids","business_basis","query_mode"]);
  return JSON.stringify(Object.fromEntries(Object.entries(scope).filter(([field])=>!excluded.has(field)).sort(([first],[second])=>first.localeCompare(second)).map(([field,value])=>[field,Array.isArray(value)?[...value].sort():value])));
}
function documentBody(value:unknown):Record<string,unknown>|null{return value!==null&&typeof value==="object"&&!Array.isArray(value)?value as Record<string,unknown>:null;}

export function BIBasisComparison({current,request,onSource,reviewKey}:{current:Read|null;request:Request;onSource:(identifier:string)=>void;reviewKey:string}){
  const [ids,setIds]=useState<string[]>(()=>[...new Set(new URLSearchParams(window.location.search).getAll("biCompare"))].slice(0,2));
  const [entries,setEntries]=useState<Entry[]>([]),[loading,setLoading]=useState(false),[refresh,setRefresh]=useState(0);
  const epoch=useRef(0),key=JSON.stringify(ids);
  useEffect(()=>{
    const abort=new AbortController(),version=++epoch.current;setEntries([]);setLoading(ids.length>0);
    void Promise.all(ids.map(async id=>{
      let read:Read|null=null;
      try{
        read=await request<Read>("/api/boss/ui/bi/query?"+new URLSearchParams({query_id:id,historical:"true"}),abort.signal);
        const evidence=read.adoption_state==="HISTORICAL_REQUIRES_REQUERY"?null:await request<Evidence>("/api/boss/ui/metrics-evidence?"+new URLSearchParams({query_id:id}),abort.signal);
        return {id,read,evidence,error:""};
      }catch(failure){return {id,read,evidence:null,error:failure instanceof Error?failure.message:String(failure)};}
    })).then(values=>{if(!abort.signal.aborted&&version===epoch.current){setEntries(values);setLoading(false);}});
    return()=>{epoch.current++;abort.abort();};
  },[key,request,refresh,reviewKey]);
  function choose(next:string[]){
    const address=new URL(window.location.href);address.searchParams.delete("biCompare");for(const identifier of next)address.searchParams.append("biCompare",identifier);
    window.history.replaceState(window.history.state,"",address);setIds(next);
  }
  const actual=entries.flatMap(entry=>entry.read?[entry.read]:[]);
  const sameScope=actual.length===2&&comparable(actual[0].result.context_snapshot)===comparable(actual[1].result.context_snapshot);
  return <section className="boss-panel boss-bi-comparison" aria-label="不同口径并列">
    <div className="boss-panel-head"><h2>不同口径并列</h2></div>
    <p>每种口径使用各自正式查询和来源，保持原始值与当前采用状态。</p>
    <div className="boss-actions"><button className="boss-button" disabled={!current||ids.includes(current.result.query_id)||ids.length>=2} onClick={()=>{if(current)choose([...ids,current.result.query_id]);}}>保留本次口径</button>
      <button className="boss-button" disabled={!ids.length||loading} onClick={()=>setRefresh(value=>value+1)}>重读并列查询</button></div>
    {loading&&<p role="status">正在读取所选查询与各自来源。</p>}
    {actual.length===2&&<p role="status">{sameScope?"期间、指标及业务范围相同，分别保留双方口径。":"查询条件存在差异，请核查期间、指标与业务范围。"}</p>}
    <div className="boss-bi-comparison-grid">{entries.map(entry=><article key={entry.id} className="boss-workspace-item" aria-label={entry.read?"口径 "+String(entry.read.result.context_snapshot.business_basis):"查询 "+entry.id}>
      <h3>{entry.read?String(entry.read.result.context_snapshot.business_basis):entry.id}</h3>
      <button className="boss-button" onClick={()=>choose(ids.filter(identifier=>identifier!==entry.id))}>移除此项并列</button>
      {entry.error&&<p role="alert">该项原始依据读取失败：{entry.error}</p>}
      {entry.read&&<><p>{entry.read.adoption_state} · 查询 {entry.read.result.query_id}</p>
        <p>{String(entry.read.result.context_snapshot.period_start)} 至 {String(entry.read.result.context_snapshot.period_end)} · {String(entry.read.result.context_snapshot.currency)} · {String(entry.read.result.context_snapshot.quantity_unit)}</p>
        {entry.read.adoption_state==="HISTORICAL_REQUIRES_REQUERY"&&<p>历史查询需要重新查询，当前原文不可采用。</p>}
        <div className="boss-table-scroll"><table className="boss-table boss-bi-table"><thead><tr><th>指标</th><th>当前原始值</th><th>单位</th></tr></thead><tbody>
          {entry.read.result.values.filter(value=>value.period_scope==="CURRENT").map(value=><tr key={value.metric_id}><th scope="row">{LABELS[value.metric_id]??value.metric_id}</th><td>{value.value??"未定义"}</td><td>{value.unit}</td></tr>)}</tbody></table></div>
        {entry.read.result.sources.map(source=><div key={source.source_id}><p>{source.source_id} · v{source.version} · {source.source_type}</p><p>{source.coverage}</p>
          <button className="boss-button" disabled={entry.read?.adoption_state==="HISTORICAL_REQUIRES_REQUERY"||Boolean(entry.error)} onClick={()=>onSource(source.source_id)}>打开该口径当前原文</button></div>)}
        {entry.evidence?.result.original_records.filter(record=>entry.read?.result.sources.some(source=>source.source_id===record.record_id)).map(record=>{
          const body=documentBody(record.content);
          return <details key={record.record_id}><summary>来源原文 {record.record_id} · v{record.version}</summary>
            <p>作者 {String(body?.author_display_name??body?.author_contact_id??"未知")} · {String(body?.author_kind??"未知")}</p>
            <p>业务口径 {String(body?.business_basis??"未知")} · 用途 {String(body?.allowed_use??"未知")}</p>
            <p>有效期 {String(body?.valid_from??"未知")} 至 {String(body?.valid_until??"未知")} · 位置 {String(body?.original_locator??"未知")}</p>
            <pre>{typeof body?.content==="string"?body.content:JSON.stringify(record.content,null,2)}</pre></details>;
        })}</>}
    </article>)}</div>
    {ids.length===0&&<p>查询一种口径后保留该项，再查询另一种口径并保留。</p>}
  </section>;
}
