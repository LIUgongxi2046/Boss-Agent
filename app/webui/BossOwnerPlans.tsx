import {useEffect,useRef,useState} from "react";
import {useTransaction} from "./BossAssignmentFlow";
import {V7Panel,V7Empty,V7Fact,V7Pagination,V7ReadState} from "./BossV7UI";

export type OwnerPlan={plan_id:string;version:string;state:string;purpose:string;event_ids:string[];timezone:string;not_before:string;authorization_id:string;plan_type?:string;next_run_at?:string|null;rule_version?:string};
export type OwnerPlanProjection={
  plans:OwnerPlan[];events:{event_id:string;version:string;state:string;due_at:string}[];
  results:{event_id:string;state:string;business_at:string;owner_plan_id:string}[];
  dispatches:{event_id:string;state:string;reason:string|null;business_at:string;owner_plan_id:string}[];
  technical_schedule:{version:string;enabled:boolean;canceled:boolean};execution_owner:string;
};
type Props={data:OwnerPlanProjection|null;loading:boolean;error:string;onReload:()=>void;onDirtyChange:(dirty:boolean)=>void};
function localTime(value:string){return new Intl.DateTimeFormat("sv-SE",{timeZone:"Asia/Shanghai",year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hourCycle:"h23"}).format(new Date(value)).replace(" ","T");}

