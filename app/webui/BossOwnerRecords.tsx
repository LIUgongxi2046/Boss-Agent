import {useEffect,useRef,useState} from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {V7Empty,V7Fact,V7Panel,V7Pagination,V7ReadState,V7Tabs} from "./BossV7UI";
import {useOwnerWorkspace} from "./useTechnicalWorkspace";
import {OwnerConditions,OwnerEventTimeline,OwnerOriginalRecords,OwnerRecordFacts,OwnerRecordIdentity,OwnerSources,ownerState,type OwnerRecord} from "./BossOwnerRecordDetails";

type Domain="authorizations"|"decisions"|"notification-history";
type Projection={projection:Domain;private_body_available_here:true;records:OwnerRecord[];namespace:string;business_clock:string;read_at:string};
type Filters={query:string;start:string;end:string;meeting:string;kind:string;source:string;namespace:string};
type SavedView={filters:Filters;page:number;tab:string};
const EMPTY_FILTERS:Filters={query:"",start:"",end:"",meeting:"",kind:"",source:"",namespace:""};
const calendarDate=new Intl.DateTimeFormat("en-CA",{timeZone:"Asia/Shanghai",year:"numeric",month:"2-digit",day:"2-digit"});

function matches(record:OwnerRecord,filters:Filters,tab:string){
  const includes=(value:string,query:string)=>value.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase());
  const date=record.created_at?calendarDate.format(new Date(record.created_at)):"";
  return (tab==="ALL"||record.effective_state===tab)
    &&(!filters.query||[record.id,record.title,record.target_id??"",...record.source_ids].some(value=>includes(value,filters.query)))
    &&(!filters.start||date!==""&&date>=filters.start)&&(!filters.end||date!==""&&date<=filters.end)
    &&(!filters.meeting||record.original_records.some(value=>value.kind==="MINUTES"&&includes(value.id,filters.meeting))||record.values.some(value=>includes(value.value??"",filters.meeting)))
    &&(!filters.kind||record.title===filters.kind)&&(!filters.source||record.source_ids.some(value=>includes(value,filters.source)))
    &&(!filters.namespace||record.namespace===filters.namespace);
}

