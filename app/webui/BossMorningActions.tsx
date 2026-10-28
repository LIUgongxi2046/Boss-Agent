import {useEffect,useState,type ReactNode} from "react";
import * as Dialog from "@radix-ui/react-dialog";
import type {TodayItem,TodayProjection} from "./BossToday";
import {morningState} from "./BossToday";
import {useOwnerWorkspace} from "./useTechnicalWorkspace";
import {V7Pagination,V7ReadState} from "./BossV7UI";
type Action="approve"|"reject"|"delegate";
type Item=TodayItem&{approval:{amount:string;currency:string;source_id:string}|null};
type Projection={projection:"morning-actions";date:string;timezone:string;snapshot_sha256:string;items:Item[];
  secretary:{version:string;recipient_id:string;recipient_name:string;channel:string;address:string}|null;
  messages:{message_id:string;recipient_name:string;body:string;reply_state:string}[];replies:{reply_id:string;reply_to:string;text:string}[]};
type Props={data:TodayProjection|null;category:TodayItem["category"]|"ALL";children:ReactNode;loading:boolean;disabled:boolean;
  contacts:{contact_id:string;name:string}[];onSelectItem:(item:TodayItem)=>void;onAgent:(items:TodayItem[])=>void;onReload:()=>void;onDirtyChange:(value:boolean)=>void};
