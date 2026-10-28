import {ArrowUpRight, CircleAlert, Sparkles} from "lucide-react";
import "./boss-insights.css";

export type BossInsight={id:string;target_id:string;target_kind?:string;title:string;finding:string;impact:string;action:string;evidence:string[];priority:"urgent"|"attention";basis:"CURRENT_RECORD_RULE";action_executed:false};

export function BossInsightList({items,onOpen,disabled=false,buttonId,label="继续分析",empty="当前资料没有触发需要优先处理的提醒。"}:{items:BossInsight[];onOpen:(item:BossInsight)=>void;disabled?:boolean;buttonId?:(item:BossInsight)=>string;label?:string;empty?:string}){
  return <div className="boss-insights">
    <p className="boss-insights-caption"><Sparkles size={14}/>根据当前资料检查 · {items.length} 项关注</p>
    {items.map(item=><article className={"boss-insight boss-insight-"+item.priority} key={item.id}>
      <div className="boss-insight-priority"><CircleAlert size={14}/>{item.priority==="urgent"?"优先关注":"建议关注"}</div>
      <h3>{item.title}</h3><p className="boss-insight-finding">{item.finding}</p>
      <p>{item.impact}</p>
      <div className="boss-insight-action"><span>建议行动</span><p>{item.action}</p></div>
      <details><summary>查看判断依据</summary><ul>{item.evidence.map((text,index)=><li key={index}>{text}</li>)}</ul><p>原因与影响需要结合原文继续核查，建议尚未执行。</p></details>
      <button type="button" id={buttonId?.(item)} className="boss-btn" disabled={disabled} onClick={()=>onOpen(item)}>{label}<ArrowUpRight size={15}/></button>
    </article>)}
    {!items.length&&<p className="boss-insights-empty">{empty}</p>}
  </div>;
}
