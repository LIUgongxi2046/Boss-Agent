import {useEffect,useRef,useState} from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {useClient} from "@/providers/ClientProvider";
import {useOwnerWorkspace} from "./useTechnicalWorkspace";
import {useTransaction} from "./BossAssignmentFlow";
import {BossNativeNotification} from "./BossDesktopNotifications";
import type {BusinessAlertRead} from "./BossBusinessAlerts";
import {OwnerConditions,type OwnerRecord} from "./BossOwnerRecordDetails";
import {V7Empty,V7Fact,V7Panel,V7Pagination,V7ReadState,V7Tabs} from "./BossV7UI";
import {replaceBossHistory} from "./boss-history";

type NotificationRecord=OwnerRecord&{task_state?:string|null;participation_reason?:string|null};
type History={projection:"notification-history";records:NotificationRecord[];namespace:string;read_at:string};
type EventRecord={event_id:string;version:string;state:string;impact:string;due_at:string;task_id?:string};
type Current={projection:"notifications";source_type:"SIMULATED";namespace:string;read_at:string;data_version:string;
  events:EventRecord[];reminders:{event_id:string;version:string;state:string;until?:string|null}[];
  notifications:{event_id:string;event_version:string;state:string;created_at?:string;business_at?:string}[];
  dispatches:{event_id:string;event_version:string;state:string;reason?:string|null;business_at:string;rule_version?:string;owner_notice_version?:string}[];
  business_alerts:BusinessAlertRead};
type Props={onNavigate:(page:string)=>void;onOpenTask:(taskId:string)=>void;refreshVersion:number};
const TABS=[{id:"ALL",title:"全部"},{id:"UNREAD",title:"未读"},{id:"ACKNOWLEDGED",title:"已知晓"},{id:"SNOOZED",title:"已暂缓"},{id:"CLOSED",title:"已关闭"}] as const;
type Tab=typeof TABS[number]["id"];
type View={tab:Tab;scope:string;date:string;query:string;selected:string;page:number};
const EMPTY:View={tab:"ALL",scope:"",date:"",query:"",selected:"",page:1};
const calendarDate=new Intl.DateTimeFormat("en-CA",{timeZone:"Asia/Shanghai",year:"numeric",month:"2-digit",day:"2-digit"});
function fact(record:OwnerRecord,label:string){return record.values.find(value=>value.label===label)?.value??null;}

