import {useEffect,useState} from "react";
import {useClient} from "@/providers/ClientProvider";
import type {MorningReference} from "./BossMorningView";
import {prepareMorningAssignmentContext, type MorningAssignmentDetail, type MorningPreparationContext} from "./morning-assignment-context";
export type {MorningPreparationContext} from "./morning-assignment-context";

type Detail=MorningAssignmentDetail&{item:MorningAssignmentDetail["item"]&{title:string;reason:string}};
export function BossMorningPreparation({reference,onReady,onContext,onReturn,refreshVersion}:{reference:MorningReference;onReady:(value:boolean)=>void;onContext:(value:MorningPreparationContext|null)=>void;onReturn:()=>void;refreshVersion:number}){
  const {getToken,token}=useClient();
  const [detail,setDetail]=useState<Detail|null>(null),[error,setError]=useState("");
  useEffect(()=>{
    const abort=new AbortController();setDetail(null);setError("");onReady(false);onContext(null);
    void fetch("/api/boss/ui/morning/detail?"+new URLSearchParams({list_id:reference.list_id,item_id:reference.item_id}),{headers:{Authorization:"Bearer "+getToken()},cache:"no-store",signal:abort.signal}).then(async response=>{
      const value=await response.json();if(!response.ok)throw new Error("当前晨间事项需要重新核查：HTTP "+response.status);
      if(abort.signal.aborted)return;
      const detail=value as Detail;
      const context=prepareMorningAssignmentContext(reference,detail);
      setDetail(detail);onContext(context);onReady(context.source_ids.length>0);
    }).catch(failure=>{if(!abort.signal.aborted){setDetail(null);onReady(false);setError(failure.message);}});
    return()=>abort.abort();
  },[reference,getToken,token,onReady,onContext,refreshVersion]);
  return <section className="boss-panel"><header className="boss-panel-head"><h2>晨间事项交办准备</h2></header><p>清单 {reference.list_id} · 版本 {reference.list_version} · 事项 {reference.item_id}</p>
    {error&&<p role="alert" className="boss-status boss-status-error">{error}</p>}{detail?<><h3>{detail.item.title}</h3><p>{detail.item.reason}</p>{detail.item.source_refs.map(value=><p key={value.kind+value.id}>{value.kind} / {value.id} / v{value.version??"未知"}</p>)}
      {detail.documents.length===0&&<p role="status">当前事项没有可确认的原文来源；不能创建无依据交办，请补充有效来源后重新核查。</p>}</>:!error&&<p role="status">正在核查当前事项与来源版本</p>}
    <p>交办创建、发送和完成分别需要本人确认。</p><button className="boss-btn" onClick={onReturn}>返回晨间清单</button>
  </section>;
}