export function BossOwnerPlans({data,loading,error,onReload,onDirtyChange}:Props){
  const [selected,setSelected]=useState<OwnerPlan|null>(null);
  const [purpose,setPurpose]=useState(""),[at,setAt]=useState(""),[events,setEvents]=useState<string[]>([]);
  const [filter,setFilter]=useState({state:"",type:"",timezone:""}),[applied,setApplied]=useState(filter),[page,setPage]=useState(1);
  const [dirty,setDirty]=useState(false),[failure,setFailure]=useState("");
  const resultsRef=useRef<HTMLElement|null>(null);
  const transaction=useTransaction(()=>{select(null);onReload();},undefined,undefined,"plan");
  const busy=transaction.busy;
  const current=selected?data?.plans.find(plan=>plan.plan_id===selected.plan_id):null;
  const changedVersion=Boolean(selected&&data&&(!current||current.version!==selected.version));
  const disabled=busy||loading||!data||Boolean(error)||changedVersion;
  const plans=(data?.plans??[]).filter(plan=>(!applied.state||plan.state===applied.state)&&(!applied.type||plan.plan_type===applied.type)&&(!applied.timezone||plan.timezone===applied.timezone));
  const currentPage=Math.min(page,Math.max(1,Math.ceil(plans.length/10)));
  const dispatches=data?.dispatches.filter(row=>!selected||row.owner_plan_id===selected.plan_id)??[];
  const results=data?.results.filter(row=>!selected||row.owner_plan_id===selected.plan_id)??[];
  useEffect(()=>{onDirtyChange(dirty||busy);},[dirty,busy,onDirtyChange]);
  function select(plan:OwnerPlan|null){
    setSelected(plan);setPurpose(plan?.purpose??"");setAt(plan?localTime(plan.not_before):"");
    setEvents(plan?.event_ids??[]);setDirty(false);setFailure("");onDirtyChange(false);
  }
  function changed(){setDirty(true);onDirtyChange(true);}
  function choose(plan:OwnerPlan|null){if(dirty){setFailure("当前计划存在未保存编辑，请保存或明确放弃后选择其他计划。");return;}select(plan);}
  function submit(action:"save"|"pause"|"resume"|"cancel"){
    if(disabled)return;
    const payload={plan_id:selected?.plan_id??"",expected_version:selected?.version??"0",
      ...(action==="save"?{purpose,event_ids:events,timezone:"Asia/Shanghai",not_before:at+":00+08:00"}:{}),
    };
    transaction.propose(("boss.owner.plan."+action) as "boss.owner.plan.save"|"boss.owner.plan.pause"|"boss.owner.plan.resume"|"boss.owner.plan.cancel",payload,"本人核查计划操作",[
      "本次动作："+({save:"保存",pause:"暂停",resume:"恢复",cancel:"取消"}[action]),"计划："+(selected?.plan_id??"当前新增计划"),
      "当前版本："+(selected?.version??"0"),"用途："+purpose,"事件范围："+events.join("、"),"时间条件："+at+"（Asia/Shanghai）",
      "仅改变当前本人计划，原经营事件、任务期限和历史通知分别保留。",
    ]);
  }
  return <div className="boss-owner-plans">
    <V7ReadState loading={loading} error={error} onReload={onReload}/>
    {failure&&<p className="boss-status boss-status-error" role="alert">{failure}</p>}
    {changedVersion&&<p className="boss-status boss-status-warn" role="status">所选计划版本已经变化。当前编辑保留，请核查并选择当前版本后操作。</p>}
    <form className="boss-v7-filter-bar" onSubmit={event=>{event.preventDefault();setApplied(filter);setPage(1);}}>
      <label>当前状态<select value={filter.state} onChange={event=>setFilter({...filter,state:event.target.value})}><option value="">全部状态</option><option value="ACTIVE">启用</option><option value="PAUSED">暂停</option><option value="CANCELED">取消</option></select></label>
      <label>计划类型<select value={filter.type} onChange={event=>setFilter({...filter,type:event.target.value})}><option value="">全部已读取类型</option>{[...new Set((data?.plans??[]).flatMap(plan=>plan.plan_type?[plan.plan_type]:[]))].map(value=><option key={value}>{value}</option>)}</select></label>
      <label>时区<select value={filter.timezone} onChange={event=>setFilter({...filter,timezone:event.target.value})}><option value="">全部已读取时区</option>{[...new Set((data?.plans??[]).map(plan=>plan.timezone))].map(value=><option key={value}>{value}</option>)}</select></label>
      <button className="boss-btn boss-btn-primary" disabled={loading}>查询 / 应用</button>
    </form>
    <div className="boss-owner-plan-columns"><div className="boss-column">
      <V7Panel title="计划与运行条件">
        <div className="boss-v7-table-scroll"><table className="boss-v7-table"><thead><tr><th>本人计划与用途</th><th>任务范围</th><th>时间与时区</th><th>规则与授权</th><th>当前状态</th></tr></thead><tbody>{plans.slice((currentPage-1)*10,currentPage*10).map(plan=><tr key={plan.plan_id} aria-selected={selected?.plan_id===plan.plan_id}><td><button className="boss-v7-text-button" disabled={busy} onClick={()=>choose(plan)}>{plan.purpose}</button><small>{plan.plan_id} · {plan.plan_type??"类型尚未提供"}</small></td><td>{plan.event_ids.join("、")}</td><td>{plan.not_before}<small>{plan.timezone}</small><small>下一次：{plan.next_run_at??"尚未提供"}</small></td><td>{plan.rule_version??"采用规则版本尚未提供"}<small>{plan.authorization_id}</small></td><td>{plan.state}<small>v{plan.version}</small></td></tr>)}</tbody></table></div>
        {!plans.length&&<V7Empty title={loading?"正在读取本人计划":data?"当前条件下没有本人计划":"本人计划待读取"}>按当前本人权限和筛选条件查询。</V7Empty>}
        {data&&<V7Pagination total={plans.length} pageSize={10} page={currentPage} onChange={setPage}/>}
        <div className="boss-actions"><button className="boss-btn" disabled={busy||loading} onClick={()=>choose(null)}>填写新的本人计划</button>{dirty&&<button className="boss-btn" disabled={busy} onClick={()=>select(current??null)}>放弃当前编辑</button>}{changedVersion&&!dirty&&<button className="boss-btn" onClick={()=>select(current??null)}>采用当前版本</button>}</div>
        <h3>时间与事件条件</h3>
        <fieldset className="boss-owner-plan-editor" disabled={disabled||selected?.state==="CANCELED"}>
          <div className="boss-form-grid"><label>计划用途<input maxLength={400} value={purpose} onChange={event=>{setPurpose(event.target.value);changed();}}/></label><label>最早执行时间（Asia/Shanghai）<input type="datetime-local" value={at} onChange={event=>{setAt(event.target.value);changed();}}/></label></div>
          <p>任务范围：选择当前已经保存的事件</p>
          {data?.events.map(event=><label className="boss-confirm-check" key={event.event_id}><input type="checkbox" checked={events.includes(event.event_id)} disabled={event.state==="CANCELED"} onChange={change=>{setEvents(change.target.checked?[...events,event.event_id]:events.filter(id=>id!==event.event_id));changed();}}/><span>{event.event_id} · {event.state} · v{event.version}<small>期限：{event.due_at}</small></span></label>)}
          {data&&!data.events.length&&<p className="boss-v7-note">没有可选择的已保存事件。</p>}
        </fieldset>
      </V7Panel>
      <section ref={resultsRef} tabIndex={-1}><V7Panel title="执行边界">
        <V7Fact label="本次查看范围">{selected?selected.purpose:"全部已读取本人计划"}</V7Fact>
        <p>暂停和取消会停止后续计划采用；历史通知、已经保存的任务与发件记录继续保留。</p>
        <p>执行需要同时满足事件期限、有效授权、技术规则、免打扰和冷却条件。</p>
        <div className="boss-v7-table-scroll"><table className="boss-v7-table"><thead><tr><th>计划与事件</th><th>执行状态</th><th>处理原因</th><th>业务时间</th></tr></thead><tbody>{dispatches.map((row,index)=><tr key={row.owner_plan_id+row.event_id+row.business_at+index}><td>{row.owner_plan_id}<small>{row.event_id}</small></td><td>{row.state}</td><td>{row.reason??"未提供"}</td><td>{row.business_at}</td></tr>)}</tbody></table></div>
        {!dispatches.length&&<V7Empty title={data?"当前范围没有已读取执行记录":"执行记录待读取"}>执行结果采用服务保存的正式记录。</V7Empty>}
        <details><summary>已保存内部通知（{data?results.length:"尚未读取"}）</summary>{results.map((row,index)=><article className="boss-workspace-item" key={row.owner_plan_id+row.event_id+row.business_at+index}><strong>{row.event_id} · {row.state}</strong><p>{row.business_at}</p><small>{row.owner_plan_id}</small></article>)}</details>
      </V7Panel></section>
    </div><aside className="boss-column">
      <V7Panel title="来源与依据"><V7Fact label="所选计划">{selected?.plan_id??"尚未选择"}</V7Fact><V7Fact label="计划版本">{selected?.version??"尚未选择"}</V7Fact><V7Fact label="有效授权引用">{selected?.authorization_id??"尚未取得"}</V7Fact><V7Fact label="采用规则版本">{selected?.rule_version??"尚未提供"}</V7Fact><V7Fact label="计划执行时区">{selected?.timezone??"尚未选择"}</V7Fact><p className="boss-v7-note">授权引用需要在执行时继续核查有效范围。</p></V7Panel>
      <V7Panel title="状态与核查"><V7Fact label="本人计划状态">{current?.state??(selected?"当前记录不可用":"尚未选择")}</V7Fact><V7Fact label="下一次执行时间">{current?.next_run_at??"尚未提供"}</V7Fact><V7Fact label="技术执行责任">{data?.execution_owner??"尚未读取"}</V7Fact><V7Fact label="当前技术规则">{data?.technical_schedule.version??"尚未读取"}</V7Fact><V7Fact label="技术调度状态">{data?(data.technical_schedule.canceled?"已经取消":data.technical_schedule.enabled?"启用":"暂停"):"尚未读取"}</V7Fact><button className="boss-btn" disabled={loading||busy} onClick={onReload}>重读计划与执行状态</button></V7Panel>
    </aside></div>
    <footer className="boss-owner-actions">
      <button className="boss-btn boss-btn-primary" disabled={disabled||!purpose.trim()||!at||!events.length||selected?.state==="CANCELED"} onClick={()=>submit("save")}>{selected?"修改本人范围":"创建获准计划"}</button>
      {(["pause","resume","cancel"] as const).map(action=><button className="boss-btn" key={action} disabled={disabled||!selected||dirty||selected.state==="CANCELED"||(action==="pause"&&selected.state!=="ACTIVE")||(action==="resume"&&selected.state!=="PAUSED")} onClick={()=>submit(action)}>{{pause:"暂停",resume:"恢复",cancel:"取消"}[action]}</button>)}
      <button className="boss-btn" onClick={()=>{resultsRef.current?.scrollIntoView({block:"start",behavior:"smooth"});resultsRef.current?.focus({preventScroll:true});}}>查看执行结果</button>
    </footer>
    {transaction.notice&&<p className="boss-status boss-status-ok" role="status">{transaction.notice}</p>}{transaction.dialog}{transaction.recovery}
  </div>;
}