export function BossNotificationCenter(props:Props){
  const {token}=useClient(),identity=useRef({token,sequence:0});
  if(identity.current.token!==token)identity.current={token,sequence:identity.current.sequence+1};
  return <NotificationCenter key={identity.current.sequence} {...props}/>;
}
function NotificationCenter({onNavigate,onOpenTask,refreshVersion}:Props){
  const api=useOwnerWorkspace<History>("notification-history"),{getToken}=useClient();
  const [live,setLive]=useState<Current|null>(null),[liveLoading,setLiveLoading]=useState(false),[liveError,setLiveError]=useState(""),[revision,setRevision]=useState(0);
  const [view,setView]=useState<View>(()=>window.history.state?.bossNotificationCenter??EMPTY),[form,setForm]=useState({scope:view.scope,date:view.date,query:view.query});
  const [snooze,setSnooze]=useState(false),[until,setUntil]=useState(""),[formError,setFormError]=useState("");
  const reload=()=>{api.reload();setRevision(value=>value+1);};
  const reminder=useTransaction(reload,undefined,undefined,"reminder"),alert=useTransaction(reload,undefined,undefined,"alerts");
  const busy=reminder.busy||alert.busy;
  const initialRefresh=useRef(refreshVersion);
  useEffect(()=>{if(initialRefresh.current===refreshVersion)return;initialRefresh.current=refreshVersion;reload();},[refreshVersion]);
  useEffect(()=>{
    if(!api.data)return;
    const controller=new AbortController(),namespace=api.data.namespace;
    setLive(null);setLiveLoading(true);setLiveError("");
    void fetch("/api/boss/ui/workspace/notifications",{headers:{Authorization:"Bearer "+getToken()},cache:"no-store",signal:controller.signal}).then(async response=>{
      if(response.status===401)window.dispatchEvent(new Event("boss-auth-expired"));
      if(!response.ok)throw new Error("当前提醒读取失败，HTTP "+response.status);
      const value=await response.json() as Current;
      if(value.projection!=="notifications"||value.source_type!=="SIMULATED"||value.namespace!==namespace)throw new Error("当前提醒与通知目录的执行空间不一致");
      if(controller.signal.aborted)return;setLive(value);setLiveLoading(false);
    }).catch(error=>{if(controller.signal.aborted)return;setLiveError(error.message);setLiveLoading(false);});
    return()=>controller.abort();
  },[api.data?.namespace,revision,getToken]);
  const current=!api.loading&&!api.error&&!liveLoading&&!liveError&&live?.namespace===api.data?.namespace?live:null;
  function binding(record:NotificationRecord){
    if(!current||record.historical||record.namespace!==current.namespace)return null;
    const business=current.business_alerts.items.find(item=>item.event_id===record.target_id&&item.event_version===record.version&&(!item.notification||item.notification.event_version===record.version)&&record.id===record.namespace+":notification:"+item.event_id+":alert");
    if(business)return {kind:"business" as const,event:business,state:business.reminder?.state??"UNREAD",version:business.event_version};
    const event=current.events.find(item=>item.event_id===record.target_id&&item.version===record.version);
    const saved=current.notifications.find(item=>item.event_id===record.target_id&&item.event_version===record.version);
    if(!event||!saved||record.id!==record.namespace+":notification:"+event.event_id+":"+event.version)return null;
    const decision=current.reminders.find(item=>item.event_id===event.event_id);
    return {kind:"event" as const,event,state:decision?.state??"UNREAD",version:event.version,decision};
  }
  const scoped=(api.data?.records??[]).filter(record=>(!view.scope||(view.scope==="current"?!record.historical:record.historical))&&(!view.query||[record.title,record.target_id??"",record.task_id??"",...record.source_ids].some(value=>value.toLocaleLowerCase().includes(view.query.toLocaleLowerCase())))&&(!view.date||record.sources.some(source=>source.published_at&&calendarDate.format(new Date(source.published_at))===view.date)));
  const records=scoped.filter(record=>view.tab==="ALL"||binding(record)?.state===view.tab);
  const page=Math.min(view.page,Math.max(1,Math.ceil(records.length/10)));
  const selected=records.find(record=>record.id===view.selected),selectedBinding=selected?binding(selected):null;
  const canAct=Boolean(selectedBinding&&selectedBinding.state!=="CLOSED"&&selectedBinding.event.state!=="CANCELED"&&(selectedBinding.kind==="event"||selectedBinding.event.reminder&&selectedBinding.event.adoption_state==="CURRENT"));
  const canClose=Boolean(selectedBinding&&selectedBinding.state!=="CLOSED"&&(selectedBinding.kind==="business"?selectedBinding.event.reminder:selectedBinding.event.state!=="CANCELED"));
  const taskIds=[...new Set([...(selected?.task_id?[selected.task_id]:[]),...(selectedBinding?.kind==="business"?selectedBinding.event.assignment_references.flatMap(row=>typeof row.task_id==="string"?[row.task_id]:[]):[])])];
  const reason=selectedBinding?.kind==="business"?selectedBinding.event.facts?.participation_reason:null;
  useEffect(()=>{const state=window.history.state??{};window.history.replaceState({...state,bossNotificationCenter:view},"",window.location.href);},[view]);
  function update(next:View){setView(next);setSnooze(false);setUntil("");setFormError("");}
  function openOriginal(record:NotificationRecord){const url=new URL(window.location.href);url.searchParams.set("bossHistoryRecord",record.id);replaceBossHistory(url);onNavigate("D09");}
  function openCurrent(){if(!selectedBinding)return;const url=new URL(window.location.href);url.searchParams.set("bossEvent",selectedBinding.event.event_id);url.searchParams.set("bossEventVersion",selectedBinding.version);replaceBossHistory(url);onNavigate("F02");}
  function decide(action:"ack"|"snooze"|"close"){
    if(!selected||!selectedBinding||!(action==="close"?canClose:canAct)||busy)return;
    if(action==="snooze"&&!/^\d{4}-\d\d-\d\dT\d\d:\d\d$/.test(until)){setFormError("请选择完整的暂缓日期与时间。");return;}
    const fields:Record<string,unknown>={event_id:selectedBinding.event.event_id,event_version:selectedBinding.version};
    if(action==="snooze")fields.until=until+":00+08:00";
    const preview=["通知编号："+selected.id,"事件版本："+selectedBinding.version,"当前处理状态："+selectedBinding.state,"执行空间："+selected.namespace,...(action==="snooze"?["暂缓至："+fields.until]:[]),"当前动作仅修改提醒处理状态，任务完成与源事件状态分别核查。"];
    if(selectedBinding.kind==="business"){
      fields.expected_version=selectedBinding.event.reminder_version;fields.review_sha256=selectedBinding.event.review_sha256;
      alert.propose(("boss.alert."+action) as "boss.alert.ack"|"boss.alert.snooze"|"boss.alert.close",fields,{ack:"确认知晓",snooze:"确认暂缓提醒",close:"确认关闭提醒"}[action],preview);
    }else{
      fields.reminder_version=selectedBinding.decision?.version??"0";
      reminder.propose(("boss.reminder."+action) as "boss.reminder.ack"|"boss.reminder.snooze"|"boss.reminder.close",fields,{ack:"确认知晓",snooze:"确认暂缓提醒",close:"确认关闭提醒"}[action],preview);
    }
    setSnooze(false);setFormError("");
  }
  return <div className="boss-notification-center">
    <V7ReadState loading={api.loading||liveLoading} error={api.error||liveError} onReload={reload}/>
    <div className="boss-notification-columns"><div className="boss-column"><V7Panel title="对象与记录">
      <V7Tabs label="通知处理状态" value={view.tab} onChange={tab=>update({...view,tab,page:1,selected:""})} items={TABS.map(item=>({...item,count:api.data&&(item.id==="ALL"||current)?scoped.filter(record=>item.id==="ALL"||binding(record)?.state===item.id).length:undefined}))}/>
      <form className="boss-v7-filter-bar" onSubmit={event=>{event.preventDefault();update({...view,...form,query:form.query.trim(),page:1,selected:""});}}><label>通知范围<select value={form.scope} onChange={event=>setForm({...form,scope:event.target.value})}><option value="">全部获准空间</option><option value="current">当前空间</option><option value="history">历史空间</option></select></label><label>来源日期（Asia/Shanghai）<input type="date" value={form.date} onChange={event=>setForm({...form,date:event.target.value})}/></label><label>关联对象<input value={form.query} onChange={event=>setForm({...form,query:event.target.value})} placeholder="事项、任务或来源编号"/></label><button className="boss-btn boss-btn-primary" disabled={api.loading}>查询 / 应用</button></form>
      <div className="boss-v7-table-scroll"><table className="boss-v7-table"><thead><tr><th>事项与关联对象</th><th>参与原因</th><th>规则版本</th><th>处理与任务状态</th><th>来源时间</th></tr></thead><tbody>{records.slice((page-1)*10,page*10).map(record=>{
        const bound=binding(record),participation=bound?.kind==="business"?bound.event.facts?.participation_reason:null;
        return <tr key={record.id} aria-selected={selected?.id===record.id}><td><button className="boss-v7-text-button" onClick={()=>update({...view,selected:record.id})}>{record.title}</button><small>{record.task_id??record.target_id??"尚无关联对象"}</small><small>{record.historical?"历史空间":"当前空间"} · {record.namespace}</small></td><td>{participation??record.participation_reason??fact(record,"参与原因")??"参与原因尚未提供"}</td><td>{fact(record,"规则版本")??"当时规则版本未提供"}</td><td>{bound?TABS.find(tab=>tab.id===bound.state)?.title??bound.state:"原通知只读"}<small>任务：{record.task_state??"当前状态尚未提供"}</small><small>原通知：{record.state}</small></td><td>{record.sources.length?record.sources.map(source=><small key={source.source_id+source.version}>{source.source_id} · {source.published_at??"来源时间未提供"}</small>):"没有已读取的来源时间"}</td></tr>;
      })}</tbody></table></div>
      {!records.length&&<V7Empty title={api.loading?"正在读取通知记录":api.error?"通知记录读取失败":view.tab!=="ALL"&&!current?"当前提醒状态待读取":api.data?"当前条件下没有已保存通知":"通知待读取"}>列表仅显示当前本人获准的正式通知记录。</V7Empty>}{api.data&&(view.tab==="ALL"||current)&&<V7Pagination total={records.length} pageSize={10} page={page} onChange={page=>setView({...view,page})}/>}
      <p className="boss-v7-note">状态分类采用当前提醒记录。历史空间的本人处理状态尚未提供，原通知可在“全部”中查看。</p>
    </V7Panel></div><aside className="boss-column"><V7Panel title="选中记录">
      {selected?<><h3>{selected.title}</h3><V7Fact label="原通知时间">{selected.created_at||"尚未提供"}</V7Fact><V7Fact label="原事件版本">{selected.version||"尚未提供"}</V7Fact><V7Fact label="触发依据">{reason??selected.participation_reason??fact(selected,"参与原因")??"尚未提供"}</V7Fact><V7Fact label="原规则版本">{fact(selected,"规则版本")??"尚未提供"}</V7Fact><V7Fact label="原数据集">{selected.dataset_id}</V7Fact><V7Fact label="原执行空间">{selected.namespace}</V7Fact><OwnerConditions record={selected}/><div className="boss-actions"><button className="boss-btn" onClick={()=>openOriginal(selected)}>查看原通知与依据</button>{selectedBinding&&<button className="boss-btn" onClick={openCurrent}>打开当前事项</button>}{taskIds.map(id=><button key={id} className="boss-btn" onClick={()=>onOpenTask(id)}>打开任务 {id}</button>)}</div></>:<V7Empty title="尚未选择通知">选择一条已保存通知，查看依据和当前可用操作。</V7Empty>}
    </V7Panel><V7Panel title="状态与核查"><V7Fact label="当前提醒状态">{selectedBinding?TABS.find(tab=>tab.id===selectedBinding.state)?.title??selectedBinding.state:"当前对象尚未匹配"}</V7Fact><V7Fact label="原通知状态">{selected?.state??"尚未选择"}</V7Fact><V7Fact label="当前事件状态">{selectedBinding?.event.state??"尚未取得"}</V7Fact><V7Fact label="当前任务状态">{selected?.task_state??"尚未提供"}</V7Fact><V7Fact label="目录读取时间">{api.data?.read_at??"尚未读取"}</V7Fact><V7Fact label="当前状态读取时间">{current?.read_at??"尚未读取"}</V7Fact>{selected&&!selectedBinding&&<p className="boss-v7-note">原记录保持只读。取得当前空间、对象版本和提醒条件后，才可执行当前动作。</p>}<button className="boss-btn" disabled={api.loading||liveLoading||busy} onClick={reload}>重读当前状态</button><button className="boss-btn" onClick={()=>onNavigate("N08")}>查看本人通知要求</button>{selectedBinding&&<details><summary>系统通知状态</summary><BossNativeNotification eventId={selectedBinding.event.event_id} eventVersion={selectedBinding.version}/></details>}</V7Panel></aside></div>
    <footer className="boss-owner-actions"><button className="boss-btn boss-btn-primary" disabled={!selected||taskIds.length!==1} onClick={()=>onOpenTask(taskIds[0])}>打开任务</button><button className="boss-btn" disabled={!canAct||busy} onClick={()=>decide("ack")}>知晓</button><button className="boss-btn" disabled={!canAct||busy} onClick={()=>{setUntil("");setFormError("");setSnooze(true);}}>选择暂缓时间</button><button className="boss-btn" disabled={!canClose||busy} onClick={()=>decide("close")}>关闭提醒</button></footer>
    {reminder.notice&&<p role="status">{reminder.notice}</p>}{alert.notice&&<p role="status">{alert.notice}</p>}{reminder.dialog}{reminder.recovery}{alert.dialog}{alert.recovery}
    <Dialog.Root open={snooze} onOpenChange={setSnooze}><Dialog.Portal><Dialog.Overlay className="boss-v7-dialog-overlay"/><Dialog.Content className="boss-v7-dialog"><Dialog.Title>选择暂缓时间</Dialog.Title><Dialog.Description>暂缓只改变本次提醒时间，任务期限保持当前正式记录。</Dialog.Description><V7Fact label="当前事项">{selected?.title??"尚未选择"}</V7Fact><label className="boss-field">暂缓至（Asia/Shanghai）<input type="datetime-local" value={until} onChange={event=>setUntil(event.target.value)}/></label>{formError&&<p role="alert" className="boss-status boss-status-error">{formError}</p>}<div className="boss-actions"><Dialog.Close asChild><button className="boss-btn">取消</button></Dialog.Close><button className="boss-btn boss-btn-primary" disabled={!canAct||busy||!until} onClick={()=>decide("snooze")}>核查暂缓动作</button></div></Dialog.Content></Dialog.Portal></Dialog.Root>
  </div>;
}
