import {useEffect,useState} from "react";
import {useClient} from "@/providers/ClientProvider";
import type {MorningReference} from "./BossMorningView";

type Detail={list_version:string;snapshot_sha256:string;item:{title:string;reason:string;related_meetings?:{id:string;version:string}[];source_refs:{kind:string;id:string;version:string|null}[]};documents:{source_id:string;version:string;simulation_definition?:string}[];business_authorization_granted:false};
export type MorningPreparationContext={source_ids:string[];meeting_id:string|null;event_ids:string[]};
export function BossMorningPreparation({reference,onReady,onContext,onReturn,refreshVersion}:{reference:MorningReference;onReady:(value:boolean)=>void;onContext:(value:MorningPreparationContext|null)=>void;onReturn:()=>void;refreshVersion:number}){
  const {getToken,token}=useClient();
  const [detail,setDetail]=useState<Detail|null>(null),[error,setError]=useState("");
  useEffect(()=>{
    const abort=new AbortController();setDetail(null);setError("");onReady(false);onContext(null);
    void fetch("/api/boss/ui/morning/detail?"+new URLSearchParams({list_id:reference.list_id,item_id:reference.item_id}),{headers:{Authorization:"Bearer "+getToken()},cache:"no-store",signal:abort.signal}).then(async response=>{
      const value=await response.json();if(!response.ok)throw new Error("当前晨间事项需要重新核查：HTTP "+response.status);
      if(abort.signal.aborted)return;
      if(value.list_version!==reference.list_version||value.snapshot_sha256!==reference.snapshot_sha256||value.business_authorization_granted!==false)throw new Error("晨间清单与准备交办引用不符");
      const detail=value as Detail;
      const sources=detail.documents.filter(document=>document.source_id==="finance-note"||["si09-si10-business-v1","FC04-ALERT-1"].includes(document.simulation_definition??"")).map(document=>document.source_id);
      setDetail(detail);onContext({source_ids:sources,meeting_id:detail.item.related_meetings?.[0]?.id??null,event_ids:detail.item.source_refs.filter(ref=>ref.kind==="event").map(ref=>ref.id)});onReady(sources.length>0);
    }).catch(failure=>{if(!abort.signal.aborted){setDetail(null);onReady(false);setError(failure.message);}});
    return()=>abort.abort();
  },[reference,getToken,token,onReady,onContext,refreshVersion]);
  return <section className="boss-panel"><header className="boss-panel-head"><h2>晨间事项交办准备</h2></header><p>清单 {reference.list_id} · 版本 {reference.list_version} · 事项 {reference.item_id}</p>
    {error&&<p role="alert" className="boss-status boss-status-error">{error}</p>}{detail?<><h3>{detail.item.title}</h3><p>{detail.item.reason}</p>{detail.item.source_refs.map(value=><p key={value.kind+value.id}>{value.kind} / {value.id} / v{value.version??"未知"}</p>)}
      {!detail.documents.some(document=>document.source_id==="finance-note"||["si09-si10-business-v1","FC04-ALERT-1"].includes(document.simulation_definition??""))&&<p role="status">当前事项缺少此交办流程支持的有效依据，请补充核查后继续。</p>}</>:!error&&<p role="status">正在核查当前事项与来源版本</p>}
    <p>交办创建、发送和完成分别需要本人确认。</p><button className="boss-btn" onClick={onReturn}>返回晨间清单</button>
  </section>;
}
