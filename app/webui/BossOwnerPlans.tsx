import {useEffect,useState} from "react";
import {useTransaction} from "./BossAssignmentFlow";

export type OwnerPlan={plan_id:string;version:string;state:string;purpose:string;event_ids:string[];timezone:string;not_before:string;authorization_id:string};
export type OwnerPlanProjection={
  plans:OwnerPlan[];events:{event_id:string;version:string;state:string;due_at:string}[];
  results:{event_id:string;state:string;business_at:string;owner_plan_id:string}[];
  dispatches:{event_id:string;state:string;reason:string|null;business_at:string;owner_plan_id:string}[];
  technical_schedule:{version:string;enabled:boolean;canceled:boolean};execution_owner:string;
};
type Props={data:OwnerPlanProjection|null;loading:boolean;error:string;onReload:()=>void;
  onCommand:(action:string,payload:Record<string,unknown>)=>Promise<void>;onDirtyChange:(dirty:boolean)=>void};

export function BossOwnerPlans({data,loading,error,onReload,onDirtyChange}:Props){
  const [selected,setSelected]=useState<OwnerPlan|null>(null);
  const [purpose,setPurpose]=useState("");
  const [at,setAt]=useState("");
  const [events,setEvents]=useState<string[]>([]);
  const [filter,setFilter]=useState("");
  const [dirty,setDirty]=useState(false);
  const [failure,setFailure]=useState("");
  const transaction=useTransaction(()=>{select(null);onReload();},undefined,undefined,"plan");
  const busy=transaction.busy;
  useEffect(()=>{onDirtyChange(dirty||busy);},[dirty,busy,onDirtyChange]);
  function select(plan:OwnerPlan|null){
    setSelected(plan);setPurpose(plan?.purpose||"");setAt(plan?.not_before.slice(0,16)||"");
    setEvents(plan?.event_ids||[]);setDirty(false);setFailure("");onDirtyChange(false);
  }
  function changed(){setDirty(true);onDirtyChange(true);}
  function choose(plan:OwnerPlan|null){if(dirty){setFailure("当前计划存在未保存编辑，请保存或明确放弃后选择其他计划。");return;}select(plan);}
  function submit(action:"save"|"pause"|"resume"|"cancel"){
    if(busy||!data)return;
    const payload={plan_id:selected?.plan_id||"",
      expected_version:selected?.version||"0",
      ...(action==="save"?{purpose,event_ids:events,timezone:"Asia/Shanghai",not_before:at+":00+08:00"}:{}),
    };
    transaction.propose(("boss.owner.plan."+action) as "boss.owner.plan.save"|"boss.owner.plan.pause"|"boss.owner.plan.resume"|"boss.owner.plan.cancel",payload,"本人核查计划操作",[
      "本次动作："+({save:"保存",pause:"暂停",resume:"恢复",cancel:"取消"}[action]),"计划："+(selected?.plan_id||"当前新增计划"),
      "当前版本："+(selected?.version||"0"),"用途："+purpose,"事件范围："+events.join("、"),"时间条件："+at+"（Asia/Shanghai）",
      "仅改变当前本人计划，原经营事件、任务期限和历史通知分别保留。",
    ]);
  }
  return <>
    <div className="boss-workspace-toolbar"><span className="boss-tag boss-tag-amber">N09 · 本人计划 · SIMULATED</span>
      <button type="button" className="boss-btn" disabled={loading||busy} onClick={onReload}>查询当前计划与执行结果</button></div>
    {(error||failure)&&<p className="boss-status boss-status-error" role="alert">{error||failure}</p>}
    {loading&&<p role="status">正在读取本人计划</p>}
    <div className="boss-columns"><div className="boss-column"><section className="boss-panel">
      <div className="boss-panel-head"><h2>本人计划列表</h2><small>范围与状态均由本人维护</small></div>
      <label className="boss-field">当前状态<select value={filter} onChange={e=>setFilter(e.target.value)}><option value="">全部状态</option><option value="ACTIVE">启用</option><option value="PAUSED">暂停</option><option value="CANCELED">取消</option></select></label>
      {data?.plans.filter(p=>!filter||p.state===filter).map(plan=><button className="boss-task-row" type="button" key={plan.plan_id} disabled={busy} onClick={()=>choose(plan)}>
        <strong>{plan.purpose}</strong><small>{plan.state} · v{plan.version} · {plan.not_before}</small></button>)}
      {data?.plans.length===0&&<p>本人计划尚未设置。</p>}
      <button className="boss-btn" type="button" disabled={busy} onClick={()=>choose(null)}>填写新的本人计划</button>
      {dirty&&<button className="boss-btn" type="button" disabled={busy} onClick={()=>select(null)}>放弃当前计划编辑</button>}
    </section><section className="boss-panel"><div className="boss-panel-head"><h2>计划与运行条件</h2></div>
      <fieldset disabled={busy||selected?.state==="CANCELED"}>
        <label className="boss-field">计划用途<input maxLength={400} value={purpose} onChange={e=>{setPurpose(e.target.value);changed();}}/></label>
        <label className="boss-field">时间条件（Asia/Shanghai）<input type="datetime-local" value={at} onChange={e=>{setAt(e.target.value);changed();}}/></label>
        <p>任务范围：选择当前已经保存的事件</p>
        {data?.events.map(event=><label className="boss-confirm-check" key={event.event_id}><input type="checkbox" checked={events.includes(event.event_id)} disabled={event.state==="CANCELED"}
          onChange={e=>{setEvents(e.target.checked?[...events,event.event_id]:events.filter(id=>id!==event.event_id));changed();}}/>{event.event_id} · {event.state} · v{event.version}</label>)}
      </fieldset>
      <div className="boss-actions">
        <button type="button" className="boss-btn boss-btn-primary" disabled={busy||!purpose||!at||!events.length||selected?.state==="CANCELED"} onClick={()=>submit("save")}>{selected?"修改本人范围":"创建获准计划"}</button>
        {selected&&(["pause","resume","cancel"] as const).map(action=><button className="boss-btn" type="button" key={action}
          disabled={busy||dirty||selected.state==="CANCELED"||(action==="pause"&&selected.state!=="ACTIVE")||(action==="resume"&&selected.state!=="PAUSED")}
          onClick={()=>void submit(action)}>{{pause:"暂停",resume:"恢复",cancel:"取消"}[action]}</button>)}
      </div>
      <p className="boss-helper">暂停和取消会停止后续计划采用；历史通知、已经保存的任务与发件记录继续保留。</p>
    </section></div><div className="boss-column"><section className="boss-panel"><div className="boss-panel-head"><h2>技术执行责任与当前结果</h2></div>
      <p>唯一执行组件：{data?.execution_owner||"待读取"}</p><p>技术规则版本：{data?.technical_schedule.version||"待读取"}</p>
      <p>技术调度状态：{data?.technical_schedule.canceled?"已经取消":data?.technical_schedule.enabled?"启用":"暂停或待读取"}</p>
      <p>当前授权：{selected?.authorization_id||"选择计划后查看"}</p>
      <p>最早执行时间：{selected?.not_before||"尚未选择计划"}</p>
      <p className="boss-helper">执行还需满足事件期限、当前授权、技术规则、免打扰和冷却条件。内部模拟通知与系统通知分别验证。</p>
      {data?.dispatches.filter(r=>!selected||r.owner_plan_id===selected.plan_id).map(result=><article className="boss-workspace-item" key={result.event_id}><strong>{result.event_id} · {result.state}</strong><p>{result.reason||"已保存内部通知"}</p><small>{result.business_at}</small></article>)}
      <p>已保存内部通知数量：{data?.results.filter(r=>!selected||r.owner_plan_id===selected.plan_id).length??0}</p>
    </section></div></div>
    {transaction.notice&&<p className="boss-status boss-status-ok" role="status">{transaction.notice}</p>}
    {transaction.dialog}
    {transaction.recovery}
  </>;
}
