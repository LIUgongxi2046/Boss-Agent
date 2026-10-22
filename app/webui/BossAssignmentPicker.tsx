import { useEffect, useState } from "react";
import { ArrowLeft, CalendarDays, CheckCircle2, Clock3, ShieldCheck, Users } from "lucide-react";

export type AssignmentDraft = {
  purpose: string; coordinator: string; due: string;
  evidence: string; body: string; newDue: string; reason: string;
};
export const DEFAULT_ASSIGNMENT_DRAFT: AssignmentDraft = {
  purpose:"",coordinator:"",due:"",evidence:"经营原始明细",
  body:"",newDue:"",reason:"",
};
type Contact = {
  contact_id: string; name: string; organization: string;
  responsibility: string; valid_from?: string; valid_until?: string;
};
type Props = {
  pageId: "D04" | "D05";
  contacts: Contact[];
  timezone: string;
  businessClock?: string;
  draft: AssignmentDraft;
  onChange: (field:keyof AssignmentDraft,value:string)=>void;
  onReturn: ()=>void;
};
export function BossAssignmentPicker({pageId,contacts,timezone,businessClock,draft,onChange,onReturn}:Props){
  const [person,setPerson] = useState(draft.coordinator);
  const [due,setDue] = useState(draft.due);
  const [error,setError] = useState("");
  const [filter,setFilter] = useState("");
  useEffect(()=>{
    setPerson(draft.coordinator);setDue(draft.due);
  },[draft.coordinator,draft.due]);
  const options=contacts.filter(c=>(c.name+" "+c.contact_id+" "+c.organization).includes(filter.trim()));
  function confirm(){
    setError("");
    if(pageId==="D04"){
      if(!person || !contacts.some(c=>c.contact_id===person)){
        setError("请选择当前材料中有效的负责人。");return;
      }
      // This fixed data set has only one authorized assignment coordinator.
      if(person!=="coordinator-1"){
        setError("当前演示交办工具仅允许 coordinator-1；其他人可查但不能代入交办。");return;
      }
      onChange("coordinator",person);
    }else{
      if(!/^\d{4}-\d\d-\d\dT\d\d:\d\d$/.test(due)){
        setError("请输入完整年月日与时分。");return;
      }
      if(timezone!=="Asia/Shanghai"){
        setError("当前模拟工具仅核验 Asia/Shanghai 时区，不能擅自换算。");return;
      }
      if(businessClock && new Date(due+":00+08:00").getTime()<=new Date(businessClock).getTime()){
        setError("选择的期限必须晚于当前模拟业务时钟。");return;
      }
      onChange("due",due);
    }
    onReturn();
  }
  return <div className="boss-columns">
    <div className="boss-column">
      <section className="boss-panel">
        <div className="boss-panel-head"><h2>{pageId==="D04"?"选择唯一负责人":"选择日期与时区"}</h2>
          <small>{pageId} · v6 业务选择弹窗</small></div>
        {pageId==="D04" ? <>
          <label className="boss-label" htmlFor="boss-contact-search">查找当前有权联系人</label>
          <input className="boss-single-input" id="boss-contact-search" placeholder="按名称、组织或联系人ID过滤"
            value={filter} onChange={e=>setFilter(e.target.value)}/>
          <div className="boss-picker-list" role="radiogroup" aria-label="选择模拟交办负责人">
            {options.map(c=><label className={"boss-picker-item "+(person===c.contact_id?"selected":"")} key={c.contact_id}>
              <input type="radio" name="boss-contact-choice" checked={person===c.contact_id}
                onChange={()=>setPerson(c.contact_id)} disabled={c.contact_id!=="coordinator-1"}/>
              <Users size={17}/><span><strong>{c.name} · {c.organization}</strong>
                <small>{c.contact_id} · {c.responsibility}</small>
                {c.contact_id!=="coordinator-1"&&<small>当前模拟接口不允许此联系人承接交办</small>}
              </span>
            </label>)}
          </div>
        </> : <>
          <label className="boss-label" htmlFor="boss-due-picker">当前交办截止时间</label>
          <input className="boss-single-input" id="boss-due-picker" type="datetime-local"
            value={due} onChange={e=>setDue(e.target.value)}/>
          <div className="boss-kv"><span>当前 IANA 时区</span><strong>{timezone}</strong></div>
          <div className="boss-kv"><span>模拟业务时钟</span><strong>{businessClock?.replace("T"," ")||"待读取"}</strong></div>
          <div className="boss-status"><Clock3 size={16}/>
            当前选型只支持北京时间的交办演示；海外、夏令时和跨日排程需独立数据及规则校验。
          </div>
        </>}
        {error&&<div role="alert" className="boss-status boss-status-error">{error}</div>}
        <div className="boss-actions">
          <button type="button" className="boss-btn" onClick={onReturn}>
            <ArrowLeft size={15}/> 返回原交办（不更改）
          </button>
          <button type="button" className="boss-btn boss-btn-primary" onClick={confirm}>
            <CheckCircle2 size={15}/> 采用当前选择
          </button>
        </div>
      </section>
    </div>
    <div className="boss-column">
      <section className="boss-panel">
        <div className="boss-panel-head"><h2>授权和保存边界</h2></div>
        <div className="boss-status"><ShieldCheck size={16}/>
          当前只在本地表单采用一个选择，不创建或发送交办。实际任务仍需要老板审阅完整目的、负责人、期限、证据后再次确认。
        </div>
        <div className="boss-kv"><span>数据来源</span><strong>当前 SIMULATED 联系人／业务时钟</strong></div>
        <div className="boss-kv"><span>实际任务写入</span><strong>尚未执行</strong></div>
        <button type="button" className="boss-btn" onClick={onReturn}>
          <CalendarDays size={15}/> 返回 F06 继续编辑
        </button>
      </section>
    </div>
  </div>;
}
