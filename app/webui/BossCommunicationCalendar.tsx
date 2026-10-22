import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import {
  AlertCircle, ArrowLeft, CalendarDays, CheckCircle2, Clock3, FileSearch,
  FolderOpen, Loader2, MessageSquareText, RefreshCw, Send, ShieldCheck, X,
} from "lucide-react";
import { useClient } from "@/providers/ClientProvider";
import "./boss-v6.css";

type Contact = {
  contact_id:string;name:string;organization:string;responsibility:string;
};
type Reference = {source_id:string;version:string};
type Draft = {
  draft_id:string;version:string;status:"DRAFT"|"SENT_SIMULATED";
  recipient_id:string;recipient_name_at_save:string;organization_at_save:string;
  related_task_id:string|null;body:string;attachment_refs:Reference[];
  content_sha256:string;message_id:string|null;
};
type Sent = {
  message_id:string;draft_id:string;recipient_id:string;
  send_state:"SENT_SIMULATED";delivery_state:string;reply_state:string;
  sent_at:string;related_task_id:string|null;external_channel_invoked:boolean;
};
type Reply = {
  reply_id:string;reply_to:string;text:string;author_contact_id:string;received_at:string;
};
type Outbox = {
  source_type:"SIMULATED";projection:"outbox";data_version:string;
  drafts:Draft[];sent_messages:Sent[];replies:Reply[];
  contacts:Contact[];task_ids:string[];messages:Record<string,unknown>[];
};
type Calendar = {
  calendar_id:string;version:string;status:"ACTIVE"|"DELETED";
  starts_at:string;ends_at:string;timezone:string;title?:string;
  location?:string;private_body:string;attachment_refs:Reference[];
};
type BusyShare = {
  share_id:string;calendar_version:string;recipient_id:string;
  busy:boolean;starts_at:string;ends_at:string;timezone:string;
  expires_at:string;revoked:boolean;
};
type CalendarData = {
  source_type:"SIMULATED";projection:"calendar";data_version:string;
  calendar:Calendar;shares:BusyShare[];
  meeting:{meeting_id:string;starts_at:string;ends_at:null;end_is_known:false};
  can_edit:boolean;physical_secure_erasure_verified:false;
};
type MutationResult = {
  draft_id?:string;version?:string;status?:string;message_id?:string;
  send_state?:string;delivery_state?:string;share_status?:string;
};
type Pending = {
  action:string;payload:Record<string,unknown>;key:string;
  title:string;lines:string[];
};
type Props = {pageId:"F08"|"F12";onNavigate:(page:string)=>void;onViewSource:(id:string)=>void};

function Block({title,note,children}: {title:string;note?:string;children:ReactNode}) {
  return <section className="boss-panel">
    <div className="boss-panel-head"><h2>{title}</h2>{note&&<small>{note}</small>}</div>{children}
  </section>;
}
function LabelValue({name,value}:{name:string;value?:string|number|boolean|null}) {
  return <div className="boss-kv"><span>{name}</span><strong>{value===undefined||value===null?"待核查":String(value)}</strong></div>;
}
function Empty({children}:{children:ReactNode}) {
  return <div className="boss-empty"><FolderOpen size={20}/><div><strong>暂无已保存记录</strong><p>{children}</p></div></div>;
}
function splitDate(raw:string) {return raw.slice(0,16);}
function isoShanghai(raw:string) {
  if (!/^\d{4}-\d\d-\d\dT\d\d:\d\d$/.test(raw)) throw Error("必须填写完整日期与时间");
  return raw+":00+08:00";
}
function validate(text:string,label:string,max=2400) {
  if(!text.trim()||text.length>max)throw Error(label+"必须填写且不超过"+max+"字");
  return text.trim();
}

