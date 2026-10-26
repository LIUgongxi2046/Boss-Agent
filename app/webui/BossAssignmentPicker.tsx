import {useEffect,useState} from "react";
import {checkLocalTime,initialLocalTime} from "./local-time";

export type AssignmentDraft = {
  purpose:string;coordinator:string;due:string;evidence:string;body:string;newDue:string;reason:string;
  timezone:string;basis:string;sourceIds:string;meetingId:string;eventIds:string;relatedTask:string;relatedTaskVersion:string;
};
export const DEFAULT_ASSIGNMENT_DRAFT:AssignmentDraft={purpose:"",coordinator:"",due:"",evidence:"",body:"",newDue:"",reason:"",timezone:"",basis:"",sourceIds:"",meetingId:"",eventIds:"",relatedTask:"",relatedTaskVersion:""};
type Contact={contact_id:string;name:string;organization:string;responsibility:string;valid_from?:string;valid_until?:string};
type Props={pageId:"D04"|"D05";contacts:Contact[];timezone?:string;businessClock?:string;draft:AssignmentDraft;onChange:(field:keyof AssignmentDraft,value:string)=>void;onReturn:()=>void;onDirtyChange?:(value:boolean)=>void;taskId?:string;taskVersion?:string;loading?:boolean};

export function BossAssignmentPicker({pageId,contacts,timezone,businessClock,draft,onChange,onReturn,onDirtyChange,taskId,taskVersion,loading=false}:Props){
  const [person,setPerson]=useState(draft.coordinator),[zone,setZone]=useState(draft.timezone);
  const [initialTime]=useState(()=>initialLocalTime(draft.due,draft.timezone));
  const [localDate,setLocalDate]=useState(initialTime.date),[localClock,setLocalClock]=useState(initialTime.time),[occurrence,setOccurrence]=useState(initialTime.occurrence);
  const [filter,setFilter]=useState(""),[organization,setOrganization]=useState(""),[error,setError]=useState("");
  const [original]=useState(()=>JSON.stringify([draft,taskId,taskVersion]));
  const changed=original!==JSON.stringify([draft,taskId,taskVersion]);
  const dirty=pageId==="D04"?person!==draft.coordinator:localDate!==initialTime.date||localClock!==initialTime.time||occurrence!==initialTime.occurrence||zone!==draft.timezone;
  useEffect(()=>{onDirtyChange?.(dirty);return()=>onDirtyChange?.(false);},[dirty,onDirtyChange]);
  const selected=contacts.find(contact=>contact.contact_id===person);
  const options=contacts.filter(contact=>(!organization||contact.organization===organization)&&[contact.name,contact.contact_id,contact.organization,contact.responsibility].join(" ").toLocaleLowerCase().includes(filter.trim().toLocaleLowerCase()));
  const date=businessClock?.slice(0,10);
  const valid=(contact:Contact)=>!date||(!contact.valid_from||contact.valid_from<=date)&&(!contact.valid_until||contact.valid_until>=date);
  const check=pageId==="D05"?checkLocalTime(localDate,localClock,zone,occurrence,businessClock,timezone):null;
  const issue=check?.issue??"";
  function confirm(){
    if(loading||changed)return;
    setError("");
    if(pageId==="D04"){
      if(!selected||!valid(selected)){setError("请选择当前资料中有效的唯一负责人。");return;}
      onChange("coordinator",person);
    }else{
      if(!check?.value){setError(issue||"请选择日期、时间与IANA时区。");return;}
      onChange("due",check.value);onChange("timezone",zone);
    }
    onReturn();
  }
  return <div className="boss-assignment-scope">
    {changed&&<p className="boss-status boss-status-warn" role="alert">原交办内容已经变化，请返回原页面重新核查后选择。</p>}
    {loading&&<p role="status">正在读取当前可用资料。</p>}
    <div className="boss-assignment-columns"><div className="boss-column">
      <section className="boss-panel"><div className="boss-panel-head"><h2>{pageId==="D04"?"负责人查询":"时间选择与对象"}</h2><small>当前交办草稿</small></div>
        {pageId==="D04"?<><div className="boss-form-grid"><label>姓名、组织或职责<input value={filter} onChange={event=>setFilter(event.target.value)} placeholder="查询获准联系人"/></label><label>组织范围<select value={organization} onChange={event=>setOrganization(event.target.value)}><option value="">全部获准组织</option>{[...new Set(contacts.map(contact=>contact.organization))].map(value=><option key={value} value={value}>{value}</option>)}</select></label></div>
          <div className="boss-picker-list" role="radiogroup" aria-label="选择唯一负责人">{options.map(contact=><label key={contact.contact_id} className={"boss-picker-item "+(person===contact.contact_id?"selected":"")}><input type="radio" name="assignment-person" checked={person===contact.contact_id} disabled={loading||changed||!valid(contact)} onChange={()=>setPerson(contact.contact_id)}/><span><strong>{contact.name} · {contact.organization}</strong><small>{contact.responsibility} · {contact.contact_id}</small><small>{valid(contact)?"当前资料有效":"已超出资料有效日期"} · {contact.valid_from??"未提供起始日期"} 至 {contact.valid_until??"未提供结束日期"}</small></span></label>)}</div>{!options.length&&<p className="boss-helper">当前查询范围没有可显示的联系人。</p>}
        </>:<><div className="boss-kv"><span>原对象</span><strong>{taskId||"尚未创建的交办"} · {taskVersion?"版本 "+taskVersion:"本地草稿"}</strong></div><div className="boss-form-grid"><label>本次日期<input type="date" value={localDate} disabled={loading||changed} onChange={event=>{setLocalDate(event.target.value);setOccurrence("");}}/></label><label>具体时间<input type="time" step="1" value={localClock} disabled={loading||changed} onChange={event=>{setLocalClock(event.target.value);setOccurrence("");}}/></label><label>IANA时区<input value={zone} disabled={loading||changed} onChange={event=>{setZone(event.target.value);setOccurrence("");}} placeholder="例如 Asia/Shanghai"/></label>{Boolean(check&&check.choices.length>1)&&<label>本次采用的UTC时差<select value={occurrence} disabled={loading||changed} onChange={event=>setOccurrence(event.target.value)}><option value="">请选择本次采用的时间</option>{check!.choices.map(choice=><option key={choice.value} value={choice.value}>{choice.label}</option>)}</select></label>}</div>{initialTime.issue&&!dirty&&<p className="boss-status boss-status-warn">{initialTime.issue}</p>}<p className="boss-helper">采用所选地点的当地时间，确认后保留完整ISO时间、UTC时差与IANA时区。不存在或存在歧义的当地时间需要重新选择。</p></>}
      </section>
      <section className="boss-panel"><div className="boss-panel-head"><h2>{pageId==="D04"?"选中唯一负责人":"跨时区核查"}</h2></div>{pageId==="D04"?selected?<><div className="boss-kv"><span>姓名与编号</span><strong>{selected.name} · {selected.contact_id}</strong></div><div className="boss-kv"><span>组织与职责</span><strong>{selected.organization} · {selected.responsibility}</strong></div><p className="boss-helper">确认后仅将这一位联系人填入原交办草稿。</p></>:<p className="boss-helper">尚未选择负责人。</p>:check?.value?<><div className="boss-kv"><span>所选时区 {zone}</span><strong>{check.local}</strong></div><div className="boss-kv"><span>本人时区 {timezone??"未提供"}</span><strong>{check.owner??"缺少有效本人时区，尚不能核查"}</strong></div><div className="boss-kv"><span>UTC时间</span><strong>{check.utc}</strong></div><div className="boss-kv"><span>UTC时差</span><strong>{check.offset}</strong></div><div className="boss-kv"><span>夏令时</span><strong>{check.daylight?"当前采用夏令时":"当前采用标准时间"}</strong></div><div className="boss-kv"><span>与本人日期是否跨日</span><strong>{check.crossDay===undefined?"待本人时区核查":check.crossDay?"当地与本人日期不同":"当地与本人日期相同"}</strong></div><div className="boss-kv"><span>业务时钟</span><strong>{businessClock}</strong></div></>:<p className="boss-helper" role="status">{issue||"选择日期、时间和时区后显示换算结果。"}</p>}</section>
    </div><aside className="boss-column"><section className="boss-panel"><div className="boss-panel-head"><h2>{pageId==="D04"?"范围与异常":"原对象与取消"}</h2></div><p>当前选择只修改交办草稿。创建与发送分别由本人核查。</p><div className="boss-kv"><span>原负责人</span><strong>{draft.coordinator||"尚未选择"}</strong></div><div className="boss-kv"><span>原期限</span><strong>{draft.due||"尚未填写"}</strong></div><div className="boss-kv"><span>原时区</span><strong>{draft.timezone||"尚未填写"}</strong></div><p className="boss-helper">取消选择将保留进入页面时的交办草稿。资料版本变化后需要重新核查。</p></section></aside></div>
    {error&&<p className="boss-status boss-status-error" role="alert">{error}</p>}
    <div className="boss-actions boss-assignment-footer"><button type="button" className="boss-btn" onClick={onReturn}>取消并返回交办</button><button type="button" className="boss-btn boss-btn-primary" disabled={loading||changed||(pageId==="D04"?!selected||!valid(selected):!check?.value)} onClick={confirm}>确认选择并返回</button></div>
  </div>;
}
