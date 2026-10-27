import {useEffect, useRef, useState, type ReactNode} from "react";
import {useClient} from "@/providers/ClientProvider";
import {moveTodayOrderWithinCategory, todayOrderPosition, validateTodayOrderReceipt, withoutTodayOrderRequest, isConfirmedMissingTodayOrderReceipt, type TodayOrderReceipt} from "./today-order";
export type {TodayOrderReceipt} from "./today-order";

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
  presentation?:"table"|"compact";
  children?:ReactNode;
  onDiscuss?:()=>void;
  discussEnabled?:boolean;
  category?:TodayItem["category"]|"ALL";
  selectedItemId?:string;
};
export function morningState(state:string){const labels:Record<string,string>={OPEN:"待处理",DRAFT:"草稿",ACTIVE:"当前启用",IN_PROGRESS:"处理中",RESULT_SUBMITTED:"结果已提交",PENDING_DECISION:"等待本人决定",WAITING_MATERIAL:"等待材料",CONFIRMED:"已经确认",CANCELED:"已经取消",HELD:"已经举行",CLOSED:"已经关闭",APPROVED:"已经批准",REJECTED:"已经拒绝",COMPLETED_CONFIRMED:"本人已确认完成"};return labels[state]??state;}
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
  const prefixes:Record<string,string>={UNKNOWN_END:"结束时间未知",DOCUMENT_SOURCE_NOT_PROVIDED:"原始准备材料尚未提供",REGION_NOT_UPDATED:"地区资料尚未更新",REGION_UNSYNCHRONIZED:"地区资料尚未同步",SOURCE_MISSING:"来源缺少",SOURCE_FORBIDDEN:"来源无权访问",SOURCE_WITHDRAWN:"来源已经撤销",SOURCE_EXPIRED:"来源已经到期",SOURCE_VERSION_CHANGED:"来源版本已经变化",SOURCE_NEEDS_REIMPORT:"来源需要重新载入",SOURCE_NOT_CURRENT:"来源当前不可采用",ASSIGNMENT_SOURCES_REQUIRE_REVIEW:"交办来源需要重新核查",LINKED_EVENT:"同一事项关联经营事件",CURRENT_BUSINESS_ALERT_RULE:"当前经营提醒规则版本",TRANSPORT_SOURCE_NOT_PROVIDED:"交通依据尚未提供",RISK_REQUIRES_REVIEW:"当前风险判断需要复核",MEETING_LINK_REQUIRES_REVIEW:"会议关联需要复核",RELATED_MEETING_NOT_CURRENT:"关联会议当前不可采用",RELATED_MEETING_SOURCES_REQUIRE_REVIEW:"关联会议来源需要复核"};
  const separator=reason.indexOf(":");if(separator>=0&&prefixes[reason.slice(0,separator)])return prefixes[reason.slice(0,separator)]+"："+reason.slice(separator+1);
  return labels[reason]??reason;
}

