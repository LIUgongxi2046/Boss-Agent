import {useEffect, useRef, useState} from "react";
import {useClient} from "@/providers/ClientProvider";

export type TodayItem = {
  item_id:string;object_id:string;version:string;title:string;
  category:"DECIDE"|"COORDINATE"|"INFORM";reason:string;page_id:string;
  due_at:string|null;important:boolean;source_refs:{kind:string;id:string;version:string}[];
  target_id?:string;read_only?:boolean;
};
export type TodayProjection = {
  date:string;timezone:string;items:TodayItem[];snapshot_sha256:string;
  order_version:string;ordering_reason:string;missing_sources:string[];
  conflict_state:string;coverage_state:string;
};
type Props = {
  data:TodayProjection|null;loading:boolean;error:string;
  onReload:()=>void;onNavigate:(page:string, objectId:string)=>void;
  onReorder:(payload:Record<string,unknown>)=>Promise<void>;
  onReadOrder:(requestId:string,signal?:AbortSignal)=>Promise<TodayOrderReceipt>;
  onDirtyChange:(dirty:boolean)=>void;
};
export type TodayOrderReceipt={action:string;client_request_id:string;outcome:"RECORDED"|"NOT_FOUND_IN_CURRENT_STORE";write_performed_by_lookup:false};

