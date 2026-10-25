import {useEffect,useState} from "react";
import {useClient} from "@/providers/ClientProvider";
import {BossBIView} from "./BossBIView";
import {savedOverviewScope} from "./BossBusinessOverview";
import type {Overview} from "./business-overview-types";

export function BusinessOverviewQuery({getToken,onSource,onReturn,onDirtyChange}:{getToken:()=>string;onSource:(id:string)=>void;onReturn:()=>void;onDirtyChange:(dirty:boolean)=>void}){
  const {client,token}=useClient();
  const [view,setView]=useState<Overview|null>(null),[error,setError]=useState("");
  useEffect(()=>{
    let active=true;setView(null);setError("");
    const scope=savedOverviewScope(),snapshot=new URLSearchParams(window.location.search).get("overviewQuerySnapshot");
    if(!scope||!snapshot||!/^[a-f0-9]{64}$/.test(snapshot))throw new Error("经营查询缺少原范围或固定资料版本");
    void client.requestMutation<Overview>("boss.business_overview.read",scope).then(result=>{
      if(!active)return;
      if(result.projection!=="business-overview"||result.business_authorization_granted!==false||result.business_mutation_performed!==false||result.snapshot_sha256!==snapshot)throw new Error("经营资料已经变化，请返回经营关注重新核查范围");
      if(!result.query_handoff)throw new Error(result.query_handoff_unavailable_reason??"当前范围没有正式经营查询条件");
      setView(result);
    }).catch(reason=>{if(active)setError(reason instanceof Error?reason.message:String(reason));});
    return()=>{active=false;};
  },[client,token]);
  return <div><section className="boss-panel" aria-label="经营关注查询来源"><h2>经营关注查询范围</h2><p>当前查询继承经营关注已经应用的法人、区域、期间与正式指标来源。表单中的补充条件只影响本次查询。</p><p>本次指标资料覆盖水产饲料外销，专业专题的资料缺口继续保留。</p><button className="boss-btn" onClick={onReturn}>返回经营关注</button>{error&&<p role="alert">{error}</p>}{!view&&!error&&<p role="status">正在重新核查经营范围与资料版本。</p>}</section>{view?.query_handoff&&<BossBIView getToken={getToken} onSource={onSource} initialScope={view.query_handoff} onDirtyChange={onDirtyChange}/>}</div>;
}