export function BossToday({data,loading,error,onReload,onNavigate,onReorder,onReadOrder,onDirtyChange,orderScope,onSelectItem,orderEnabled:requestedOrderEnabled=true,presentation,category="ALL",selectedItemId,children,onDiscuss,discussEnabled=false}:Props){
  const {client,token}=useClient();
  const [order,setOrder]=useState<string[]>([]);
  const [dirty,setDirty]=useState(false);
  const [busy,setBusy]=useState(false);
  const [failure,setFailure]=useState("");
  const [pending,setPending]=useState("");
  const [original,setOriginal]=useState("");
  const [receipt,setReceipt]=useState<TodayOrderReceipt|null>(null);
  const [page,setPage]=useState(1);
  const [orderBasis,setOrderBasis]=useState("");
  const [orderMode,setOrderMode]=useState(false);
  const currentBasis=JSON.stringify([data?.date,data?.timezone,data?.snapshot_sha256,data?.order_version,orderScope]);
  const stale=dirty&&orderBasis!==currentBasis;
  const orderEnabled=requestedOrderEnabled&&!stale&&!loading;
  const epoch=useRef(0),sequence=useRef(0);
  useEffect(()=>{
    const version=++epoch.current,abort=new AbortController();
    setOrder([]);setDirty(false);setOrderBasis("");setBusy(false);setFailure("");setReceipt(null);
    const key=new URLSearchParams(window.location.search).get("todayOrderRequest")??"";
    setOriginal(key);setPending(key);
    onDirtyChange(Boolean(key));
    if(key)void recover(key,abort.signal,version);
    return()=>{epoch.current++;abort.abort();};
  },[client,token]);
  useEffect(()=>{
    if(data&&!dirty&&!pending)setOrder(data.items.map(i=>i.item_id));
  },[data,dirty,pending]);
  function move(index:number,offset:-1|1){
    if(!orderEnabled||busy||pending||index<0||index>=order.length)return;
    const changed=moveTodayOrderWithinCategory(order,data?.items??[],category,order[index],offset);
    if(!changed)return;
    if(!dirty)setOrderBasis(currentBasis);
    setOrder(changed);setDirty(true);onDirtyChange(true);
  }
  function clearTrackedRequest(key:string){
    const revised=withoutTodayOrderRequest(window.location.href,key);
    if(revised!==null)window.history.replaceState(window.history.state,"",revised);
  }
  function acknowledgeMissing(){
    if(busy||!pending||!isConfirmedMissingTodayOrderReceipt(receipt,pending))return;
    clearTrackedRequest(pending);setPending("");
    onDirtyChange(dirty);
    setFailure(dirty
      ?"原排序请求在当前库未找到；已由本人结束原编号核查，未保存次序仍保留。请核对后再决定是否明确提交。"
      :"原排序请求在当前库未找到；已由本人结束核查。刷新前未保存次序无法恢复，请重新核对当前清单后再调整。");
  }
  async function recover(key=original,signal?:AbortSignal,version=epoch.current){
    if(!key)return;
    const request=++sequence.current;setBusy(true);setFailure("");
    const current=()=>!signal?.aborted&&version===epoch.current&&request===sequence.current;
    try{
      const value=validateTodayOrderReceipt(await onReadOrder(key,signal),key);
      if(!current())return;
      setReceipt(value);
      if(value.outcome==="RECORDED"){
        clearTrackedRequest(key);setPending("");setDirty(false);setOrderMode(false);onDirtyChange(false);onReload();
      }else{
        setFailure("原排序请求在当前库未找到记录；不会自动重发。可以再次读取原编号，或明确结束核查。");
      }
    }catch(reason){
      if(current())setFailure(reason instanceof Error?reason.message:String(reason));
    }finally{
      if(current())setBusy(false);
    }
  }
  async function save(){
    if(!data||!orderEnabled||busy||pending)return;
    const version=epoch.current,key="today-"+crypto.randomUUID();
    const payload={...orderScope,client_request_id:key,
      expected_version:data.order_version,snapshot_sha256:data.snapshot_sha256,item_ids:order};
    setOriginal(key);setPending(key);setReceipt(null);setBusy(true);setFailure("");
    const address=new URL(window.location.href);address.searchParams.set("todayOrderRequest",key);window.history.replaceState(window.history.state,"",address);
    await onReorder(payload).then(async()=>{if(version===epoch.current)await recover(key,undefined,version);},(reason:unknown)=>{
      if(version!==epoch.current)return;
      const status=typeof reason==="object"&&reason!==null&&"status" in reason?Number(reason.status):null;
      if(status!==null&&[400,401,403,404,409,410,413].includes(status)){
        setPending("");clearTrackedRequest(key);
      }
      setFailure((status===409?"事项版本或本人次序已经变化；未保存编辑已保留，请核查当前资料。":reason instanceof Error?reason.message:String(reason))+"；原排序请求 "+key);
    });
    if(version===epoch.current)setBusy(false);
  }
  function cancelOrder(){setOrder(data?.items.map(i=>i.item_id)??[]);setDirty(false);onDirtyChange(false);setOrderMode(false);setFailure("");}
  const items=order.map(id=>data?.items.find(i=>i.item_id===id)).filter((i):i is TodayItem=>Boolean(i));
  const labels={DECIDE:"待本人决定",COORDINATE:"待本人协调",INFORM:"需要知晓"};
  useEffect(()=>{setPage(1);},[category,data?.date,data?.timezone]);
  if(presentation==="compact"){
    const filtered=items.filter(item=>category==="ALL"||item.category===category),pages=Math.max(1,Math.ceil(filtered.length/10)),currentPage=Math.min(page,pages);
    const selectedIndex=items.findIndex(item=>item.item_id===selectedItemId);
    const selectedPosition=todayOrderPosition(order,data?.items??[],category,selectedItemId??"");
    return <section className="boss-panel boss-f01-list" aria-label="我的当前事项" aria-busy={loading}>
      <header className="boss-panel-head"><h2>今天需要我参与的事</h2></header>
      {children}
      {(error||failure)&&<p className="boss-status boss-status-error" role="alert">{error||failure}</p>}
      {loading&&<p role="status">正在读取本人事项</p>}
      <ul className="boss-f01-items">{filtered.slice((currentPage-1)*10,currentPage*10).map(item=><li key={item.item_id} data-item-id={item.item_id}>
        <button id={"morning-item-"+item.item_id} type="button" className="boss-f01-item" aria-label={item.title} aria-pressed={selectedItemId===item.item_id}
          onClick={()=>onSelectItem?onSelectItem(item):onNavigate(item.page_id,item.target_id||item.object_id)}
          onKeyDown={event=>{if(event.altKey&&["ArrowUp","ArrowDown"].includes(event.key)){event.preventDefault();move(items.findIndex(value=>value.item_id===item.item_id),event.key==="ArrowUp"?-1:1);}}}>
          <span className="boss-f01-item-icon" aria-hidden="true">✓</span><span className="boss-f01-item-copy"><strong>{item.title}</strong>
            <span>{item.reason} · 处理人：{item.coordinator_id??"尚未提供"} · 有效期限：{item.due_at??"尚未提供"} · {morningState(item.state??"尚未提供")}</span>
          </span><span className="boss-f01-item-category">{labels[item.category]}{item.important?" · 重要事项":""}</span>
        </button>
      </li>)}</ul>
      {!loading&&filtered.length===0&&<p className="boss-f01-empty">{data?"当前资料在此分类没有可展示事项；来源及覆盖缺口见右侧。":"资料尚待读取，事项数量尚未确定。"}</p>}
      <div className="boss-f01-table-foot"><span>{data?"当前分类 "+filtered.length+" 项 / 全部 "+items.length+" 项":"数量等待读取"} · 每页10项</span>
        {pages>1&&<div className="boss-actions"><button className="boss-btn" type="button" disabled={currentPage===1} onClick={()=>setPage(currentPage-1)}>上一页</button><span>{currentPage} / {pages}</span><button className="boss-btn" type="button" disabled={currentPage===pages} onClick={()=>setPage(currentPage+1)}>下一页</button></div>}</div>
      <div className="boss-actions boss-f01-sort-actions">{!orderMode&&<button type="button" className="boss-btn" disabled={!orderEnabled||busy||Boolean(pending)} onClick={()=>{if(selectedPosition.index<0){setFailure("请先选择一个事项再调整排序。");return;}setFailure("");setOrderMode(true);}}>调整排序</button>}
        {orderMode&&<><button type="button" className="boss-btn" disabled={!orderEnabled||selectedPosition.index<=0||busy||Boolean(pending)} onClick={()=>move(selectedIndex,-1)}>上移 ↑</button>
        <button type="button" className="boss-btn" disabled={!orderEnabled||selectedPosition.index<0||selectedPosition.index===selectedPosition.total-1||busy||Boolean(pending)} onClick={()=>move(selectedIndex,1)}>下移 ↓</button>
        <button type="button" className="boss-btn boss-btn-primary" disabled={!orderEnabled||!dirty||busy||loading||Boolean(pending)} onClick={()=>void save()}>{busy?"正在保存排序":"保存排序"}</button>
        <button type="button" className="boss-btn" disabled={busy||Boolean(pending)} onClick={cancelOrder}>取消排序</button></>}
        {onDiscuss&&<button id="morning-discuss" type="button" className="boss-btn boss-btn-primary" disabled={!discussEnabled||busy||Boolean(pending)} onClick={onDiscuss}>让大鹏处理这件事</button>}</div>
      {orderMode&&<p role="status">{selectedPosition.index<0?"选择一个事项后可调整它在本分类中的位置。":"当前分类中第 "+(selectedPosition.index+1)+" / "+selectedPosition.total+" 项。"}</p>}
      {dirty&&<p role="status">{stale?"当前清单或次序版本已经变化，未保存次序继续保留。请明确放弃未保存次序并核查新版本后调整。":"当前次序尚未保存。选中事项支持 Alt+方向键调整。"}</p>}
      {pending&&<div role="status"><p>排序结果尚未确认，原请求 {original} · 回执 {receipt?.outcome??"尚未取得"}</p><button type="button" className="boss-btn" disabled={busy} onClick={()=>void recover()}>读取排序原请求结果</button>
        {isConfirmedMissingTodayOrderReceipt(receipt,pending)&&<button type="button" className="boss-btn" disabled={busy} onClick={acknowledgeMissing}>结束原编号核查，保留当前编辑</button>}</div>}
      <details className="boss-f01-order-record"><summary>查看排序依据与保存结果</summary><p>{data?.ordering_reason??"排序依据等待读取"} · 版本 {data?.order_version??"未知"}</p>
        <button type="button" className="boss-btn" disabled={!dirty||busy||Boolean(pending)} onClick={cancelOrder}>取消排序</button>
        {original&&<p>排序原请求 {original}</p>}{receipt&&<p>排序回执 {receipt.outcome}</p>}{pending&&<p role="status">排序结果尚未确认，请读取同一原请求结果。</p>}
        {original&&!pending&&<button type="button" className="boss-btn" disabled={busy} onClick={()=>void recover()}>读取排序原请求结果</button>}
      </details>
    </section>;
  }
  if(presentation==="table"){
    const filtered=items.filter(item=>category==="ALL"||item.category===category),pages=Math.max(1,Math.ceil(filtered.length/10)),currentPage=Math.min(page,pages);
    return <section className="boss-panel boss-f01-list" aria-label="我的当前事项" aria-busy={loading}>
      <header className="boss-panel-head"><div><h2>我的当前事项</h2><p>当前排序版本 {data?.order_version??"等待读取"}</p></div>
        <button type="button" className="boss-btn" disabled={loading||busy||dirty||Boolean(pending)} onClick={onReload}>重新读取今日资料</button></header>
      {(error||failure)&&<p className="boss-status boss-status-error" role="alert">{error||failure}</p>}
      {loading&&<p role="status">正在读取本人事项</p>}
      <div className="boss-f01-table-scroll" tabIndex={0} aria-label="事项表格，可横向滚动"><table className="boss-f01-table"><thead><tr>
        <th scope="col">事项标题</th><th scope="col">处理人</th><th scope="col">期限</th><th scope="col">状态</th><th scope="col">参与原因与排序理由</th><th scope="col">调整次序</th>
      </tr></thead><tbody>{filtered.slice((currentPage-1)*10,currentPage*10).map(item=>{
        const index=items.findIndex(value=>value.item_id===item.item_id);
        const position=todayOrderPosition(order,data?.items??[],category,item.item_id);
        return <tr key={item.item_id} data-item-id={item.item_id} aria-selected={selectedItemId===item.item_id}>
          <td><button id={"morning-item-"+item.item_id} className="boss-f01-item-link" type="button" onClick={()=>onSelectItem?onSelectItem(item):onNavigate(item.page_id,item.target_id||item.object_id)}
            onKeyDown={event=>{if(event.altKey&&["ArrowUp","ArrowDown"].includes(event.key)){event.preventDefault();move(index,event.key==="ArrowUp"?-1:1);}}}>{item.title}</button>
            <span className="boss-f01-cell-note">{labels[item.category]}{item.important?" · 重要事项":""} · v{item.version??"未知"}</span></td>
          <td>{item.coordinator_id??"尚未提供"}</td><td>{item.due_at??"期限尚未提供"}</td><td>{morningState(item.state??"状态尚未提供")}</td>
          <td><p>{item.reason}</p><ul>{item.sorting_reasons?.map(reason=><li key={reason}>{morningReason(reason)}</li>)}</ul></td>
          <td><div className="boss-f01-order-buttons"><button type="button" className="boss-btn" disabled={!orderEnabled||position.index<=0||busy||Boolean(pending)} onClick={()=>move(index,-1)} aria-label={"提高事项次序："+item.title}>上移</button>
            <button type="button" className="boss-btn" disabled={!orderEnabled||position.index<0||position.index===position.total-1||busy||Boolean(pending)} onClick={()=>move(index,1)} aria-label={"降低事项次序："+item.title}>下移</button></div></td>
        </tr>;
      })}</tbody></table></div>
      {!loading&&filtered.length===0&&<p className="boss-f01-empty">{data?"当前资料在此分类没有可展示事项；来源及覆盖缺口见右侧。":"资料尚待读取，事项数量尚未确定。"}</p>}
      <div className="boss-f01-table-foot"><span>{data?"当前分类 "+filtered.length+" 项 / 全部 "+items.length+" 项":"数量等待读取"} · 每页10项</span>
        <div className="boss-actions"><button className="boss-btn" type="button" disabled={currentPage===1} onClick={()=>setPage(currentPage-1)}>上一页</button><span>{currentPage} / {pages}</span><button className="boss-btn" type="button" disabled={currentPage===pages} onClick={()=>setPage(currentPage+1)}>下一页</button></div></div>
      <div className="boss-f01-order-save"><p>{data?.ordering_reason??"排序依据等待读取"}</p>
        <div className="boss-actions"><button type="button" className="boss-btn boss-btn-primary" disabled={!orderEnabled||!dirty||busy||loading||Boolean(pending)} onClick={()=>void save()}>{busy?"正在保存当前次序":"本人确认保存当前次序"}</button>
          <button type="button" className="boss-btn" disabled={!dirty||busy||Boolean(pending)} onClick={cancelOrder}>取消排序</button></div>
        {dirty&&<p role="status">{stale?"当前清单或次序版本已经变化，未保存次序继续保留。请明确放弃未保存次序并核查新版本后调整。":"当前次序尚未保存。事项标题支持 Alt+方向键调整，也可以使用上移、下移按钮。"}</p>}
        {original&&<p>排序原请求 {original}</p>}{receipt&&<p>排序回执 {receipt.outcome}</p>}{pending&&<p role="status">排序结果尚未确认，请读取同一原请求结果。</p>}
        {isConfirmedMissingTodayOrderReceipt(receipt,pending)&&<button type="button" className="boss-btn" disabled={busy} onClick={acknowledgeMissing}>结束原编号核查，保留当前编辑</button>}
        {original&&<button type="button" className="boss-btn" disabled={busy} onClick={()=>void recover()}>读取排序原请求结果</button>}
      </div>
    </section>;
  }
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
    {isConfirmedMissingTodayOrderReceipt(receipt,pending)&&<button type="button" className="boss-btn" disabled={busy} onClick={acknowledgeMissing}>结束原编号核查，保留当前编辑</button>}
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