export function BossOwnerRecords({pageId,onNavigate,onOpenTask,onViewSource}:{pageId:string;onNavigate:(page:string)=>void;onOpenTask:(id:string)=>void;onViewSource:(id:string)=>void}){
  const domain:Domain=pageId==="N11"?"decisions":pageId==="D09"?"notification-history":"authorizations";
  const api=useOwnerWorkspace<Projection>(domain);
  const saved=useRef<SavedView|undefined>(window.history.state?.bossOwnerRecords?.[pageId]);
  const recordParameter=pageId==="D09"?"bossHistoryRecord":"bossOwnerRecord";
  const [selected,setSelected]=useState(()=>new URLSearchParams(window.location.search).get(recordParameter)??"");
  const [tab,setTab]=useState(saved.current?.tab??(pageId==="N10"?"CURRENT":"ALL"));
  const [filters,setFilters]=useState<Filters>(saved.current?.filters??EMPTY_FILTERS);
  const [draft,setDraft]=useState<Filters>(filters);
  const [page,setPage]=useState(saved.current?.page??1);
  const [revoke,setRevoke]=useState(false);
  const [reason,setReason]=useState("");
  const [decisionOpen,setDecisionOpen]=useState(false);
  const originalRef=useRef<HTMLDivElement>(null);
  const timelineRef=useRef<HTMLDivElement>(null);
  const records=(api.data?.records??[]).filter(row=>matches(row,filters,tab));
  const record=api.data?.records.find(row=>row.id===selected);
  const currentPage=Math.min(page,Math.max(1,Math.ceil(records.length/10)));
  const busy=api.busy||!!api.pending;
  const canContinue=!!record?.can_continue&&!record.historical&&!!(record.task_id||record.current_page);
  const canRecover=!!record?.request_id&&!!record.action&&!record.historical;
  const isList=pageId==="N10",isDecisions=pageId==="N11",isHistory=pageId==="D09",isNecessary=pageId==="D02";

  useEffect(()=>{
    const changed=()=>setSelected(new URLSearchParams(window.location.search).get(recordParameter)??"");
    window.addEventListener("boss-notification-target-changed",changed);
    window.addEventListener("popstate",changed);
    return()=>{window.removeEventListener("boss-notification-target-changed",changed);window.removeEventListener("popstate",changed);};
  },[recordParameter]);
  useEffect(()=>{
    if(!api.data)return;
    const state=window.history.state??{};
    window.history.replaceState({...state,bossOwnerRecords:{...state.bossOwnerRecords,[pageId]:{filters,page:currentPage,tab}}},"",window.location.href);
  },[api.data,filters,currentPage,pageId,tab]);
  useEffect(()=>{setRevoke(false);setDecisionOpen(false);setReason("");},[selected]);

  function select(id:string){
    setSelected(id);
    const url=new URL(window.location.href);
    if(id)url.searchParams.set(recordParameter,id);else url.searchParams.delete(recordParameter);
    window.history.replaceState(window.history.state,"",url);
  }
  function continuation(){
    if(!record||!canContinue)return;
    if(record.task_id)onOpenTask(record.task_id);else if(record.current_page)onNavigate(record.current_page);
  }
  function recover(){
    if(!record||!canRecover)return;
    const url=new URL(window.location.href);
    url.searchParams.set("bossRecoveryRequest",record.request_id!);url.searchParams.set("bossRecoveryAction",record.action!);
    window.history.replaceState(window.history.state,"",url);onNavigate("D03");
  }
  function requestRevoke(){if(record?.can_revoke&&!record.historical){setReason("");setRevoke(true);}}
  function inspectOriginal(){originalRef.current?.scrollIntoView({block:"start",behavior:"smooth"});originalRef.current?.focus({preventScroll:true});}
  function inspectTimeline(){timelineRef.current?.scrollIntoView({block:"start",behavior:"smooth"});timelineRef.current?.focus({preventScroll:true});}
  function editFilter(key:keyof Filters,value:string){setDraft(old=>({...old,[key]:value}));}
  const filterForm=<form className="boss-owner-filters" onSubmit={event=>{event.preventDefault();setFilters({...draft});setPage(1);}}>
    {isDecisions?<>
      <label>期间起始<input type="date" value={draft.start} max={draft.end||undefined} onChange={event=>editFilter("start",event.target.value)}/></label>
      <label>期间结束<input type="date" value={draft.end} min={draft.start||undefined} onChange={event=>editFilter("end",event.target.value)}/></label>
      <label>会议<input value={draft.meeting} placeholder="会议编号或原文关键词" onChange={event=>editFilter("meeting",event.target.value)}/></label>
      <label>决定类型<select value={draft.kind} onChange={event=>editFilter("kind",event.target.value)}><option value="">全部类型</option>{[...new Set(api.data?.records.map(row=>row.title)??[])].map(value=><option key={value}>{value}</option>)}</select></label>
      <label>来源<input value={draft.source} onChange={event=>editFilter("source",event.target.value)}/></label>
    </>:<label>目标对象或来源<input value={draft.query} placeholder={isList?"按名称搜索，编号可在高级条件输入":"按名称搜索"} onChange={event=>editFilter("query",event.target.value)}/></label>}
    {isList&&<label>记录范围<select value={tab} onChange={event=>{setTab(event.target.value);setPage(1);}}><option value="ALL">全部状态</option>{[...new Set(["CURRENT","EXPIRED","REVOKED","EXECUTED",...api.data?.records.map(row=>row.effective_state)??[]])].map(value=><option key={value} value={value}>{ownerState(value)}</option>)}</select></label>}
    {isDecisions&&<label>执行空间<select value={draft.namespace} onChange={event=>editFilter("namespace",event.target.value)}><option value="">全部获准空间</option>{[...new Set(api.data?.records.map(row=>row.namespace)??[])].map(value=><option key={value}>{value}</option>)}</select></label>}
    <button className="boss-btn boss-btn-primary" type="submit" disabled={api.loading}>{isList?"筛选授权":isDecisions?"筛选历史决定":"查询"}</button>
  </form>;
  const selector=<div className="boss-owner-filters">
    <label>{isHistory?"获准历史记录":"目标事项与当前版本"}<select value={selected} onChange={event=>select(event.target.value)}>
      <option value="">请选择记录</option>{api.data?.records.map(row=><option key={row.id} value={row.id}>{row.title} · {row.target_id??row.id} · v{row.version}{row.historical?" · 历史只读":""}</option>)}
    </select></label>
    {isHistory?<><V7Fact label="原数据集">{record?.dataset_id??"尚未选择"}</V7Fact><V7Fact label="原执行空间">{record?.namespace??"尚未选择"}</V7Fact><V7Fact label="历史版本">{record?.version??"尚未选择"}</V7Fact></>:<><V7Fact label="当前身份">老板本人</V7Fact><V7Fact label="内容版本">{record?.version??"尚未选择"}</V7Fact></>}
    <button className="boss-btn" disabled={api.loading} onClick={api.reload}>{isHistory?"刷新当前事项状态":"刷新授权状态"}</button>
  </div>;
  const statePanel=<V7Panel title="状态与核查">
    <V7Fact label="记录状态">{record?ownerState(record.effective_state):api.loading?"正在读取":"尚未选择记录"}</V7Fact>
    <V7Fact label="当前事项">{record?.current_target_id??"没有已读取的对应事项"}</V7Fact>
    <V7Fact label="读取时间">{api.data?.read_at??"尚未读取"}</V7Fact>
    <V7Fact label="业务时钟">{api.data?.business_clock??"尚未读取"}</V7Fact>
    {record?.historical&&<p className="boss-v7-note">原执行空间已归档，仅供本人查询历史内容。</p>}
    <button className="boss-btn" disabled={api.loading} onClick={api.reload}>刷新正式状态</button>
  </V7Panel>;
  const sources=<V7Panel title="来源与依据">
    {record?<><OwnerRecordIdentity record={record}/><OwnerConditions record={record}/><OwnerSources record={record} onViewSource={onViewSource}/></>:<V7Empty title="尚未选择记录">选择记录后查看当时版本与来源状态。</V7Empty>}
    {isDecisions&&record&&<div ref={originalRef} tabIndex={-1}><h3>原始记录</h3><OwnerOriginalRecords record={record}/><OwnerEventTimeline record={record}/></div>}
  </V7Panel>;
  const conditionPanel=<V7Panel title={isNecessary?"原任务上下文":"当前对象与有效条件"}>
    {record?<><OwnerRecordFacts record={record}/>{isHistory&&<p className="boss-v7-note">当前显示原通知与当时对象版本。当前事项通过独立入口查询。</p>}</>:<V7Empty title={selected?"原记录不存在或当前无权读取":"请选择获准记录"}>对象、内容版本、范围与执行结果需要分别核查。</V7Empty>}
  </V7Panel>;
  const eventPanel=<div ref={timelineRef} tabIndex={-1}><V7Panel title="事件与反馈时间线">
    {record?<><OwnerEventTimeline record={record}/><div ref={originalRef} tabIndex={-1}><h3>原始记录</h3><OwnerOriginalRecords record={record}/></div></>:<V7Empty title="尚无已读取的事件与反馈"/>}
  </V7Panel></div>;

  return <div className="boss-owner-records">
    <V7ReadState loading={api.loading} error={api.error} onReload={api.reload}/>
    {api.pending&&<div className="boss-status boss-status-warn">原请求 {api.pending.request_id} 需要核查。<button className="boss-btn" disabled={api.busy} onClick={()=>void api.reconcile()}>核查原请求</button></div>}
    {api.receipt&&<p role="status" className="boss-status boss-status-ok">操作已记录 · {api.receipt.request_id}</p>}
    {selected&&api.data&&!record&&<p className="boss-status boss-status-warn">原记录不存在或当前无权读取。请选择获准记录或返回原页面。</p>}
    {isDecisions&&filterForm}
    {!isList&&!isDecisions&&selector}
    {isNecessary?<>
      {conditionPanel}
      <div className="boss-owner-actions"><button className="boss-btn boss-btn-primary" disabled={!record?.missing.length||record.historical} onClick={()=>setDecisionOpen(true)}>核对本次决定</button><button className="boss-btn" disabled={!canContinue} onClick={continuation}>打开原事项</button><button className="boss-btn" onClick={()=>onNavigate("N10")}>查看我的授权记录</button></div>
      {record&&!record.missing.length&&<p className="boss-v7-note">当前记录没有返回缺少条件。后续操作在原事项中按当前有效指令处理。</p>}
    </>:<div className="boss-owner-columns"><div className="boss-column">
      {isList?<V7Panel title="对象与记录">
        <V7Tabs label="授权有效状态" value={tab} onChange={value=>{setTab(value);setPage(1);}} items={[{id:"CURRENT",title:"当前有效"},{id:"EXPIRED",title:"已到期"},{id:"REVOKED",title:"已撤销"},{id:"EXECUTED",title:"已执行"}]}/>
        {filterForm}
        <div className="boss-v7-table-scroll"><table className="boss-v7-table"><thead><tr><th>目标对象</th><th>授权动作</th><th>内容版本</th><th>范围</th><th>有效期</th></tr></thead><tbody>{records.slice((currentPage-1)*10,currentPage*10).map(row=><tr key={row.id} aria-selected={selected===row.id}>
          <td><button className="boss-v7-text-button" onClick={()=>select(row.id)}>{row.target_id??row.id}</button></td><td>{row.title}</td><td>{row.version}</td><td>{row.scope.join("、")}<small>{ownerState(row.effective_state)}</small></td><td>{row.valid_until??"未记录"}</td>
        </tr>)}</tbody></table></div>
        {!records.length&&<V7Empty title={api.loading?"正在查询本人授权":"当前范围没有授权记录"}/>}
        <V7Pagination page={currentPage} total={records.length} pageSize={10} onChange={setPage}/>
      </V7Panel>:isDecisions?<V7Panel title="历史决定时间线">
        <div className="boss-v7-timeline">{records.slice((currentPage-1)*10,currentPage*10).map(row=><article key={row.id} aria-current={row.id===selected?"true":undefined}>
          <time dateTime={row.created_at}>{row.created_at}</time><button className="boss-v7-text-button" onClick={()=>select(row.id)}>{row.title}</button><p>内容版本 {row.version} · {ownerState(row.effective_state)}</p>
          <V7Fact label="当时条件">{row.values.find(value=>value.label==="确认依据")?.value??"未记录确认依据"}</V7Fact><V7Fact label="关联交办">{row.task_id??"没有可访问的当前交办"}</V7Fact>
          <p>{row.namespace} · {row.historical?"归档只读":"当前执行空间"}</p><button className="boss-btn" onClick={()=>select(row.id)}>查看当时依据</button>
        </article>)}</div>
        {!records.length&&<V7Empty title={api.loading?"正在查询历史决定":"当前条件下没有历史决定"}/>}
        <V7Pagination page={currentPage} total={records.length} pageSize={10} onChange={setPage}/>
        <p className="boss-v7-note">历史决定保留当时版本，后续资料变化不会改写已作出的决定。期间按 Asia/Shanghai 查询。</p>
      </V7Panel>:<>{conditionPanel}{eventPanel}</>}
    </div><aside className="boss-column">
      {isList?<V7Panel title="选中记录">{record?<><OwnerRecordIdentity record={record}/><OwnerRecordFacts record={record}/><h3>执行记录</h3><OwnerEventTimeline record={record}/></>:<V7Empty title="尚未选择记录">选择实际条目后查看对象、来源及操作。</V7Empty>}</V7Panel>:sources}
      {statePanel}
    </aside></div>}
    {!isNecessary&&<div className="boss-owner-actions" aria-label="当前记录操作">
      {isList?<><button className="boss-btn" disabled={!record} onClick={()=>{if(!record)return;const url=new URL(window.location.href);url.searchParams.set("bossOwnerRecord",record.id);window.history.replaceState(window.history.state,"",url);onNavigate("F28");}}>查看授权详情</button><button className="boss-btn" disabled={!canContinue||!record?.task_id} onClick={continuation}>打开关联交办</button><button className="boss-btn boss-owner-danger" disabled={!record?.can_revoke||busy||record.historical} onClick={requestRevoke}>撤销授权</button><button className="boss-btn" disabled={!canRecover} onClick={recover}>查看执行记录</button></>:
       isDecisions?<><button className="boss-btn" disabled={!record} onClick={inspectOriginal}>查看当时依据</button><button className="boss-btn" disabled={!canContinue} onClick={continuation}>查看当前事项</button><button className="boss-btn" disabled={!canContinue} onClick={()=>onNavigate("N02")}>基于这项决定继续讨论</button></>:
       isHistory?<><button className="boss-btn" onClick={()=>onNavigate("N06")}>返回通知</button><button className="boss-btn" disabled={!canContinue} onClick={continuation}>查看当前事项</button></>:
       <><button className="boss-btn boss-btn-primary" disabled={!record?.missing.length||record.historical} onClick={()=>setDecisionOpen(true)}>{record?"核对并确认"+record.title:"核对并确认"}</button><button className="boss-btn boss-owner-danger" disabled={!record?.can_revoke||busy||record.historical} onClick={requestRevoke}>撤销授权</button><button className="boss-btn" disabled={!canContinue||!record?.task_id} title="前往原事项，核查并取消尚未执行步骤" onClick={continuation}>取消未执行动作</button><button className="boss-btn" disabled={!record} onClick={inspectTimeline}>查看授权及执行历史</button></>}
    </div>}
    <Dialog.Root open={decisionOpen&&!!record&&!record.historical&&record.missing.length>0} onOpenChange={setDecisionOpen}><Dialog.Portal><Dialog.Overlay className="boss-v7-dialog-overlay"/><Dialog.Content className="boss-v7-dialog boss-owner-decision-dialog">
      <Dialog.Title>当前动作必要决定</Dialog.Title><Dialog.Description>核查当前对象、内容版本和具体缺少条件，在原事项中补充有效指令。当前弹窗不会提交业务写入。</Dialog.Description>
      {record&&<OwnerRecordFacts record={record}/>}
      <div className="boss-actions"><Dialog.Close asChild><button className="boss-btn">返回原任务上下文</button></Dialog.Close><button className="boss-btn boss-btn-primary" disabled={!canContinue} onClick={continuation}>打开原事项核对</button><button className="boss-btn" disabled={!canContinue||!record?.task_id} title="前往原事项，核查并取消尚未执行步骤" onClick={continuation}>取消未执行操作</button></div>
    </Dialog.Content></Dialog.Portal></Dialog.Root>
    <Dialog.Root open={revoke&&!!record&&!record.historical} onOpenChange={setRevoke}><Dialog.Portal><Dialog.Overlay className="boss-v7-dialog-overlay"/><Dialog.Content className="boss-v7-dialog">
      <Dialog.Title>撤销当前授权</Dialog.Title><Dialog.Description>授权 {record?.authorization_id}，目标 {record?.target_id}，内容版本 {record?.version}。撤销将停止后续采用，已经执行的历史记录保留。</Dialog.Description>
      <label className="boss-field">本人撤销原因<textarea required rows={3} maxLength={400} value={reason} onChange={event=>setReason(event.target.value)}/></label>
      <div className="boss-actions"><Dialog.Close asChild><button className="boss-btn">取消</button></Dialog.Close><button className="boss-btn boss-btn-primary" disabled={busy||!reason.trim()||!record?.can_revoke} onClick={()=>{if(!record?.authorization_version||record.historical)return;void api.execute("revoke",{authorization_id:record.authorization_id,expected_version:record.authorization_version,reason:reason.trim()});setRevoke(false);}}>确认撤销</button></div>
    </Dialog.Content></Dialog.Portal></Dialog.Root>
  </div>;
}
