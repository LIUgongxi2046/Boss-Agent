import {useMemo,useState} from "react";
import {ArrowRight,ClipboardCheck,Filter} from "lucide-react";
import type {AssignmentTask,TaskListResponse} from "./BossAssignmentFlow";
import {BossPersonalCommitments,type SelfCommitment} from "./BossPersonalCommitments";
import {BossNotificationCenter} from "./BossNotificationCenter";
import {V7Panel,V7Tabs,V7Empty,V7Pagination} from "./BossV7UI";
import {replaceBossHistory} from "./boss-history";
import {useOwnerWorkspace} from "./useTechnicalWorkspace";
import type {LibraryProjection} from "./BossMeetingLibrary";
import {BossInsightList,type BossInsight} from "./BossInsightList";

type CenterTask=AssignmentTask&{related_meeting_id?:string};
type Response=TaskListResponse&{insights:BossInsight[];self_commitments?:SelfCommitment[];business_clock?:string;
  self_due_events?:{commitment_id:string;event_id:string;event_state:string;due_at:string}[];self_commitment_revisions?:SelfCommitment[]};
type Tab="全部"|"我的承诺"|"我交办的"|"通知";
type Props={data:Response|null;selectedTaskId:string;contacts:{contact_id:string;name:string}[];refreshVersion:number;
  onSelectTask:(id:string)=>void;onOpenTask:(id:string)=>void;onCreateTask:()=>void;onNavigate:(page:string)=>void;onReload:()=>void;onDirtyChange:(value:boolean)=>void;notifications?:boolean};
const TABS:Tab[]=["全部","我的承诺","我交办的","通知"];
const STATES:Record<string,string>={OPEN:"待我决定",IN_PROGRESS:"执行中",WAITING_FEEDBACK:"待反馈",OVERDUE:"逾期",RESULT_SUBMITTED:"待我验收",COMPLETED_CONFIRMED:"已完成",CANCELED:"已取消"};
function time(value?:string,zone="Asia/Shanghai"){return value?new Intl.DateTimeFormat("zh-CN",{timeZone:zone,month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false}).format(new Date(value)):"尚未约定";}
function overdue(task:AssignmentTask,clock?:string){return !!task.due_at&&!!clock&&!["CANCELED","COMPLETED_CONFIRMED"].includes(task.status)&&Date.parse(task.due_at)<Date.parse(clock);}

