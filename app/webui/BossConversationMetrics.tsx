import {useEffect,useState} from "react";
import {useClient} from "@/providers/ClientProvider";
import {BossMetricTrend} from "./BossMetricTrend";

type Query={id:string;recorded_version:string|null};
type Metric={metric_id:string;metric_name?:string;period_scope:string;scope_description:string;value:string|null;unit:string;formula:string;definition_version:string;display_rounding:string};
type Result={run_id:string;chat_id:string;session_id:string;business_authorization_granted:false;business_mutation_performed:false;kind:"query";id:string;data:{context_snapshot:Record<string,unknown>;values:Metric[];comparison:{state:string;reasons:string[]};missing_fields:string[];unexplained_causes:string[];trends?:{metric_id:string;unit:string;definition_version:string;points:{period_start:string;period_end:string;value:string|null;coverage_state:string;source_ids?:string[]}[]}[]};evidence:{sources:{source_id:string;version:string}[]}|null};
type Props={chatId:string|null;runId:string|null;queries:Query[];active:boolean;refreshVersion:number;onOpen:(id:string)=>void;onSource:(id:string,version?:string)=>void};

export function BossConversationMetrics({chatId,runId,queries,active,refreshVersion,onOpen,onSource}:Props){
  const {client,token}=useClient();
  const [selected,setSelected]=useState(""),[result,setResult]=useState<Result|null>(null),[error,setError]=useState(""),[loading,setLoading]=useState(false),[revision,setRevision]=useState(0);
  const query=queries.find(item=>item.id===selected)??queries.at(-1);
  const queryId=query?.id,version=query?.recorded_version;
  useEffect(()=>{
    let disposed=false;setResult(null);setError("");setLoading(false);
    if(!active||!chatId||!runId||!queryId)return;
    setLoading(true);
    void client.requestMutation<Result>("boss.conversation.artifact",{chat_id:chatId,run_id:runId,kind:"query",id:queryId}).then(value=>{
      if(disposed)return;
      if(value.chat_id!==chatId||value.session_id!=="websocket:"+chatId||value.business_authorization_granted!==false||value.business_mutation_performed!==false||value.run_id!==runId||value.kind!=="query"||value.id!==queryId||!value.data?.context_snapshot||!Array.isArray(value.data.values)||!value.data.comparison||!Array.isArray(value.data.missing_fields)||!Array.isArray(value.data.unexplained_causes))throw new Error("经营指标与当前会话原查询不符。");
      setResult(value);setLoading(false);
    }).then(undefined,failure=>{if(!disposed){setResult(null);setLoading(false);setError(failure instanceof Error?failure.message:String(failure));}});
    return()=>{disposed=true;};
  },[client,token,chatId,runId,queryId,version,active,revision,refreshVersion]);
  const current=active&&result?.run_id===runId&&result.id===queryId?result:null;
  return <>
    {queries.length>0&&<label className="boss-n02-session-select">当前运行查询<select value={queryId??""} onChange={event=>setSelected(event.target.value)}>{queries.map(item=><option key={item.id} value={item.id}>{item.id}</option>)}</select></label>}
    {loading&&<p role="status">正在读取原查询的指标与依据。</p>}
    {error&&<div className="boss-n02-note error" role="alert">{error}<button className="boss-btn" onClick={()=>setRevision(value=>value+1)}>重新读取指标</button></div>}
    <div className="boss-chat-metric-grid">{current?.data.values.length?current.data.values.slice(0,4).map((item,index)=><div key={item.metric_id+item.period_scope+index}><span>{item.metric_name??item.metric_id}</span><strong>{item.value===null?"当前无法确定":item.value+" "+item.unit}</strong><small>{item.period_scope} · {item.scope_description}</small><small>定义版本 {item.definition_version}</small></div>):["指标数值","比较期间","计算依据","资料覆盖"].map(title=><div key={title}><span>{title}</span><strong>{error?"读取失败":loading?"正在核查":queryId?"尚未取得结果":"尚未查询"}</strong></div>)}</div>
    {current&&<><p className="boss-helper">比较状态：{current.data.comparison.state} · 原查询 {current.id}</p>{current.data.comparison.reasons.map(reason=><p key={reason}>{reason}</p>)}{current.data.missing_fields.length>0&&<p className="boss-n02-note warn">资料缺口：{current.data.missing_fields.join("、")}</p>}{current.data.unexplained_causes.map(reason=><p key={reason}>{reason}</p>)}<button className="boss-btn" data-conversation-return={"metric:"+runId+":"+current.id} onClick={()=>onOpen(current.id)}>查看全部指标、期间与来源（{current.data.values.length} 项）</button></>}
    {current?.data.trends?.length?current.data.trends.map(trend=><section key={trend.metric_id+trend.definition_version}><p>定义版本 {trend.definition_version}</p><BossMetricTrend data={{metric_id:trend.metric_id,unit:trend.unit,points:trend.points.map(point=>({period:point.period_start+" 至 "+point.period_end,value:point.value,source_ids:point.source_ids??[]}))}} onSource={id=>onSource(id,current.evidence?.sources.find(source=>source.source_id===id)?.version)}/><details><summary>期间覆盖状态</summary>{trend.points.map(point=><p key={point.period_start+point.period_end}>{point.period_start} 至 {point.period_end} · {point.coverage_state}</p>)}</details></section>):<div className="boss-chat-trend-empty"><strong>尚无可核查的经营趋势序列</strong><span>期间、单位、可比口径及完整来源取得后显示趋势。</span></div>}
  </>;
}
