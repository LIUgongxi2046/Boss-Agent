import {useEffect, useRef, useState} from "react";
import {useClient} from "@/providers/ClientProvider";

export type TodayItem = {
  item_id:string;object_id:string;version:string|null;title:string;
  category:"DECIDE"|"COORDINATE"|"INFORM";reason:string;page_id:string;
  due_at:string|null;important:boolean;source_refs:{kind:string;id:string;version:string|null}[];
  target_id?:string|null;read_only?:boolean;state?:string;coordinator_id?:string|null;sorting_reasons?:string[];
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
  orderScope?:{list_id:string;date:string;timezone:string};
  onSelectItem?:(item:TodayItem)=>void;
  orderEnabled?:boolean;
};
export type TodayOrderReceipt={action:string;client_request_id:string;outcome:"RECORDED"|"NOT_FOUND_IN_CURRENT_STORE";write_performed_by_lookup:false};
export function morningReason(reason:string){
  const labels:Record<string,string>={"CATEGORY:DECIDE":"按照待本人决定事项分类","CATEGORY:COORDINATE":"按照待本人协调事项分类","CATEGORY:INFORM":"按照需要知晓事项分类",
    MATCHES_CONFIRMED_OWNER_GOAL:"符合当前本人确认目标",OVERDUE_AT_SELECTED_DAY:"在所选业务日之前已经到期",FUTURE_DEADLINE_BACKLOG:"期限位于后续日期，当前仍需跟进",
    DUE_WITHIN_SELECTED_DAY:"期限位于所选业务日",NO_DEADLINE_PROVIDED:"处理期限尚未提供",OWNER_SAVED_ORDER:"采用本人保存的当前日期次序",NEW_ITEM_DEFAULT_ORDER:"新增事项采用当前默认次序",
    OWNER_GOALS_NOT_SET:"当前本人目标尚未设置",REGIONAL_COVERAGE_NOT_PROVIDED:"地区资料覆盖尚未提供",COMPLETE_EXTERNAL_CALENDAR_NOT_VERIFIED:"完整外部日历尚未验证",
    SOURCE_REFRESH_COVERAGE_NOT_PROVIDED:"来源更新范围尚未提供",PRIORITY_RULES_NOT_CONFIGURED:"重要事项规则尚未设置",HISTORICAL_STATE_NOT_RECONSTRUCTED:"当前资料未重建历史业务状态",
    FUTURE_STATE_NOT_PREDICTED:"当前资料不包含未来状态预测",FULL_REGIONAL_COVERAGE_NOT_VERIFIED:"完整地区覆盖尚未验证",HISTORICAL_CONTENT_REQUIRES_REQUERY:"历史内容需要重新查询",
    TERMINAL_OR_NOT_ACTIVE:"对象已经终止或当前未启用",OUTSIDE_SELECTED_DAY:"时间位于所选业务日之外",UNKNOWN_END_OUTSIDE_START_DAY:"结束时间未知，开始日期位于所选业务日之外",
    BEFORE_APPLICABLE_DAY:"尚未到达适用日期",NO_CURRENT_CONFIRMED_TRAVEL:"当前没有有效确认的出行安排",SOURCE_NOT_CURRENT:"来源当前不可采用",SOURCE_VERSION_CHANGED:"来源版本已经变化",ASSIGNMENT_SOURCES_REQUIRE_REVIEW:"交办来源需要重新核查"};
  if(reason.startsWith("CURRENT_IMPORTANT_EVENT_RULE:"))return "符合当前有效重要事项规则，版本 "+reason.slice("CURRENT_IMPORTANT_EVENT_RULE:".length);
  const prefixes:Record<string,string>={UNKNOWN_END:"结束时间未知",DOCUMENT_SOURCE_NOT_PROVIDED:"原始准备材料尚未提供",REGION_NOT_UPDATED:"地区资料尚未更新",REGION_UNSYNCHRONIZED:"地区资料尚未同步",SOURCE_MISSING:"来源缺少",SOURCE_FORBIDDEN:"来源无权访问",SOURCE_WITHDRAWN:"来源已经撤销",SOURCE_EXPIRED:"来源已经到期",SOURCE_VERSION_CHANGED:"来源版本已经变化",ASSIGNMENT_SOURCES_REQUIRE_REVIEW:"交办来源需要重新核查"};
  const separator=reason.indexOf(":");if(separator>=0&&prefixes[reason.slice(0,separator)])return prefixes[reason.slice(0,separator)]+"："+reason.slice(separator+1);
  return labels[reason]??reason;
}