function useMutation(refresh:()=>void, success?:(result:MutationResult)=>void) {
  const {client}=useClient();
  const [pending,setPending]=useState<Pending|null>(null);
  const [checked,setChecked]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [status,setStatus]=useState("");
  const modal=useRef<HTMLElement|null>(null);
  const busyRef=useRef(false);busyRef.current=busy;
  useEffect(()=>{
    if(!pending)return;
    const previous=document.activeElement instanceof HTMLElement?document.activeElement:null;
    modal.current?.focus();
    const key=(event:KeyboardEvent)=>{
      if(event.key==="Escape"&&!busyRef.current){setPending(null);setChecked(false);return;}
      if(event.key!=="Tab"||!modal.current)return;
      const nodes=Array.from(modal.current.querySelectorAll<HTMLElement>(
        'input:not([disabled]),button:not([disabled])')).filter(x=>x.getClientRects().length>0);
      if(nodes.length&&event.shiftKey&&document.activeElement===nodes[0]){
        event.preventDefault();nodes[nodes.length-1].focus();
      }else if(nodes.length&&!event.shiftKey&&document.activeElement===nodes[nodes.length-1]){
        event.preventDefault();nodes[0].focus();
      }
    };
    document.addEventListener("keydown",key);
    return ()=>{document.removeEventListener("keydown",key);previous?.focus();};
  },[pending?.key]);
  const propose=useCallback((action:string,payload:Record<string,unknown>,
                            title:string,lines:string[])=>{
    setPending({action,payload,key:"boss-"+crypto.randomUUID(),title,lines});
    setChecked(false);setStatus("");setError("");
  },[]);
  const submit=async()=>{
    if(!pending||!checked||busy)return;
    setBusy(true);setError("");
    try{
      const result=await client.requestMutation<MutationResult>(pending.action,{
        ...pending.payload,client_request_id:pending.key,
      });
      setStatus("模拟业务事务已保存："+(result.status||result.send_state||result.share_status||"已记录")+
                "。请以重新读取的状态为准。");
      success?.(result);
      setPending(null);setChecked(false);refresh();
    }catch(e){
      setError((e instanceof Error?e.message:String(e))+
        "。请求结果可能尚未同步；请先重新核查，重试会复用原请求编号。");
    }finally{setBusy(false);}
  };
  const dialog=pending?<div className="boss-confirm-backdrop">
    <section ref={modal} tabIndex={-1} className="boss-confirm" role="dialog"
      aria-modal="true" aria-labelledby="boss-private-action-title">
      <h3 id="boss-private-action-title"><ShieldCheck size={18}/>{pending.title}</h3>
      <p>仅当前 BOSS 身份可执行该动作。收件人、内容、版本或日程分享字段发生变化时，需要重新授权。</p>
      <dl>{pending.lines.map((line,i)=><div key={i}><dd>{line}</dd></div>)}</dl>
      <label className="boss-confirm-check">
        <input type="checkbox" checked={checked} disabled={busy}
          onChange={e=>setChecked(e.target.checked)}/>
        <span>我已核实本次具体内容、对象、范围与结果，并同意执行。</span>
      </label>
      {error&&<p className="boss-validation-error" role="alert">{error}</p>}
      <footer className="boss-actions">
        <button className="boss-btn" type="button" disabled={busy} onClick={()=>setPending(null)}>取消</button>
        <button className="boss-btn boss-btn-primary" type="button"
          disabled={!checked||busy} onClick={()=>void submit()}>
          {busy&&<Loader2 size={16} className="boss-spin"/>} 确认并提交
        </button>
      </footer>
    </section>
  </div>:null;
  return {propose,dialog,status,error,busy};
}

