import {useEffect,useState} from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {useTransaction} from "./BossAssignmentFlow";
import {V7Empty,V7Fact,V7Panel} from "./BossV7UI";

type Entry={entry_id:string;kind:string;text:string;source_anchor:string};
type Minute={minute_id:string;meeting_id:string;version:string;state:"DRAFT_REVIEW"|"CONFIRMED";source_id:string;source_version:string;entries:Entry[]};
type TaskLink={minute_id:string;minute_version:string;entry_id:string;task_id:string;task_status:string;task_version:string;send_status:string;sent_message_count:number;authorization_id:string;source_id:string;source_version:string};
type Props={minute:Minute|null;participants:string[];contacts:{contact_id:string;name:string;organization:string;responsibility:string;allowed_for_fixture_assignment:boolean}[];businessClock:string;links:TaskLink[];sourceCurrent:boolean;editingUnsaved:boolean;onReload:()=>void;onTaskCreated:(id:string)=>void;onNavigate:(id:string)=>void;onDirtyChange:(dirty:boolean)=>void};
const EMPTY={entryId:"",purpose:"",coordinator:"",due:"",evidence:"",basis:""};
function signature(minute:Minute,entry:Entry){return JSON.stringify([minute.minute_id,minute.version,minute.state,minute.source_id,minute.source_version,entry.entry_id,entry.text,entry.source_anchor]);}

