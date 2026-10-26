import {V7Empty} from "./BossV7UI";

export type MetricTrend={metric_id:string;unit:string;points:{period:string;value:string|null;source_ids:string[]}[]};
export function BossMetricTrend({data,onSource}:{data:MetricTrend|null;onSource:(id:string)=>void}){
  if(!data||!data.points.some(point=>point.value!==null))return <div className="boss-sector-empty-trend"><V7Empty title="尚未读取趋势数据">查询后显示具有期间、单位和来源的实际趋势。</V7Empty></div>;
  const numbers=data.points.map(point=>point.value===null?null:Number(point.value));
  if(numbers.some(value=>value!==null&&!Number.isFinite(value)))throw new Error("指标趋势包含无效数值");
  const values=numbers.filter((value):value is number=>value!==null),minimum=Math.min(...values),maximum=Math.max(...values),difference=maximum-minimum;
  const points=numbers.map((value,index)=>value===null?null:{x:45+index*610/Math.max(1,numbers.length-1),y:difference===0?105:170-(value-minimum)*130/difference});
  const segments:{x:number;y:number}[][]=[];
  for(const point of points){if(point===null){if(segments.at(-1)?.length)segments.push([]);}else{if(!segments.length)segments.push([]);segments[segments.length-1].push(point);}}
  return <div className="boss-v7-trend"><div className="boss-panel-head"><strong>{data.metric_id}</strong><small>{data.unit}</small></div><svg viewBox="0 0 700 220" role="img" aria-label={data.metric_id+"期间趋势"}><line x1="45" y1="170" x2="655" y2="170" stroke="#dce4ed"/><line x1="45" y1="40" x2="655" y2="40" stroke="#e7edf4"/><text x="45" y="25">{maximum} {data.unit}</text>{segments.filter(segment=>segment.length).map((segment,index)=><polyline key={index} points={segment.map(point=>point.x+","+point.y).join(" ")} fill="none" stroke="#0968ea" strokeWidth="2.5"/>)}{points.map((point,index)=>point&&<circle key={index} cx={point.x} cy={point.y} r="4" fill="#0968ea"><title>{data.points[index].period+"："+data.points[index].value+" "+data.unit}</title></circle>)}<text x="45" y="205">{data.points[0].period}</text><text x="655" y="205" textAnchor="end">{data.points.at(-1)?.period}</text></svg><details><summary>趋势明细与来源</summary><table className="boss-v7-table"><thead><tr><th>期间</th><th>指标值</th><th>来源</th></tr></thead><tbody>{data.points.map((point,index)=><tr key={index}><td>{point.period}</td><td>{point.value===null?"资料缺少":point.value+" "+data.unit}</td><td>{point.source_ids.length?point.source_ids.map(id=><button key={id} className="boss-v7-text-button" onClick={()=>onSource(id)}>{id}</button>):"尚未提供逐期间来源"}</td></tr>)}</tbody></table></details></div>;
}
