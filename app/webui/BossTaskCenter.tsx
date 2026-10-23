import { useMemo, useState } from "react";
import { ArrowRight, ClipboardCheck, Clock3, FileSearch,
  Filter, FolderOpen, RefreshCw, ShieldCheck } from "lucide-react";
import type { AssignmentTask, TaskFeedback, TaskListResponse } from "./BossAssignmentFlow";
type CenterTask = AssignmentTask & { related_meeting_id?: string };

type Historical = {task_id:string;status:string;due_at:string;purpose?:string};
type Response = TaskListResponse & {
  historical_commitment?:Historical|null;
  business_clock?:string;
  read_at?:string;
  source_type?:"SIMULATED";
};
type Tab = "本人承诺"|"他人交办"|"等待反馈"|"待核查结果";
type Props = {
  data:Response|null;
  selectedTaskId:string;
  onSelectTask:(id:string)=>void;
  onOpenTask:(id:string)=>void;
  onNavigate:(page:string)=>void;
  onReload:()=>void;
};
const TABS:Tab[]=["本人承诺","他人交办","等待反馈","待核查结果"];
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
export function BossTaskCenter({data,selectedTaskId,onSelectTask,onOpenTask,onNavigate,onReload}:Props){
  const [tab,setTab]=useState<Tab>("他人交办");
  const [coordinator,setCoordinator]=useState("");
  const [before,setBefore]=useState("");
  const [status,setStatus]=useState("");
  const [meeting,setMeeting]=useState("");
  const [applied,setApplied]=useState({coordinator:"",before:"",status:"",meeting:""});
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
    let subset=tasks.filter(t=>tab==="他人交办"||
      tab==="等待反馈"&&["WAITING_FEEDBACK","IN_PROGRESS"].includes(t.status)||
      tab==="待核查结果"&&t.status==="RESULT_SUBMITTED");
    if(applied.coordinator)subset=subset.filter(t=>t.coordinator_id===applied.coordinator);
    if(applied.status)subset=subset.filter(t=>t.status===applied.status);
    if(applied.meeting)subset=subset.filter(t=>t.related_meeting_id===applied.meeting);
    if(applied.before)subset=subset.filter(t=>t.due_at&&t.due_at.slice(0,10)<=applied.before);
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

  function apply(){setApplied({coordinator,before,status,meeting});setPage(0);}
  function changeTab(value:Tab){setTab(value);setPage(0);}
  return <>
    <section className="boss-panel boss-task-center">
      <div className="boss-minutes-tabs" role="tablist" aria-label="任务与承诺分类">
        {TABS.map(key=><button type="button" role="tab" key={key}
          aria-selected={tab===key} className={tab===key?"selected":""}
          onClick={()=>changeTab(key)}>
          {key}
          <span>{key==="本人承诺"?(data?.historical_commitment?1:0):
            key==="他人交办"?tasks.length:
            key==="等待反馈"?tasks.filter(t=>["WAITING_FEEDBACK","IN_PROGRESS"].includes(t.status)).length:
            tasks.filter(t=>t.status==="RESULT_SUBMITTED").length}</span>
        </button>)}
      </div>
      <div className="boss-task-filter-grid">
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
    <div className="boss-columns">
      <div className="boss-column">
        <section className="boss-panel">
          <div className="boss-panel-head"><h2>对象与正式业务记录</h2>
            <small>原版 v6 五列信息 · 数据来自当前有权 SQLite 对象</small></div>
          {tab==="本人承诺" ? <>
            {data?.historical_commitment?<div className="boss-workspace-item">
              <strong>{data.historical_commitment.task_id}</strong>
              <Display name="历史状态" value={data.historical_commitment.status}/>
              <Display name="历史原定期限" value={labelTime(data.historical_commitment.due_at)}/>
              <p>这是已批准的历史背景快照，不属于当前生成的任务，不允许在这里代办完成。</p>
            </div>:<div className="boss-empty"><FolderOpen size={19}/>
              <div><strong>没有已核验的本人承诺</strong><p>没有来源时不把他人交办视为老板本人承诺。</p></div>
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
              <div><strong>当前查询条件没有记录</strong><p>可修改筛选条件或前往 F06 创建真实交办，不能把空结果当作零经营数据。</p></div>
            </div>}
            <footer className="boss-task-table-footer">
              <span>结果数：{filtered.length} · 每页 10 条</span>
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
              onClick={()=>onNavigate("F06")}><ClipboardCheck size={15}/> 创建交办</button>
            <button type="button" className="boss-btn" onClick={onReload}><RefreshCw size={15}/> 重读最新状态</button>
            <button type="button" className="boss-btn" onClick={()=>onNavigate("F01")}>返回今日</button>
          </div>
        </section>
      </div>
      <div className="boss-column">
        <section className="boss-panel">
          <div className="boss-panel-head"><h2>选中任务</h2>
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
          <Display name="实际交办对象" value={tasks.length}/>
          <Display name="结果待本人核查" value={tasks.filter(t=>t.status==="RESULT_SUBMITTED").length}/>
          <Display name="真实送达状态" value="未验证"/>
          <div className="boss-status"><Clock3 size={15}/>
            任务完成、延期、取消和催办必须进入当前对象的 F06 授权步骤；不会在总览中自动确认全部完成。
          </div>
        </section>
      </div>
    </div>
  </>;
}