const LABELS:Record<Action,string>={approve:"同意",reject:"驳回",delegate:"交给秘书处理"};
export function BossMorningActions({data,category,children,loading,disabled,contacts,onSelectItem,onAgent,onReload,onDirtyChange}:Props){
  const api=useOwnerWorkspace<Projection>("morning-actions");
  const [checked,setChecked]=useState<string[]>(()=>new URLSearchParams(window.location.search).getAll("morningChecked")),[action,setAction]=useState<Action|null>(null),[comment,setComment]=useState(""),[page,setPage]=useState(1);
  const [confirmation,setConfirmation]=useState<{digest:string;secretary:Projection["secretary"];items:Item[]}|null>(null);
  const busy=disabled||loading||api.loading||api.busy||!!api.pending;
  const items=(data?.items??[]).filter(item=>category==="ALL"||item.category===category);
  const selected=(api.data?.items??[]).filter(item=>checked.includes(item.item_id));
  const valid=selected.length===checked.length&&checked.length>0&&checked.length<=50&&api.data?.date===data?.date&&api.data?.timezone===data?.timezone;
  const canDecide=valid&&selected.every(item=>item.approval!==null);
  useEffect(()=>{if(data)setChecked(previous=>previous.filter(id=>data.items.some(item=>item.item_id===id&&(category==="ALL"||item.category===category))));setPage(1);api.reload();},[data?.snapshot_sha256,category]);
  useEffect(()=>{const url=new URL(window.location.href);url.searchParams.delete("morningChecked");checked.forEach(id=>url.searchParams.append("morningChecked",id));window.history.replaceState(window.history.state,"",url);},[checked]);
  useEffect(()=>{onDirtyChange(action!==null||api.busy||!!api.pending);},[action,api.busy,api.pending,onDirtyChange]);
  useEffect(()=>{if(api.receipt){setAction(null);setConfirmation(null);setChecked([]);onReload();}},[api.receipt?.request_id]);
  function begin(next:Action){if(!valid||!api.data)return;setAction(next);setComment(next==="delegate"?"请协助处理以下事项，并反馈进展与需要我决定的问题。":"");setConfirmation({digest:api.data.snapshot_sha256,secretary:api.data.secretary,items:selected});}
  const messageBody=comment.trim()+"\n\n"+(confirmation?.items??[]).map((item,index)=>`${index+1}. ${item.title}；${item.reason}`).join("\n");
  const visiblePage=Math.min(page,Math.max(1,Math.ceil(items.length/10)));
  return <section className="boss-panel boss-f01-list" aria-label="我的当前事项">
    <header className="boss-panel-head"><h2>今天需要我参与的事</h2></header>{children}
    <V7ReadState loading={loading||api.loading} error={api.error} onReload={api.reload}/>
    <label className="boss-morning-select-all"><input type="checkbox" checked={items.length>0&&items.every(item=>checked.includes(item.item_id))} disabled={busy||items.length===0} onChange={event=>setChecked(event.target.checked?items.map(item=>item.item_id):[])}/>选择当前分类全部事项</label>
    <ul className="boss-f01-items">{items.slice((visiblePage-1)*10,visiblePage*10).map(item=><li className="boss-morning-select-row" key={item.item_id}>
      <input type="checkbox" aria-label={"选择"+item.title} checked={checked.includes(item.item_id)} disabled={busy} onChange={event=>setChecked(event.target.checked?[...checked,item.item_id]:checked.filter(id=>id!==item.item_id))}/>
      <button id={"morning-item-"+item.item_id} className="boss-f01-item" type="button" onClick={()=>onSelectItem(item)}><span className="boss-f01-item-copy"><strong>{item.title}</strong><span>{item.reason}</span><span>{item.coordinator_id==="boss-1"?"本人":contacts.find(contact=>contact.contact_id===item.coordinator_id)?.name??"待安排负责人"}{item.due_at&&" · "+new Intl.DateTimeFormat("zh-CN",{timeZone:data?.timezone,month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false}).format(new Date(item.due_at))}</span></span><span className="boss-f01-item-category">{morningState(item.state??"OPEN")}</span></button>
    </li>)}</ul>
    {!loading&&!items.length&&<p>当前分类没有待办事项。</p>}
    <V7Pagination total={items.length} page={visiblePage} pageSize={10} onChange={setPage}/>
    {checked.length>50&&<p role="status">每次可以处理最多五十项，请减少所选事项。</p>}
    <div className="boss-actions"><span>已选择 {checked.length} 项</span>{(["approve","reject","delegate"] as const).map(value=><button className="boss-btn" key={value} disabled={busy||(value==="delegate"?!valid||!api.data?.secretary:!canDecide)} title={value==="delegate"&&!api.data?.secretary?"请管理员配置秘书":value!=="delegate"&&!canDecide?"请选择待决定申请":undefined} onClick={()=>begin(value)}>{LABELS[value]}</button>)}<button className="boss-btn boss-btn-primary" disabled={busy||!valid} onClick={()=>onAgent(selected)}>让 Boss Agent 处理</button></div>
    {api.pending&&<button className="boss-btn" disabled={api.busy} onClick={()=>void api.reconcile().then(onReload)}>查询处理结果</button>}
    {api.receipt&&<p role="status">{api.receipt.action==="delegate"?"交办消息已模拟发送，等待秘书回复。":"处理结果已保存。"}</p>}
    {!!api.data?.messages.length&&<details><summary>秘书交办与回复</summary>{api.data.messages.map(message=><article className="boss-workspace-item" key={message.message_id}><strong>{message.recipient_name}</strong><p style={{whiteSpace:"pre-wrap"}}>{message.body}</p>{api.data!.replies.filter(reply=>reply.reply_to===message.message_id).map(reply=><p key={reply.reply_id}>秘书回复：{reply.text}</p>)}{message.reply_state==="NOT_RECEIVED"&&<p>等待回复</p>}</article>)}</details>}
    <Dialog.Root open={action!==null} onOpenChange={open=>{if(!open&&!api.busy&&!api.pending){setAction(null);setConfirmation(null);}}}><Dialog.Portal><Dialog.Overlay className="boss-dialog-overlay"/><Dialog.Content className="boss-dialog-content"><Dialog.Title>{action?LABELS[action]:"处理事项"}</Dialog.Title><Dialog.Description>请核对所选事项与处理内容。</Dialog.Description>
      {action==="delegate"&&confirmation?.secretary&&<p>接收人：{confirmation.secretary.recipient_name} · {confirmation.secretary.channel==="EMAIL"?"邮件":"内部 IM"} · {confirmation.secretary.address}</p>}
      <ul>{confirmation?.items.map(item=><li key={item.item_id}><strong>{item.title}</strong>{item.approval&&<p>申请金额：{item.approval.amount} {item.approval.currency==="CNY"?"元":item.approval.currency}</p>}</li>)}</ul>
      <label className="boss-field">{action==="delegate"?"交办消息":"处理意见"}<textarea required maxLength={1200} value={comment} onChange={event=>setComment(event.target.value)} disabled={api.busy}/></label>
      {action==="delegate"&&<><h3>完整消息预览</h3><p style={{whiteSpace:"pre-wrap"}}>{messageBody}</p>{messageBody.length>2400&&<p role="alert">消息超过两千四百字，请减少所选事项或缩短处理要求。</p>}</>}
      {api.error&&<p role="alert">{api.error}</p>}
      {api.pending&&<button className="boss-btn" disabled={api.busy} onClick={()=>void api.reconcile().then(onReload)}>查询处理结果</button>}
      <div className="boss-actions"><Dialog.Close asChild><button className="boss-btn" disabled={api.busy||!!api.pending}>取消</button></Dialog.Close><button className="boss-btn boss-btn-primary" disabled={busy||!comment.trim()||!confirmation||action==="delegate"&&messageBody.length>2400} onClick={()=>{if(!action||!confirmation)return;void api.execute(action,{snapshot_sha256:confirmation.digest,item_ids:confirmation.items.map(item=>item.item_id),comment,...(action==="delegate"?{secretary_version:confirmation.secretary?.version}:{})}).then(saved=>{if(saved){setAction(null);setConfirmation(null);setChecked([]);onReload();}});}}>确认{action==="delegate"?"发送":action?LABELS[action]:"处理"}</button></div>
    </Dialog.Content></Dialog.Portal></Dialog.Root>
  </section>;
}