export function BossCommunicationCalendar({pageId,onNavigate,onViewSource}:Props) {
  const {getToken}=useClient();
  const isMessage=pageId==="F08";
  const [state,setState]=useState<Outbox|CalendarData|null>(null);
  const [revision,setRevision]=useState(0);
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState("");
  const [selectedDraft,setSelectedDraft]=useState("");
  const [selectedRecipient,setSelectedRecipient]=useState("");
  const [relatedTask,setRelatedTask]=useState("");
  const [messageBody,setMessageBody]=useState("");
  const [attachmentId,setAttachmentId]=useState("");
  const [attachmentVersion,setAttachmentVersion]=useState("1");
  const [dirty,setDirty]=useState(false);
  const [start,setStart]=useState("");
  const [end,setEnd]=useState("");
  const [title,setTitle]=useState("");
  const [privateBody,setPrivateBody]=useState("");
  const [location,setLocation]=useState("");
  const [conflictAcknowledged,setConflictAcknowledged]=useState(false);
  const [shareRecipient,setShareRecipient]=useState("");
  const [sharePurpose,setSharePurpose]=useState("");
  const [shareExpires,setShareExpires]=useState("");
  const reload=()=>setRevision(x=>x+1);
  const {propose,dialog,status,busy}=useMutation(reload,result=>{
    if(result.draft_id){setSelectedDraft(result.draft_id);setDirty(false);}
    if(result.version&&!isMessage)setDirty(false);
  });

  useEffect(()=>{
    const abort=new AbortController();
    const token=getToken();
    if(!token){setError("当前登录已失效");return;}
    setLoading(true);setError("");setState(null);
    const key=isMessage?"outbox":"calendar";
    void fetch("/api/boss/ui/workspace/"+key,{
      headers:{"Authorization":"Bearer "+token},cache:"no-store",signal:abort.signal,
    }).then(async response=>{
      if(!response.ok)throw Error("无法读取有权业务资料（HTTP "+response.status+"）");
      const data=await response.json() as Outbox|CalendarData;
      if(data.source_type!=="SIMULATED"||data.projection!==key)
        throw Error("当前业务来源与预期不符");
      return data;
    }).then(data=>{
      if(abort.signal.aborted)return;
      setState(data);setLoading(false);
      if(!isMessage&&!dirty){
        const c=(data as CalendarData).calendar;
        setStart(splitDate(c.starts_at));setEnd(splitDate(c.ends_at));
        setTitle(c.title||"");setPrivateBody(c.private_body||"");
        setLocation(c.location||"");
      }
    }).catch(e=>{
      if(abort.signal.aborted)return;
      setError(e instanceof Error?e.message:String(e));setLoading(false);
    });
    return ()=>abort.abort();
  },[pageId,revision,getToken]);

  const messages=isMessage?state as Outbox|null:null;
  const calendars=!isMessage?state as CalendarData|null:null;
  const draft=messages?.drafts.find(x=>x.draft_id===selectedDraft)||null;

  function chooseDraft(row:Draft) {
    setSelectedDraft(row.draft_id);setSelectedRecipient(row.recipient_id);
    setRelatedTask(row.related_task_id||"");setMessageBody(row.body);
    setAttachmentId(row.attachment_refs[0]?.source_id||"");
    setAttachmentVersion(row.attachment_refs[0]?.version||"1");
    setDirty(false);setError("");
  }
  function draftPayload(){
    return {
      draft_id:draft?.draft_id||null,
      expected_version:draft?.version||"0",
      recipient_id:selectedRecipient,related_task_id:relatedTask||null,
      body:validate(messageBody,"消息内容"),
      attachment_refs:attachmentId.trim()?[{
        source_id:attachmentId.trim(),version:attachmentVersion.trim(),
      }]:[],
      visibility:"RECIPIENT_ONLY",
    };
  }
  function saveDraft(){
    setError("");
    try{
      if(!messages?.contacts.some(c=>c.contact_id===selectedRecipient))
        throw Error("请选择稳定联系人 ID。不能仅凭显示姓名匹配");
      if(draft?.status==="SENT_SIMULATED")throw Error("已发草稿不能编辑；请新建草稿");
      const body=draftPayload();
      propose("boss.message.draft.save",body,"保存本人消息草稿",[
        "收件人："+selectedRecipient,
        "任务："+(body.related_task_id||"未绑定"),
        "附件："+(attachmentId?attachmentId+" v"+attachmentVersion:"无"),
        "正文："+body.body,
        "保存草稿不发送、不创建送达回执。",
      ]);
    }catch(e){setError(e instanceof Error?e.message:String(e));}
  }
  function sendDraft(){
    setError("");
    if(!draft){setError("请先保存并重读本条消息草稿");return;}
    if(dirty){setError("输入内容已变化，必须先保存新版本，再发送");return;}
    if(draft.status!=="DRAFT"){setError("已发出或不可发送的草稿不能重复提交");return;}
    propose("boss.message.send",{
      draft_id:draft.draft_id,expected_version:draft.version,
      recipient_id:draft.recipient_id,expected_content_sha256:draft.content_sha256,
    },"确认发送当前版本的模拟消息",[
      "唯一收件人："+draft.recipient_id+" · "+draft.organization_at_save,
      "草稿："+draft.draft_id+" / v"+draft.version,
      "正文："+draft.body,
      "附件："+draft.attachment_refs.map(x=>x.source_id+" v"+x.version).join("、"),
      "成功时仅写入模拟发件箱 SENT_SIMULATED；送达/回复各自独立核查。",
    ]);
  }
  function saveCalendar(){
    setError("");
    if(!calendars?.calendar){setError("当前私人日程未加载");return;}
    try{
      const c=calendars.calendar;
      propose("boss.calendar.save",{
        expected_version:c.version,starts_at:isoShanghai(start),ends_at:isoShanghai(end),
        timezone:"Asia/Shanghai",title,private_body:validate(privateBody,"私人日程正文",2000),
        location,attachment_refs:[],acknowledge_conflict:conflictAcknowledged,
      },"保存本人私人安排",[
        "私人安排："+start+" — "+end,
        "标题和地点将仅由老板读取："+(title||"未填写")+" / "+(location||"未填写"),
        "私人正文："+privateBody,
        "与工作会议的结束时间无法完全核实；邻近时段须由本人确认。",
        "原有效 busy 分享会因版本变化全部失效。",
      ]);
    }catch(e){setError(e instanceof Error?e.message:String(e));}
  }
  function shareCalendar(){
    setError("");
    const c=calendars?.calendar;
    if(!c||c.status!=="ACTIVE"){setError("没有可分享的有效私人日程");return;}
    try{
      propose("boss.calendar.share",{
        expected_version:c.version,recipient_id:shareRecipient,
        purpose:validate(sharePurpose,"分享用途",240),
        expires_at:isoShanghai(shareExpires),
        fields:["busy","starts_at","ends_at","timezone"],
      },"仅分享忙碌状态与时间",[
        "收件人稳定 ID："+shareRecipient,
        "用途："+sharePurpose,
        "有效期至："+shareExpires,
        "允许字段：busy、starts_at、ends_at、timezone",
        "禁止分享标题、地点、私人正文及附件。无外部实际送达。",
      ]);
    }catch(e){setError(e instanceof Error?e.message:String(e));}
  }
  function revokeShare(item:BusyShare){
    propose("boss.calendar.share.revoke",{
      share_id:item.share_id,expected_version:item.calendar_version,
    },"撤销忙碌分享授权",[
      "授权："+item.share_id,"接收联系人："+item.recipient_id,
      "撤销后停止当前查询与新分享采用；不宣称回收已传出的内容。",
    ]);
  }
  function deleteCalendar(){
    const c=calendars?.calendar;
    if(!c)return;
    propose("boss.calendar.delete",{expected_version:c.version},
      "删除本人的当前私人安排",[
        "对象："+c.calendar_id+" / v"+c.version,
        "正文停止未来读取，仍保留必要历史记录供追溯。",
        "同步撤销当前忙碌分享。不能宣称已擦除所有磁盘备份。",
      ]);
  }

  return <>
    <div className="boss-workspace-toolbar">
      <span className="boss-workspace-note"><span className="boss-tag boss-tag-amber">SIMULATED · BOSS ONLY</span>
        {isMessage?"F08 消息编辑与模拟发件箱":"F12 本人私人安排与忙碌分享"}
      </span>
      <button type="button" className="boss-btn" onClick={reload} disabled={loading}>
        {loading?<Loader2 className="boss-spin" size={15}/>:<RefreshCw size={15}/>} 重新读取
      </button>
    </div>
    {loading&&<div className="boss-status"><Loader2 size={16} className="boss-spin"/>正在读取有权版本…</div>}
    {error&&<div className="boss-status boss-status-error" role="alert"><AlertCircle size={16}/>{error}</div>}
    {status&&<div className="boss-status boss-status-ok" role="status"><CheckCircle2 size={16}/>{status}</div>}
    <div className="boss-columns">
      <div className="boss-column">
        {isMessage?<>
          <Block title="消息编辑" note="收件人、正文、附件和版本逐项核对">
            <div className="boss-form-grid">
              <label>选择唯一联系人
                <select value={selectedRecipient} onChange={e=>{setSelectedRecipient(e.target.value);setDirty(true);}}>
                  <option value="">请选择</option>
                  {(messages?.contacts||[]).map(c=><option key={c.contact_id} value={c.contact_id}>
                    {c.name} · {c.organization} · {c.responsibility} [{c.contact_id}]
                  </option>)}
                </select>
              </label>
              <label>关联任务
                <select value={relatedTask} onChange={e=>{setRelatedTask(e.target.value);setDirty(true);}}>
                  <option value="">不关联任务</option>
                  {(messages?.task_ids||[]).map(id=><option key={id} value={id}>{id}</option>)}
                </select>
              </label>
              <label>有权附件来源标识<input value={attachmentId}
                onChange={e=>{setAttachmentId(e.target.value);setDirty(true);}}
                placeholder="无附件请留空"/></label>
              <label>附件当前版本<input value={attachmentVersion}
                onChange={e=>{setAttachmentVersion(e.target.value);setDirty(true);}}/></label>
            </div>
            <label className="boss-label" htmlFor="boss-msg-text">消息正文</label>
            <textarea id="boss-msg-text" rows={5} value={messageBody}
              onChange={e=>{setMessageBody(e.target.value);setDirty(true);}}
              placeholder="明确的模拟收件人、用途及正文；不会默认向同名联系人发送。"/>
            <div className="boss-actions">
              <button type="button" className="boss-btn" disabled={busy} onClick={()=>{
                setSelectedDraft("");setSelectedRecipient("");setRelatedTask("");setMessageBody("");
                setAttachmentId("");setDirty(false);
              }}>新建草稿</button>
              <button type="button" className="boss-btn" onClick={saveDraft} disabled={busy}>
                <ShieldCheck size={15}/> 保存当前草稿</button>
              <button type="button" className="boss-btn boss-btn-primary"
                disabled={!draft||dirty||busy||draft.status!=="DRAFT"} onClick={sendDraft}>
                <Send size={15}/> 审核并模拟发送</button>
            </div>
            <div className="boss-status boss-status-warn"><AlertCircle size={16}/>
              已保存并回读的 DRAFT 才能模拟发送。修改收件人、附件或正文后，旧确认一律无效。
            </div>
          </Block>
          <Block title="已保存草稿与消息时间线" note="草稿 / SENT / 送达核查 / 回复分开">
            {(messages?.drafts||[]).length?(messages?.drafts||[]).map(d=><button
              type="button" className={"boss-task-row "+(selectedDraft===d.draft_id?"selected":"")}
              key={d.draft_id} onClick={()=>chooseDraft(d)}>
              <span className="boss-task-icon"><MessageSquareText size={18}/></span>
              <span><strong>{d.recipient_name_at_save} · {d.organization_at_save}</strong>
                <small>{d.draft_id} · v{d.version} · {d.status}</small>
                <small>收件人 ID：{d.recipient_id}</small>
              </span><ArrowLeft size={15}/>
            </button>):<Empty>请先保存有权消息草稿。</Empty>}
            {(messages?.sent_messages||[]).map(row=><div className="boss-workspace-item" key={row.message_id}>
              <strong>{row.message_id}</strong>
              <LabelValue name="实际模拟发送">{row.send_state}</LabelValue>
              <LabelValue name="送达状态">{row.delivery_state}</LabelValue>
              <LabelValue name="回复状态">{row.reply_state}</LabelValue>
              <LabelValue name="联系人">{row.recipient_id}</LabelValue>
              {(messages?.replies||[]).filter(reply=>reply.reply_to===row.message_id).map(reply=>
                <div className="boss-msg-reply" key={reply.reply_id}>
                  <span>模拟回复 · {reply.author_contact_id}</span><p>{reply.text}</p>
                </div>)}
            </div>)}
            <div className="boss-actions">
              <button type="button" className="boss-btn" onClick={()=>onNavigate("F06")}>
                查看交办状态 <ArrowLeft size={15}/></button>
            </div>
          </Block>
        </>:<>
          <Block title="私人安排编辑" note="FR12 · 标题、地点、正文默认仅本人可见">
            {calendars?.calendar?<div className="boss-form-grid">
              <label>开始（北京时间）<input type="datetime-local" value={start} disabled={!calendars.can_edit}
                onChange={e=>{setStart(e.target.value);setDirty(true);}}/></label>
              <label>结束（北京时间）<input type="datetime-local" value={end} disabled={!calendars.can_edit}
                onChange={e=>{setEnd(e.target.value);setDirty(true);}}/></label>
              <label>私人标题<input value={title} disabled={!calendars.can_edit}
                onChange={e=>{setTitle(e.target.value);setDirty(true);}}/></label>
              <label>地点<input value={location} disabled={!calendars.can_edit}
                onChange={e=>{setLocation(e.target.value);setDirty(true);}}/></label>
            </div>:<Empty>正在等待本人私有日程。</Empty>}
            <label className="boss-label" htmlFor="boss-private-body">私人正文（禁止向维护者显示）</label>
            <textarea id="boss-private-body" rows={4} value={privateBody}
              disabled={!calendars?.can_edit}
              onChange={e=>{setPrivateBody(e.target.value);setDirty(true);}}/>
            <label className="boss-confirm-check">
              <input type="checkbox" checked={conflictAcknowledged}
                onChange={e=>setConflictAcknowledged(e.target.checked)}/>
              <span>会议缺少结束时间时，我已核查临近时间的冲突风险。</span>
            </label>
            <div className="boss-actions">
              <button type="button" className="boss-btn boss-btn-primary"
                disabled={!calendars?.can_edit||busy} onClick={saveCalendar}>
                <ShieldCheck size={15}/> 保存本人私人安排</button>
              <button type="button" className="boss-btn"
                disabled={!calendars?.can_edit||busy} onClick={deleteCalendar}>删除私人安排</button>
            </div>
            <div className="boss-status boss-status-warn"><Clock3 size={16}/>
              只能核对已知会议开始时间；会议缺少结束时间，无法推断精确冲突。保存后原 busy 分享将失效。
            </div>
          </Block>
          <Block title="仅分享忙碌时段" note="不暴露标题、地点或正文">
            <div className="boss-form-grid">
              <label>分享给稳定联系人
                <select value={shareRecipient} onChange={e=>setShareRecipient(e.target.value)}>
                  <option value="">请选择联系人 ID</option>
                  <option value="coordinator-1">陈明 · 业务统筹 [coordinator-1]</option>
                  <option value="finance-1">李文 · 财务材料作者 [finance-1]</option>
                  <option value="contact-2">陈明 · 客户联系人 [contact-2]</option>
                </select>
              </label>
              <label>授权有效期（北京时间）<input type="datetime-local"
                value={shareExpires} onChange={e=>setShareExpires(e.target.value)}/></label>
            </div>
            <label className="boss-label">用途</label>
            <textarea rows={2} value={sharePurpose} onChange={e=>setSharePurpose(e.target.value)}
              placeholder="例如：只告知当前时段已被占用。"/>
            <div className="boss-actions">
              <button type="button" className="boss-btn boss-btn-primary"
                disabled={!calendars?.can_edit||busy||dirty||!shareRecipient} onClick={shareCalendar}>
                <ShieldCheck size={15}/> 确认分享 busy 字段</button>
            </div>
            <div className="boss-status"><ShieldCheck size={16}/>
              有效共享字段固定为 busy、starts_at、ends_at、timezone。当前为本地模拟授权，没有真实外部投递。
            </div>
          </Block>
          <Block title="已有分享和撤销记录" note="逐项核查版本及撤销时间">
            {(calendars?.shares||[]).length?(calendars?.shares||[]).map(share=>
              <div key={share.share_id} className="boss-workspace-item">
                <strong>{share.share_id}</strong>
                <LabelValue name="接收人 ID">{share.recipient_id}</LabelValue>
                <LabelValue name="时段">{share.starts_at.replace("T"," ")+" — "+share.ends_at.replace("T"," ")}</LabelValue>
                <LabelValue name="授权版本">{share.calendar_version}</LabelValue>
                <LabelValue name="状态">{share.revoked?"已撤销":"有效模拟分享"}</LabelValue>
                {!share.revoked&&<div className="boss-actions">
                  <button type="button" className="boss-btn" disabled={busy} onClick={()=>revokeShare(share)}>
                    <X size={15}/> 明确撤销分享</button>
                </div>}
              </div>):<Empty>没有已生效的忙碌分享记录。</Empty>}
          </Block>
        </>}
      </div>
      <div className="boss-column">
        <Block title="当前业务与权限范围">
          <LabelValue name="工作台">{pageId}</LabelValue>
          <LabelValue name="资料版本">{state?.data_version}</LabelValue>
          <LabelValue name="数据属性">{state?.source_type}</LabelValue>
          {isMessage?<>
            <LabelValue name="已选择草稿版本">{draft?.version}</LabelValue>
            <LabelValue name="已保存草稿数">{messages?.drafts.length}</LabelValue>
            <LabelValue name="模拟发送数">{messages?.sent_messages.length}</LabelValue>
            <LabelValue name="已有模拟回复">{messages?.replies.length}</LabelValue>
            <LabelValue name="真实投递渠道">未接入</LabelValue>
            <div className="boss-actions">
              <button type="button" className="boss-btn" onClick={()=>onViewSource("finance-note")}>
                <FileSearch size={15}/> 打开已授权来源</button>
            </div>
          </>:<>
            <LabelValue name="日程版本">{calendars?.calendar.version}</LabelValue>
            <LabelValue name="私人正文可见性">BOSS ONLY</LabelValue>
            <LabelValue name="当前生效分享数">{calendars?.shares.filter(x=>!x.revoked).length}</LabelValue>
            <LabelValue name="私人资料物理擦除">未独立验证</LabelValue>
            <LabelValue name="会议原定开始">{calendars?.meeting.starts_at.replace("T"," ")}</LabelValue>
            <LabelValue name="会议结束时间">未知</LabelValue>
          </>}
          <div className="boss-actions">
            <button type="button" className="boss-btn" onClick={()=>onNavigate("F01")}>
              <ArrowLeft size={15}/> 返回今日工作</button>
          </div>
        </Block>
      </div>
    </div>
    {dialog}
  </>;
}
