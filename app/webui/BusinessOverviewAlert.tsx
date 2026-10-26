import {useEffect,useState} from "react";
import {useClient} from "@/providers/ClientProvider";
import {BossBusinessAlerts,type BusinessAlertRead} from "./BossBusinessAlerts";
import {savedOverviewScope} from "./BossBusinessOverview";
import type {Overview} from "./business-overview-types";

export function BusinessOverviewAlert({onNavigate,onOpenTask,onDirtyChange,refreshVersion=0}:{onNavigate:(page:string)=>void;onOpenTask:(id:string)=>void;onDirtyChange:(dirty:boolean)=>void;refreshVersion?:number}){
  const {client,token,getToken}=useClient();
  const [projection,setProjection]=useState<BusinessAlertRead|null>(null),[error,setError]=useState(""),[revision,setRevision]=useState(0),[loading,setLoading]=useState(true);
  useEffect(()=>{
    const abort=new AbortController();setProjection(null);setError("");setLoading(true);
    const scope=savedOverviewScope(),query=new URLSearchParams(window.location.search),id=query.get("bossEvent"),version=query.get("bossEventVersion");
    if(!scope||!id||!version)throw new Error("经营提醒缺少原范围或事项版本");
    void client.requestMutation<Overview>("boss.business_overview.read",scope).then(async view=>{
      if(abort.signal.aborted)return;
      const expected=view.alerts.find(row=>row.event_id===id&&row.event_version===version);
      if(!expected)throw new Error("当前原范围没有所选版本的经营提醒，请返回经营关注重新核查");
      const response=await fetch("/api/boss/ui/business-alerts",{headers:{Authorization:"Bearer "+getToken()},cache:"no-store",signal:abort.signal});
      if(response.status===401)window.dispatchEvent(new Event("boss-auth-expired"));
      if(!response.ok)throw new Error("当前经营提醒读取失败，HTTP "+response.status);
      const result=await response.json() as BusinessAlertRead;
      if(abort.signal.aborted)return;
      const selected=result.items.find(row=>row.event_id===id&&row.event_version===version);
      if(result.source_type!=="SIMULATED"||!selected||selected.review_sha256!==expected.review_sha256)throw new Error("当前提醒或来源在读取期间已经变化，请重新核查");
      setProjection({...result,items:[selected]});setLoading(false);
    }).catch(reason=>{if(!abort.signal.aborted){setProjection(null);setLoading(false);setError(reason instanceof Error?reason.message:String(reason));}});
    return()=>abort.abort();
  },[client,token,getToken,revision,refreshVersion]);
  return <div>{error&&<section className="boss-panel"><p role="alert">{error}</p><button className="boss-btn" onClick={()=>setRevision(value=>value+1)}>重新核查原经营提醒</button></section>}<BossBusinessAlerts projection={projection} loading={loading} revision={revision+refreshVersion} onReload={()=>setRevision(value=>value+1)} onNavigate={onNavigate} onOpenTask={onOpenTask} onDirtyChange={onDirtyChange}/></div>;
}