export function BossToday({data,loading,error,onReload,onNavigate,onReorder,onReadOrder,onDirtyChange}:Props){
  const {token}=useClient();
  const [order,setOrder]=useState<string[]>([]);
  const [dirty,setDirty]=useState(false);
  const [busy,setBusy]=useState(false);
  const [failure,setFailure]=useState("");
  const [pending,setPending]=useState("");
  const [original,setOriginal]=useState("");
  const [receipt,setReceipt]=useState<TodayOrderReceipt|null>(null);
  const epoch=useRef(0),sequence=useRef(0);
  useEffect(()=>{
    const version=++epoch.current,abort=new AbortController();
    setOrder([]);setDirty(false);onDirtyChange(false);setBusy(false);setFailure("");setReceipt(null);
    const key=new URLSearchParams(window.location.search).get("todayOrderRequest")??"";
    setOriginal(key);setPending(key);
    if(key)void recover(key,abort.signal,version);
    return()=>{epoch.current++;abort.abort();};
  },[token]);
  useEffect(()=>{
    if(data&&!dirty&&!pending)setOrder(data.items.map(i=>i.item_id));
  },[data,dirty,pending]);
  function move(index:number,offset:number){
    if(pending||index+offset<0||index+offset>=order.length)return;
    const changed=[...order];
    [changed[index],changed[index+offset]]=[changed[index+offset],changed[index]];
    setOrder(changed);setDirty(true);onDirtyChange(true);
  }
  async function recover(key=original,signal?:AbortSignal,version=epoch.current){
    if(!key)return;
    const request=++sequence.current;setBusy(true);setFailure("");
    await onReadOrder(key,signal).then(value=>{
      if(signal?.aborted||version!==epoch.current||request!==sequence.current)return;
      if(value.action!=="boss.today.reorder"||value.client_request_id!==key||value.write_performed_by_lookup!==false)throw new Error("排序原请求回执与当前编号不符");
      setReceipt(value);
      if(value.outcome==="RECORDED"){setPending("");setDirty(false);onDirtyChange(false);onReload();}
    },failure=>{if(!signal?.aborted&&version===epoch.current&&request===sequence.current)setFailure(failure instanceof Error?failure.message:String(failure));});
    if(!signal?.aborted&&version===epoch.current&&request===sequence.current)setBusy(false);
  }
  async function save(){
    if(!data||busy||pending)return;
    const version=epoch.current,key="today-"+crypto.randomUUID();
    const payload={client_request_id:key,
      expected_version:data.order_version,snapshot_sha256:data.snapshot_sha256,item_ids:order};
    setOriginal(key);setPending(key);setReceipt(null);setBusy(true);setFailure("");
    const address=new URL(window.location.href);address.searchParams.set("todayOrderRequest",key);window.history.replaceState(null,"",address);
    await onReorder(payload).then(async()=>{if(version===epoch.current)await recover(key,undefined,version);},(reason:unknown)=>{
      if(version!==epoch.current)return;
      const status=typeof reason==="object"&&reason!==null&&"status" in reason?Number(reason.status):null;
      if(status!==null&&[400,401,403,404,409,410,413].includes(status)){
        setPending("");const current=new URL(window.location.href);if(current.searchParams.get("todayOrderRequest")===key){current.searchParams.delete("todayOrderRequest");window.history.replaceState(null,"",current);}
      }
      setFailure((reason instanceof Error?reason.message:String(reason))+"；原排序请求 "+key);
    });
    if(version===epoch.current)setBusy(false);
  }
  const items=order.map(id=>data?.items.find(i=>i.item_id===id)).filter((i):i is TodayItem=>Boolean(i));
  const labels={DECIDE:"待本人决定",COORDINATE:"待本人协调",INFORM:"需要知晓"};
  return <>
    <div className="boss-workspace-toolbar">
      <span className="boss-tag boss-tag-amber">SIMULATED · 本人资料</span>
      <span>{data?.date} · {data?.timezone}</span>
      <button type="button" className="boss-btn" disabled={loading||busy||dirty} onClick={onReload}>重新读取今日资料</button>
    </div>
    {(error||failure)&&<div className="boss-status boss-status-error" role="alert">{error||failure}</div>}
    {original&&<p>排序原请求 {original}</p>}
    {receipt&&<p>排序回执 {receipt.outcome}</p>}
    {pending&&<p role="status">排序结果尚未确认，请读取同一原请求结果。</p>}
    <div className="boss-actions"><button type="button" className="boss-btn" disabled={!original||busy} onClick={()=>void recover()}>读取排序原请求结果</button></div>
    {loading&&<p role="status">正在读取本人事项</p>}
    <div className="boss-columns"><div className="boss-column">
      <section className="boss-panel"><div className="boss-panel-head"><h2>本人事项与处理次序</h2><small>当前排序版本 {data?.order_version}</small></div>
        {items.length===0&&!loading&&<p className="boss-helper">当前资料没有可展示事项，资料覆盖范围仍需核查。</p>}
        {items.map((item,index)=><article className="boss-workspace-item" key={item.item_id}>
          <span className="boss-tag">{labels[item.category]}{item.important?" · 重要事项":""}</span>
          <h3>{item.title}</h3><p>{item.reason}</p>
          <small>{item.due_at||"期限尚未提供"} · 当前版本 {item.version}</small>
          <div className="boss-actions">
            <button type="button" className="boss-btn" onClick={()=>onNavigate(item.page_id,item.target_id||item.object_id)}>{item.read_only?"查看历史承诺资料":"打开关联事项"}</button>
            <button type="button" className="boss-btn" disabled={index===0||busy||Boolean(pending)} onClick={()=>move(index,-1)} aria-label={"提高事项次序："+item.title}>提高次序</button>
            <button type="button" className="boss-btn" disabled={index===items.length-1||busy||Boolean(pending)} onClick={()=>move(index,1)} aria-label={"降低事项次序："+item.title}>降低次序</button>
          </div>
          <details><summary>查看来源标识与版本</summary>{item.source_refs.map(ref=><p key={ref.kind+ref.id}>{ref.kind} / {ref.id} / {ref.version}</p>)}</details>
        </article>)}
        <div className="boss-actions"><button type="button" className="boss-btn boss-btn-primary" disabled={!dirty||busy||loading||Boolean(pending)} onClick={()=>void save()}>
          {busy?"正在处理本人次序":"本人确认保存当前次序"}</button>
          <button type="button" className="boss-btn" disabled={busy||Boolean(pending)} onClick={()=>{setDirty(false);onDirtyChange(false);onReload();}}>放弃未保存次序</button></div>
      </section></div><div className="boss-column"><section className="boss-panel">
        <div className="boss-panel-head"><h2>排序理由与资料覆盖</h2></div>
        <p>{data?.ordering_reason}</p><p>覆盖状态：{data?.coverage_state||"待读取"}</p>
        {data?.missing_sources.map(source=><p className="boss-helper" key={source}>{source}</p>)}
        <p>日程冲突检查：{data?.conflict_state||"待读取"}</p>
        <p className="boss-helper">资料或对象版本变化后，需要重新读取当前事项并核对次序。</p>
      </section></div></div>
  </>;
}