export function BossToday({data,loading,error,onReload,onNavigate,onReorder,onReadOrder,onDirtyChange,orderScope,onSelectItem,orderEnabled=true}:Props){
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
    setOrder([]);setDirty(false);setBusy(false);setFailure("");setReceipt(null);
    const key=new URLSearchParams(window.location.search).get("todayOrderRequest")??"";
    setOriginal(key);setPending(key);
    onDirtyChange(Boolean(key));
    if(key)void recover(key,abort.signal,version);
    return()=>{epoch.current++;abort.abort();};
  },[token]);
  useEffect(()=>{
    if(data&&!dirty&&!pending)setOrder(data.items.map(i=>i.item_id));
  },[data,dirty,pending]);
  function move(index:number,offset:number){
    if(!orderEnabled||pending||index+offset<0||index+offset>=order.length)return;
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
    if(!data||!orderEnabled||busy||pending)return;
    const version=epoch.current,key="today-"+crypto.randomUUID();
    const payload={...orderScope,client_request_id:key,
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
          <small>{item.due_at||"期限尚未提供"} · 当前版本 {item.version??"未知"}</small>
          {item.state&&<p>状态 {item.state} · 处理人 {item.coordinator_id??"尚未提供"}</p>}
          {item.sorting_reasons?.map(reason=><p key={reason}>{morningReason(reason)}</p>)}
          <div className="boss-actions">
            <button type="button" className="boss-btn" onClick={()=>onSelectItem?onSelectItem(item):onNavigate(item.page_id,item.target_id||item.object_id)}>{onSelectItem?"查看事项详情":item.read_only?"查看历史承诺资料":"打开关联事项"}</button>
            <button type="button" className="boss-btn" disabled={!orderEnabled||index===0||busy||Boolean(pending)} onClick={()=>move(index,-1)} aria-label={"提高事项次序："+item.title}>提高次序</button>
            <button type="button" className="boss-btn" disabled={!orderEnabled||index===items.length-1||busy||Boolean(pending)} onClick={()=>move(index,1)} aria-label={"降低事项次序："+item.title}>降低次序</button>
          </div>
          <details><summary>查看来源标识与版本</summary>{item.source_refs.map(ref=><p key={ref.kind+ref.id}>{ref.kind} / {ref.id} / {ref.version}</p>)}</details>
        </article>)}
        <div className="boss-actions"><button type="button" className="boss-btn boss-btn-primary" disabled={!orderEnabled||!dirty||busy||loading||Boolean(pending)} onClick={()=>void save()}>
          {busy?"正在处理本人次序":"本人确认保存当前次序"}</button>
          <button type="button" className="boss-btn" disabled={busy||Boolean(pending)} onClick={()=>{setDirty(false);onDirtyChange(false);onReload();}}>放弃未保存次序</button></div>
      </section></div><div className="boss-column"><section className="boss-panel">
        <div className="boss-panel-head"><h2>排序理由与资料覆盖</h2></div>
        <p>{data?.ordering_reason}</p><p>覆盖状态：{data?.coverage_state||"待读取"}</p>
        {data?.missing_sources.map(source=><p className="boss-helper" key={source}>{morningReason(source)}</p>)}
        <p>日程冲突检查：{data?.conflict_state||"待读取"}</p>
        <p className="boss-helper">资料或对象版本变化后，需要重新读取当前事项并核对次序。</p>
      </section></div></div>
  </>;
}