export function BossTaskCenter({data,selectedTaskId,contacts,refreshVersion,onSelectTask,onOpenTask,onCreateTask,onNavigate,onReload,onDirtyChange,notifications=false}:Props){
  const library=useOwnerWorkspace<LibraryProjection>("meeting-library");
  const [tab,setTab]=useState<Tab>(()=>{const value=new URLSearchParams(window.location.search).get("taskTab");return TABS.includes(value as Tab)?value as Tab:notifications?"通知":"全部";});
  const [coordinator,setCoordinator]=useState(()=>new URLSearchParams(window.location.search).get("taskCoordinator")??"");
  const [before,setBefore]=useState(()=>new URLSearchParams(window.location.search).get("taskBefore")??"");
  const [status,setStatus]=useState(()=>new URLSearchParams(window.location.search).get("taskState")??"");
  const [meeting,setMeeting]=useState(()=>new URLSearchParams(window.location.search).get("taskMeeting")??"");
  const [applied,setApplied]=useState({coordinator,before,status,meeting});
  const [page,setPage]=useState(1);
  const tasks=(data?.tasks??[]) as CenterTask[],feedback=data?.feedback??[];
  const person=(id?:string)=>contacts.find(item=>item.contact_id===id)?.name??"负责人待指定";
  const filtered=useMemo(()=>tasks.filter(task=>(!applied.coordinator||task.coordinator_id===applied.coordinator)&&
    (!applied.status||(applied.status==="OVERDUE"?overdue(task,data?.business_clock):task.status===applied.status))&&
    (!applied.meeting||task.related_meeting_id===applied.meeting)&&
    (!applied.before||task.due_at&&new Intl.DateTimeFormat("en-CA",{timeZone:task.timezone||"Asia/Shanghai",year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date(task.due_at))<=applied.before))
    .sort((a,b)=>(a.due_at??"").localeCompare(b.due_at??"")),[tasks,applied,data?.business_clock]);
  const currentPage=Math.min(page,Math.max(1,Math.ceil(filtered.length/10)));
  const selected=filtered.find(item=>item.task_id===selectedTaskId);
  const meetingIds=[...new Set(tasks.map(task=>task.related_meeting_id).filter((id):id is string=>!!id))];
  const documents=(library.data?.records??[]).filter(item=>item.kind==="document"&&item.material_state==="VALID").flatMap(item=>item.source_refs.map(source=>({...source,title:item.title})));
  function apply(){setApplied({coordinator,before,status,meeting});setPage(1);const url=new URL(window.location.href);for(const [key,value] of Object.entries({taskCoordinator:coordinator,taskBefore:before,taskState:status,taskMeeting:meeting}))value?url.searchParams.set(key,value):url.searchParams.delete(key);replaceBossHistory(url);}
  function changeTab(value:Tab){setTab(value);setPage(1);const url=new URL(window.location.href);url.searchParams.set("taskTab",value);replaceBossHistory(url);}
  return <div className="boss-task-center-view">
    <V7Tabs label="任务与承诺分类" value={tab} onChange={changeTab} items={TABS.map(id=>({id,title:id,count:!data||id==="通知"?undefined:id==="全部"?tasks.length+(data.self_commitments?.length??0):id==="我的承诺"?data.self_commitments?.length??0:tasks.length}))}/>
    {tab==="通知"?<BossNotificationCenter onNavigate={onNavigate} onOpenTask={onOpenTask} refreshVersion={refreshVersion}/>:<div className="boss-task-center-columns"><div className="boss-column">
      {tab!=="我的承诺"&&<V7Panel title="查询任务"><form className="boss-compact-query" onSubmit={event=>{event.preventDefault();apply();}}>
        <div className="boss-task-filter-grid"><label>截止日期<input type="date" value={before} onChange={event=>setBefore(event.target.value)}/></label>
          <label>任务状态<select value={status} onChange={event=>setStatus(event.target.value)}><option value="">全部状态</option>{Object.entries(STATES).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label></div>
        <details open={coordinator||meeting?true:undefined}><summary>高级查询</summary><div className="boss-task-filter-grid">
          <label>负责人<select value={coordinator} onChange={event=>setCoordinator(event.target.value)}><option value="">全部负责人</option>{contacts.map(item=><option key={item.contact_id} value={item.contact_id}>{item.name}</option>)}</select></label>
          <label>关联会议<select value={meeting} onChange={event=>setMeeting(event.target.value)}><option value="">全部会议</option>{meetingIds.map(id=><option key={id} value={id}>{library.data?.records.find(item=>item.kind==="meeting"&&item.id===id)?.title??"会议名称待读取"}</option>)}</select></label></div></details>
        <div className="boss-actions"><button className="boss-btn boss-btn-primary"><Filter size={15}/>查询</button></div>
      </form></V7Panel>}
      {library.error&&<p role="alert">{library.error}<button className="boss-btn" onClick={library.reload}>重新读取资料</button></p>}
      {(tab==="全部"||tab==="我的承诺")&&<BossPersonalCommitments sources={documents} items={data?.self_commitments??[]} businessClock={data?.business_clock} onReload={onReload} onDirtyChange={onDirtyChange} dueEvents={data?.self_due_events} revisions={data?.self_commitment_revisions}/>}
      {tab!=="我的承诺"&&<V7Panel title="任务列表"><div className="boss-task-table-heading" aria-hidden="true"><span>任务</span><span>负责人</span><span>截止时间</span><span>进展</span><span>处理结果</span></div>
        {filtered.slice((currentPage-1)*10,currentPage*10).map(task=>{
          const result=[...feedback].reverse().find(item=>item.task_id===task.task_id&&item.kind==="RESULT_SUBMITTED");
          return <button key={task.task_id} type="button" className={"boss-task-table-row "+(selectedTaskId===task.task_id?"selected":"")} onClick={()=>onSelectTask(task.task_id)}>
            <strong>{task.purpose}</strong><span>{person(task.coordinator_id)}</span><span>{time(task.due_at,task.timezone)}{overdue(task,data?.business_clock)&&<small>已经逾期</small>}</span>
            <span>{STATES[task.status]??"等待更新"}</span><span>{result?result.content:"等待负责人反馈"}</span></button>;
        })}
        {!filtered.length&&<V7Empty title={data?"当前条件没有任务":"正在读取任务"}/>}
        <V7Pagination total={filtered.length} page={currentPage} pageSize={10} onChange={setPage}/>
        {selected&&<section className="boss-workspace-item"><h3>{selected.purpose}</h3><p>{person(selected.coordinator_id)} · {time(selected.due_at,selected.timezone)}</p>
          {feedback.filter(item=>item.task_id===selected.task_id).map((item,index)=><p key={index}>{item.content}</p>)}
          <button className="boss-btn boss-btn-primary" onClick={()=>onOpenTask(selected.task_id)}><ArrowRight size={15}/>处理任务与结果</button></section>}
        <div className="boss-actions"><button className="boss-btn" onClick={onCreateTask}><ClipboardCheck size={15}/>新建交办</button></div>
      </V7Panel>}
    </div><aside className="boss-column"><V7Panel title="Boss Agent 建议">
      {data?<BossInsightList items={data.insights.filter(item=>tab==="我的承诺"?item.target_kind==="self_commitment":tab==="我交办的"?item.target_kind==="task":true)} label="查看并处理" onOpen={item=>item.target_kind==="self_commitment"?changeTab("我的承诺"):onOpenTask(item.target_id)}/>:<p>正在读取任务与承诺。</p>}
    </V7Panel></aside></div>}
  </div>;
}
