import { useMemo, useState } from "react";
import { ArrowRight, ClipboardCheck, Clock3, FileSearch,
  Filter, FolderOpen, RefreshCw, ShieldCheck } from "lucide-react";
import type { AssignmentTask, TaskFeedback, TaskListResponse } from "./BossAssignmentFlow";
import { BossPersonalCommitments, type SelfCommitment } from "./BossPersonalCommitments";
import {V7Panel, V7Tabs, V7Empty} from "./BossV7UI";
import {replaceBossHistory} from "./boss-history";
type CenterTask = AssignmentTask & { related_meeting_id?: string };

type Historical = {task_id:string;status:string;due_at?:string;purpose?:string};
type Response = TaskListResponse & {
  historical_commitment?:Historical|null;
  self_commitments?:SelfCommitment[];
  business_clock?:string;
  read_at?:string;
  source_type?:string;
  self_due_events?:{commitment_id:string;event_id:string;event_state:string;due_at:string}[];
  self_commitment_revisions?:SelfCommitment[];
};
type Tab = "全部任务"|"本人承诺"|"他人交办"|"等待反馈"|"待核查结果";
type Props = {
  data:Response|null;
  selectedTaskId:string;
  onSelectTask:(id:string)=>void;
  onOpenTask:(id:string)=>void;
  onCreateTask:()=>void;
  onNavigate:(page:string)=>void;
  onReload:()=>void;
  onDirtyChange:(value:boolean)=>void;
};
const TABS:Tab[]=["全部任务","本人承诺","他人交办","等待反馈","待核查结果"];
function labelTime(value?:string){return value?value.replace("T"," "):"未提供";}
function Display({name,value}:{name:string;value?:string|number|null}){
  return <div className="boss-kv"><span>{name}</span><strong>{value??"未提供"}</strong></div>;
}
function countEvidence(task:AssignmentTask,feedback:TaskFeedback[]){
  const own=feedback.filter(x=>x.task_id===task.task_id);
  return own.flatMap(x=>x.evidence_refs||[]).length;
}
function dueStatus(task:AssignmentTask,clock?:string){
  if(!task.due_at||!clock)return "期限状态未核查";
  if(["CANCELED","COMPLETED_CONFIRMED"].includes(task.status))return "历史终态";
  const due=Date.parse(task.due_at),at=Date.parse(clock);
  if(!Number.isFinite(due)||!Number.isFinite(at))return "期限不可解析";
  return due<at?"已超模拟业务时钟":"当前期限未超过模拟业务时钟";
}
export function BossTaskCenter({data,selectedTaskId,onSelectTask,onOpenTask,onCreateTask,onNavigate,onReload,onDirtyChange}:Props){
  const [tab,setTab]=useState<Tab>(()=>{const value=new URLSearchParams(window.location.search).get("taskTab");return TABS.includes(value as Tab)?value as Tab:"全部任务";});
  const [coordinator,setCoordinator]=useState(()=>new URLSearchParams(window.location.search).get("taskCoordinator")??"");
  const [before,setBefore]=useState(()=>new URLSearchParams(window.location.search).get("taskBefore")??"");
  const [status,setStatus]=useState(()=>new URLSearchParams(window.location.search).get("taskState")??"");
  const [meeting,setMeeting]=useState(()=>new URLSearchParams(window.location.search).get("taskMeeting")??"");
  const [applied,setApplied]=useState({coordinator,before,status,meeting});
  const [page,setPage]=useState(0);
  const tasks=(data?.tasks||[]) as CenterTask[];
  const feedback=data?.feedback||[];
  const messages=data?.linked_messages||[];
  const events=data?.task_due_events||[];
  const contacts=Array.from(new Set(tasks.map(x=>x.coordinator_id).filter(
    (x):x is string=>typeof x==="string"&&x.length>0)));
  const meetings=Array.from(new Set(tasks.map(x=>x.related_meeting_id).filter(
    (x):x is string=>typeof x==="string"&&x.length>0)));
  const stateNames=Array.from(new Set(tasks.map(x=>x.status).filter(Boolean)));
  const filtered=useMemo(()=>{
    if(tab==="本人承诺")return [];
    let subset=tasks.filter(t=>tab==="全部任务"||tab==="他人交办"||
      tab==="等待反馈"&&["WAITING_FEEDBACK","IN_PROGRESS"].includes(t.status)||
      tab==="待核查结果"&&t.status==="RESULT_SUBMITTED");
    if(applied.coordinator)subset=subset.filter(t=>t.coordinator_id===applied.coordinator);
    if(applied.status)subset=subset.filter(t=>t.status===applied.status);
    if(applied.meeting)subset=subset.filter(t=>t.related_meeting_id===applied.meeting);
    if(applied.before)subset=subset.filter(t=>t.due_at&&t.timezone&&new Intl.DateTimeFormat("en-CA",{timeZone:t.timezone,year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date(t.due_at))<=applied.before);
    return [...subset].sort((a,b)=>(a.due_at||"").localeCompare(b.due_at||"")||
      a.task_id.localeCompare(b.task_id));
  },[tasks,tab,applied]);
  const pageSize=10;
  const pages=Math.max(1,Math.ceil(filtered.length/pageSize));
  const currentPage=Math.min(page,pages-1);
  const shown=filtered.slice(currentPage*pageSize,currentPage*pageSize+pageSize);
  const selected=filtered.find(t=>t.task_id===selectedTaskId)||shown[0]||null;
  const chosenFeedback=feedback.filter(f=>selected&&f.task_id===selected.task_id);
  const chosenMessages=messages.filter(f=>selected&&f.task_id===selected.task_id);
  const due=events.find(e=>selected&&e.task_id===selected.task_id);
  const extension=[...chosenFeedback].reverse().find(f=>f.kind==="EXTENSION_REQUEST");
  const submitted=[...chosenFeedback].reverse().find(f=>f.kind==="RESULT_SUBMITTED");

  function apply(){setApplied({coordinator,before,status,meeting});setPage(0);const url=new URL(window.location.href);for(const [key,value] of Object.entries({taskCoordinator:coordinator,taskBefore:before,taskState:status,taskMeeting:meeting}))value?url.searchParams.set(key,value):url.searchParams.delete(key);replaceBossHistory(url);}
  function changeTab(value:Tab){setTab(value);setPage(0);const url=new URL(window.location.href);url.searchParams.set("taskTab",value);replaceBossHistory(url);}
  return <div className="boss-task-center-view">
    <div className="boss-task-center-columns"><div className="boss-column"><section className="boss-panel boss-task-center">
      <div className="boss-panel-head"><h2>任务与承诺</h2><small>当前范围与筛选</small></div>
      <V7Tabs label="任务与承诺分类" value={tab} onChange={changeTab} items={TABS.map(key=>({id:key,title:key,count:!data?undefined:
            key==="全部任务"?tasks.length+(data.self_commitments?.length||0):
            key==="本人承诺"?((data.self_commitments?.length||0)+(data.historical_commitment?1:0)):
            key==="他人交办"?tasks.length:
            key==="等待反馈"?tasks.filter(t=>["WAITING_FEEDBACK","IN_PROGRESS"].includes(t.status)).length:
            tasks.filter(t=>t.status==="RESULT_SUBMITTED").length}))}/>
      <div className="boss-task-filter-grid" style={tab==="本人承诺"?{display:"none"}:undefined}>
        <label>负责人
          <select value={coordinator} onChange={e=>setCoordinator(e.target.value)}>
            <option value="">全部已知负责人</option>
            {contacts.map(id=><option key={id} value={id}>{id}</option>)}
          </select>
        </label>
        <label>有效期限
          <input type="date" value={before} onChange={e=>setBefore(e.target.value)}
            aria-label="截止日期之前"/>
        </label>
        <label>任务状态
          <select value={status} onChange={e=>setStatus(e.target.value)}>
            <option value="">全部状态</option>
            {stateNames.map(key=><option key={key} value={key}>{key}</option>)}
          </select>
        </label>
        <label>关联会议
          <select value={meeting} onChange={e=>setMeeting(e.target.value)}>
            <option value="">全部会议</option>
            {meetings.map(id=><option key={id} value={id}>{id}</option>)}
          </select>
        </label>
        <button type="button" className="boss-btn boss-btn-primary" onClick={apply}>
          <Filter size={15}/> 查询 / 应用
        </button>
      </div>
    </section>
    <details className="boss-task-self-records" open={tab==="本人承诺"?true:undefined} hidden={tab!=="本人承诺"&&tab!=="全部任务"}><summary>本人承诺 · {data?`${data.self_commitments?.length??0} 项当前记录`:"尚未读取"}</summary><BossPersonalCommitments items={data?.self_commitments||[]} businessClock={data?.business_clock} onReload={onReload} onDirtyChange={onDirtyChange} dueEvents={data?.self_due_events} revisions={data?.self_commitment_revisions}/></details>
        <section className="boss-panel">
          <div className="boss-panel-head"><h2>任务列表与结果核查</h2>
            <small>负责人、有效期限与当前结果</small></div>
          {tab==="本人承诺" ? <>
            {data?.historical_commitment?<div className="boss-workspace-item">
              <strong>{data.historical_commitment.task_id}</strong>
              <Display name="历史状态" value={data.historical_commitment.status}/>
              <Display name="历史原定期限" value={labelTime(data.historical_commitment.due_at)}/>
              <p>这是已批准的历史背景快照，不属于当前生成的任务，不允许在这里代办完成。</p>
            </div>:<div className="boss-empty"><FolderOpen size={19}/>
              <div><strong>没有已读取的历史承诺快照</strong><p>当前本人承诺在上方独立查询与管理。</p></div>
            </div>}
          </>:<>
            <div className="boss-task-table-heading" aria-hidden="true">
              <span>任务目的</span><span>唯一负责人</span><span>期限与时区</span>
              <span>当前进展</span><span>证据状态</span>
            </div>
            {shown.length?shown.map(task=>{
              const f=feedback.filter(x=>x.task_id===task.task_id);
              return <button key={task.task_id} type="button" className={
                "boss-task-table-row "+(selected?.task_id===task.task_id?"selected":"")}
                onClick={()=>onSelectTask(task.task_id)}>
                <span><strong>{task.purpose||"未提供任务目的"}</strong><small>{task.task_id}</small></span>
                <span>{task.coordinator_id||"待核查"}</span>
                <span>{labelTime(task.due_at)}<small>{task.timezone||"时区待核查"}</small></span>
                <span>{task.status}<small>{f.length} 条署名反馈</small></span>
                <span>{countEvidence(task,feedback)} 条引用
                  <small>{task.source_reference_state==="NEEDS_REVIEW"?"来源需复核":"来源有效性："+(task.source_reference_state||"未知")}</small>
                </span>
              </button>;
            }):<div className="boss-empty"><FolderOpen size={19}/>
              <div><strong>{data?"当前查询条件没有记录":"任务列表尚未读取"}</strong><p>查询后显示当前任务、负责人和证据状态。</p></div>
            </div>}
            <footer className="boss-task-table-footer">
              <span>结果数：{data?filtered.length:"尚未读取"} · 每页 10 条</span>
              <div className="boss-actions">
                <button className="boss-btn" type="button" disabled={currentPage===0}
                  onClick={()=>setPage(n=>Math.max(0,n-1))}>上一页</button>
                <span>{currentPage+1} / {pages}</span>
                <button className="boss-btn" type="button" disabled={currentPage>=pages-1}
                  onClick={()=>setPage(n=>Math.min(pages-1,n+1))}>下一页</button>
              </div>
            </footer>
          </>}
          <div className="boss-actions">
            <button type="button" className="boss-btn boss-btn-primary"
              onClick={onCreateTask}><ClipboardCheck size={15}/> 创建交办</button>
            <button type="button" className="boss-btn" onClick={onReload}><RefreshCw size={15}/> 重读最新状态</button>
            <button type="button" className="boss-btn" onClick={()=>onNavigate("F01")}>返回今日</button>
          </div>
        </section>
      </div>
      <aside className="boss-column">
        <section className="boss-panel">
          <div className="boss-panel-head"><h2>当前选中任务</h2>
            <small>只读预览 · 重大动作进入 F06 本人确认</small></div>
          {selected?<>
            <Display name="任务 ID" value={selected.task_id}/>
            <Display name="正式状态" value={selected.status}/>
            <Display name="内容版本" value={selected.version}/>
            <Display name="当前期限" value={labelTime(selected.due_at)}/>
            <Display name="逾期属性" value={dueStatus(selected,data?.business_clock)}/>
            <Display name="负责人" value={selected.coordinator_id}/>
            <Display name="来源状态" value={selected.source_reference_state}/>
            <Display name="来源引用" value={selected.source_refs?.join("、")}/>
            <Display name="当前证据" value={(submitted?.evidence_refs||[]).join("、")||"尚无结果证据"}/>
            <Display name="延期申请" value={extension?.proposed_due_at?labelTime(extension.proposed_due_at):"无"}/>
            <Display name="消息状态" value={chosenMessages.length+" 条模拟发件；未证明实际外部送达"}/>
            <Display name="提醒事件" value={due?.event_state||"尚未创建"}/>
            {selected.origin_minute_id&&
              <div className="boss-status boss-status-warn">
                <ShieldCheck size={15}/> 关联纪要 {selected.origin_minute_id}
                {" v"+(selected.origin_minute_version||"未知")+" / "+
                  (selected.origin_entry_id||"未知")}。
                来源变化后需重新核查，不能自动重新发送。
              </div>}
            <div className="boss-actions">
              <button type="button" className="boss-btn boss-btn-primary"
                onClick={()=>onOpenTask(selected.task_id)}>
                <ArrowRight size={15}/> 进入任务详情
              </button>
              <button type="button" className="boss-btn" onClick={()=>onOpenTask(selected.task_id)}>
                <FileSearch size={15}/> 查看反馈及证据
              </button>
            </div>
          </>:<div className="boss-empty"><FolderOpen size={19}/>
            <div><strong>尚未选择当前任务</strong><p>历史承诺与实际交办分别显示，不生成示例任务。</p></div>
          </div>}
        </section>
        <section className="boss-panel">
          <div className="boss-panel-head"><h2>状态与核查</h2></div>
          <Display name="当前模拟业务时钟" value={data?.business_clock?labelTime(data.business_clock):"未提供"}/>
          <Display name="实际交办对象" value={data?tasks.length:"尚未读取"}/>
          <Display name="结果待本人核查" value={data?tasks.filter(t=>t.status==="RESULT_SUBMITTED").length:"尚未读取"}/>
          <Display name="真实送达状态" value="未验证"/>
          <div className="boss-status"><Clock3 size={15}/>
            任务完成、延期、取消和催办必须进入当前对象的 F06 授权步骤；不会在总览中自动确认全部完成。
          </div>
        </section>
      </aside>
    </div>
    <V7Panel title="结果提交与本人确认" description="提交结果后，继续核查证据与当前任务版本。">
      {tasks.some(task=>feedback.some(item=>item.task_id===task.task_id&&item.kind==="RESULT_SUBMITTED"))?<div className="boss-v7-table-scroll"><table className="boss-v7-table"><thead><tr><th>任务</th><th>最近提交</th><th>证据</th><th>本人确认</th><th>继续处理</th></tr></thead><tbody>
        {tasks.filter(task=>feedback.some(item=>item.task_id===task.task_id&&item.kind==="RESULT_SUBMITTED")).map(task=>{
          const result=[...feedback].reverse().find(item=>item.task_id===task.task_id&&item.kind==="RESULT_SUBMITTED")!;
          return <tr key={task.task_id}><td>{task.purpose||task.task_id}</td><td>{result.author_contact_id}<small>{labelTime(result.submitted_at)}</small></td><td>{result.evidence_refs?.length??0} 条{task.result_evidence_requires_resubmission&&<small>需要重新提交</small>}</td><td>{task.status==="COMPLETED_CONFIRMED"?"已确认完成":task.status==="CANCELED"?"任务已取消":"等待本人核查"}</td><td><button className="boss-btn" onClick={()=>onOpenTask(task.task_id)}>核查当前结果</button></td></tr>;
        })}
      </tbody></table></div>:<V7Empty title="尚无已提交结果">收到负责人提交后，在此核查证据与本人确认状态。</V7Empty>}
    </V7Panel>
  </div>;
}
