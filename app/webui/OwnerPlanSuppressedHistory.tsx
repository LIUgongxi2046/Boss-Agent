import {useEffect,useRef,useState} from "react";
import {useClient} from "@/providers/ClientProvider";
import Ajv2020 from "ajv/dist/2020";
import schema from "../../validation/agent_schedule_history_schema.json";

const validate=new Ajv2020({strictTypes:false,allowUnionTypes:true}).compile(schema);
const reasons:Record<string,string>={OWNER_PLAN_PAUSED:"本人计划已暂停",OWNER_PLAN_CANCELED:"本人计划已取消",PLAN_PAUSED_OR_CANCELED:"计划已暂停或取消",SOURCE_CANCELED:"事项已取消",QUIET_HOURS:"处于免打扰时段",COOLDOWN:"处于提醒冷却时段",DUPLICATE_EVENT:"事项已经处理",BOSS_CLOSED:"本人已关闭提醒",BOSS_SNOOZED:"本人已推迟提醒",TASK_ENDED:"关联任务已结束"};
export function suppressedReason(value:string):string {return reasons[value]??value;}
type History={plan_id:string;plan_version:string;event_id:string;event_version:string;receipts:{plan_id:string;plan_version:string;event_id:string;event_version:string;dispatch_id:string;reason:string;business_at:string|null;occurrence_binding:string;occurrence_id:string|null;run_id:string|null}[]};

export function OwnerPlanSuppressedHistory({planId,version,eventId}:{planId:string;version:string;eventId:string}) {
  const {token,getToken}=useClient();
  const [history,setHistory]=useState<History|null>(null),[historyScope,setHistoryScope]=useState(""),[error,setError]=useState(""),[busy,setBusy]=useState(false);
  const scope=JSON.stringify([planId,version,eventId,token]);
  const epoch=useRef(0);
  useEffect(()=>{epoch.current++;setHistory(null);setError("");setBusy(false);return()=>{epoch.current++;};},[planId,version,eventId,token]);
  async function read(){
    if(busy||!token||getToken()!==token)return;
    setHistory(null);setError("");setBusy(true);
    const current=token, currentEpoch=epoch.current;
    try {
      const query=new URLSearchParams({version,event_id:eventId});
      const response=await fetch("/api/v2/owner-plans/"+encodeURIComponent(planId)+"/suppressed-history?"+query,{headers:{Authorization:"Bearer "+token},credentials:"same-origin",cache:"no-store",redirect:"error"});
      if(!response.ok)throw new Error("抑制历史读取失败，HTTP "+response.status+"。");
      const value:unknown=await response.json();
      if(!validate(value))throw new Error("抑制历史响应不符合 Schema。");
      const result=value as History;
      if(result.plan_id!==planId||result.plan_version!==version||result.event_id!==eventId||result.receipts.some(item=>item.plan_id!==planId||item.plan_version!==version||item.event_id!==eventId||item.event_version!==result.event_version))throw new Error("抑制历史与当前计划不一致。");
      if(getToken()===current&&epoch.current===currentEpoch){setHistory(result);setHistoryScope(scope);}
    } catch(failure){if(getToken()===current&&epoch.current===currentEpoch)setError(failure instanceof Error?failure.message:String(failure));}
    finally{if(getToken()===current&&epoch.current===currentEpoch)setBusy(false);}
  }
  return <section aria-label={"事项 "+eventId+" 的抑制历史"}><h4>事项 {eventId}</h4><button type="button" className="boss-btn" disabled={busy||!token} onClick={()=>void read()}>读取事项抑制历史</button>{busy&&<p role="status">正在读取抑制历史。</p>}{error&&<p role="alert">{error}</p>}{history&&historyScope===scope&&getToken()===token&&<>{history.receipts.length?<ul>{history.receipts.map(item=><li key={item.dispatch_id}>{suppressedReason(item.reason)} · {item.business_at??"业务时间未提供"} · 回执 {item.dispatch_id} · {item.occurrence_binding==="VERIFIED"?"发生编号 "+item.occurrence_id+" · 运行 "+item.run_id:"发生关联未核查"}</li>)}</ul>:<p>当前事项没有抑制回执。</p>}</>}</section>;
}
