import {useEffect,useState} from "react";
import {useClient} from "@/providers/ClientProvider";
import type {MorningReference} from "./BossMorningView";

type Detail={list_version:string;snapshot_sha256:string;item:{title:string;reason:string;source_refs:{kind:string;id:string;version:string|null}[]};documents:{source_id:string;version:string}[];business_authorization_granted:false};
export function BossMorningPreparation({reference,onReady,onReturn,refreshVersion}:{reference:MorningReference;onReady:(value:boolean)=>void;onReturn:()=>void;refreshVersion:number}){
  const {getToken,token}=useClient();
  const [detail,setDetail]=useState<Detail|null>(null),[error,setError]=useState("");
  useEffect(()=>{
    const abort=new AbortController();setDetail(null);setError("");onReady(false);
    void fetch("/api/boss/ui/morning/detail?"+new URLSearchParams({list_id:reference.list_id,item_id:reference.item_id}),{headers:{Authorization:"Bearer "+getToken()},cache:"no-store",signal:abort.signal}).then(async response=>{
      const value=await response.json();if(!response.ok)throw new Error("当前晨间事项需要重新核查：HTTP "+response.status);
      if(abort.signal.aborted)return;
      if(value.list_version!==reference.list_version||value.snapshot_sha256!==reference.snapshot_sha256||value.business_authorization_granted!==false)throw new Error("晨间清单与准备交办引用不符");
      setDetail(value);onReady(value.documents.some((document:{source_id:string})=>document.source_id==="finance-note"));
    }).catch(failure=>{if(!abort.signal.aborted){setDetail(null);onReady(false);setError(failure.message);}});
    return()=>abort.abort();
  },[reference,getToken,token,onReady,refreshVersion]);
  return <section className="boss-panel"><header className="boss-panel-head"><h2>晨间事项交办准备</h2></header><p>清单 {reference.list_id} · 版本 {reference.list_version} · 事项 {reference.item_id}</p>
    {error&&<p role="alert" className="boss-status boss-status-error">{error}</p>}{detail?<><h3>{detail.item.title}</h3><p>{detail.item.reason}</p>{detail.item.source_refs.map(value=><p key={value.kind+value.id}>{value.kind} / {value.id} / v{value.version??"未知"}</p>)}
      {!detail.documents.some(document=>document.source_id==="finance-note")&&<p role="status">当前交办入口尚未支持本事项的来源范围，请补充核查后继续。</p>}</>:!error&&<p role="status">正在核查当前事项与来源版本</p>}
    <p>交办创建、发送和完成分别需要本人确认。</p><button className="boss-btn" onClick={onReturn}>返回晨间清单</button>
  </section>;
}
