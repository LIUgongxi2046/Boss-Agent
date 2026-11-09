import {useEffect,useState,type FormEvent} from "react";
import type {MethodSelection,MethodCatalog} from "./upgrade2-run-client";

export function Upgrade2MethodSelection({allowed,catalog,onSelect}:{allowed:boolean;catalog:MethodCatalog|null;onSelect:(method:MethodSelection)=>void}) {
  const [selected,setSelected]=useState<MethodSelection|null>(null);
  const [invalidated,setInvalidated]=useState(false);
  const method=catalog?.methods.find(item=>selected&&item.sop_id===selected.sop_id&&item.version===selected.version&&item.content_sha256===selected.content_sha256&&item.status==="AVAILABLE");
  useEffect(()=>{if(catalog&&selected&&!method){setSelected(null);setInvalidated(true);}},[catalog,selected,method]);
  function submit(event:FormEvent<HTMLFormElement>){event.preventDefault();if(allowed&&catalog?.selection_allowed&&method)onSelect({sop_id:method.sop_id,version:method.version,content_sha256:method.content_sha256});}
  return <section className="upgrade2-run-card"><h3>重新选择方法</h3>
    {catalog?<><p>目标版本 {catalog.goal_revision}。选择由当前方法目录提供，服务提交时会重新核查依赖。</p>
      <form onSubmit={submit}><label>方法<select value={method?.sop_id??""} onChange={event=>{const item=catalog.methods.find(candidate=>candidate.sop_id===event.target.value&&candidate.status==="AVAILABLE");setSelected(item?{sop_id:item.sop_id,version:item.version,content_sha256:item.content_sha256}:null);setInvalidated(false);}} disabled={!allowed||!catalog.selection_allowed}><option value="">请选择方法</option>{catalog.methods.map(item=><option key={item.sop_id} value={item.sop_id} disabled={item.status!=="AVAILABLE"}>{item.name} · {item.sop_id} · 版本 {item.version}{item.status!=="AVAILABLE"?" · 不可用":""}</option>)}</select></label>
        {(invalidated||selected&&!method)&&<p role="status">所选方法已变化或不可用，请重新选择。</p>}
        {method&&<p>方法摘要 {method.content_sha256}</p>}<button type="submit" disabled={!allowed||!catalog.selection_allowed||!method}>提交方法选择</button></form>
      {catalog.methods.filter(item=>item.status!=="AVAILABLE").map(item=><p key={item.sop_id}>{item.name} 不可用：{[...item.reasons,...item.missing_native_tools,...item.missing_runtime_tools,...item.missing_projections].join("、")}</p>)}
    </>:<p>尚未取得当前运行的方法目录。</p>}
    {!allowed&&<p role="status">当前运行尚未允许重新选择方法。</p>}
  </section>;
}