export function BossMinutesAssignmentActions({minute,participants,contacts,businessClock,links,sourceCurrent,editingUnsaved,onReload,onTaskCreated,onNavigate,onDirtyChange}:Props){
  const [form,setForm]=useState(EMPTY),[error,setError]=useState(""),[nextEntry,setNextEntry]=useState<string|null>(null);
  const transaction=useTransaction(recorded=>{if(recorded){setForm(EMPTY);setError("");}onReload();},onTaskCreated,undefined,"minutesAssignment");
  const candidates=minute?.entries.filter(row=>row.kind==="ASSIGNMENT_DRAFT")??[];
  const entry=candidates.find(row=>row.entry_id===form.entryId);
  const linked=links.find(row=>row.entry_id===form.entryId&&row.minute_version===minute?.version);
  const edited=Boolean(form.entryId&&!linked);
  const stale=Boolean(form.basis&&(!minute||!entry||signature(minute,entry)!==form.basis));
  const disabled=transaction.busy||editingUnsaved||!sourceCurrent||minute?.state!=="CONFIRMED"||stale;
  useEffect(()=>{onDirtyChange(edited||transaction.busy);},[edited,transaction.busy,onDirtyChange]);
  useEffect(()=>{const prevent=(event:BeforeUnloadEvent)=>{if(edited||transaction.busy){event.preventDefault();event.returnValue="";}};window.addEventListener("beforeunload",prevent);return()=>window.removeEventListener("beforeunload",prevent);},[edited,transaction.busy]);
  function select(id:string){const current=candidates.find(row=>row.entry_id===id);setForm(current&&minute?{...EMPTY,entryId:id,purpose:current.text,basis:signature(minute,current)}:EMPTY);setError("");setNextEntry(null);}
  function propose(){
    if(disabled||linked||!entry||!minute)return;
    const coordinator=contacts.find(row=>row.contact_id===form.coordinator);
    if(!coordinator?.allowed_for_fixture_assignment||!participants.includes(form.coordinator)){setError("请选择当前获准的唯一负责人。");return;}
    if(!form.purpose.trim()||form.purpose.length>1600){setError("交办目的须为1—1600字。");return;}
    if(!form.evidence.trim()||form.evidence.length>160){setError("证据要求须为1—160字。");return;}
    if(!form.due||!businessClock){setError("须填写完整期限，并取得当前业务时钟。");return;}
    const due=form.due+":00+08:00";
    if(!Number.isFinite(new Date(due).getTime())||new Date(due).getTime()<=new Date(businessClock).getTime()){setError("期限须晚于当前业务时钟，时区为Asia/Shanghai。");return;}
    setError("");transaction.propose("boss.minutes.assignment.create",{meeting_id:minute.meeting_id,minute_version:minute.version,entry_id:entry.entry_id,purpose:form.purpose.trim(),coordinator_id:form.coordinator,due_at:due,timezone:"Asia/Shanghai",evidence_requirements:[form.evidence.trim()]},"本人确认逐项创建交办",["纪要："+minute.minute_id+" v"+minute.version,"条目："+entry.entry_id,"原文："+minute.source_id+" v"+minute.source_version+" · "+entry.source_anchor,"目标："+form.purpose.trim(),"唯一负责人："+form.coordinator,"期限："+due,"证据："+form.evidence.trim(),"本次创建OPEN任务，发送需要另行确认。"]);
  }
  return <V7Panel title="逐项交办草稿" description="每条草稿分别关联已确认纪要、负责人、期限及证据。">
    {minute?.state!=="CONFIRMED"&&<p className="boss-status boss-status-warn">当前纪要需要本人确认。意见、建议和未确认草稿不能创建交办。</p>}
    {stale&&<p role="alert" className="boss-status boss-status-warn">纪要或条目版本已经变化，原编辑保留。请取消当前编辑并重新选择有效条目。</p>}
    {transaction.notice&&<p role="status" className="boss-status boss-status-ok">{transaction.notice}</p>}{transaction.recovery}
    <label className="boss-field">选择当前交办草稿<select value={form.entryId} disabled={transaction.busy} onChange={event=>{if(edited)setNextEntry(event.target.value);else select(event.target.value);}}><option value="">请选择纪要条目</option>{candidates.map(row=><option key={row.entry_id} value={row.entry_id}>{row.entry_id} · {row.text.slice(0,48)}</option>)}</select></label>
    {entry&&<><V7Fact label="已确认内容">{entry.text}</V7Fact><V7Fact label="原文位置">{entry.source_anchor}</V7Fact><V7Fact label="纪要版本">{minute?.version}</V7Fact></>}
    {linked?<><V7Fact label="原任务">{linked.task_id}</V7Fact><V7Fact label="任务状态">{linked.task_status}</V7Fact><V7Fact label="发送状态">{linked.send_status}</V7Fact><button className="boss-btn boss-btn-primary" onClick={()=>{onTaskCreated(linked.task_id);onNavigate("F06");}}>打开原任务</button></>:entry?<>
      <fieldset className="boss-minute-task-fields" disabled={disabled}><div className="boss-form-grid"><label>唯一负责人<select value={form.coordinator} onChange={event=>setForm(value=>({...value,coordinator:event.target.value}))}><option value="">请选择获准联系人</option>{contacts.filter(row=>participants.includes(row.contact_id)).map(row=><option key={row.contact_id} value={row.contact_id} disabled={!row.allowed_for_fixture_assignment}>{row.name} · {row.organization} · {row.responsibility}</option>)}</select></label><label>期限（Asia/Shanghai）<input type="datetime-local" value={form.due} onChange={event=>setForm(value=>({...value,due:event.target.value}))}/></label></div><label className="boss-field">交办目的与产物<textarea rows={3} value={form.purpose} onChange={event=>setForm(value=>({...value,purpose:event.target.value}))}/></label><label className="boss-field">证据要求<input value={form.evidence} onChange={event=>setForm(value=>({...value,evidence:event.target.value}))}/></label></fieldset>
      <div className="boss-actions"><button className="boss-btn boss-btn-primary" disabled={disabled} onClick={propose}>审阅并创建单项交办</button><button className="boss-btn" disabled={transaction.busy} onClick={()=>select("")}>取消当前编辑</button></div>
    </>:<V7Empty title={candidates.length?"请选择当前纪要中的交办草稿":"当前纪要没有交办草稿"}/>}
    {error&&<p role="alert" className="boss-status boss-status-error">{error}</p>}
    <div className="boss-actions"><button className="boss-btn" disabled={transaction.busy} onClick={onReload}>核对纪要与任务版本</button></div><p className="boss-v7-note">创建、发送和任务完成分别由本人决定。原版本关联任务继续保留。</p>
    {transaction.dialog}
    <Dialog.Root open={nextEntry!==null} onOpenChange={open=>{if(!open)setNextEntry(null);}}><Dialog.Portal><Dialog.Overlay className="boss-v7-dialog-overlay"/><Dialog.Content className="boss-v7-dialog"><Dialog.Title>当前条目存在未保存编辑</Dialog.Title><Dialog.Description>切换条目前可以继续编辑，或者放弃本次尚未提交的交办内容。</Dialog.Description><div className="boss-actions"><Dialog.Close asChild><button className="boss-btn">继续编辑</button></Dialog.Close><button className="boss-btn" disabled={transaction.busy} onClick={()=>{if(nextEntry!==null)select(nextEntry);}}>放弃编辑并切换条目</button></div></Dialog.Content></Dialog.Portal></Dialog.Root>
  </V7Panel>;
}
