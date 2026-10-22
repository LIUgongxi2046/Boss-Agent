import { useEffect, useState } from "react";
import { AlertCircle, CheckCircle2, Loader2, MessageSquareText, RefreshCw, ShieldCheck } from "lucide-react";
import { useClient } from "@/providers/ClientProvider";
type Row = {
  message_id:string;recipient_id:string;send_state:string;reply_state:string;
  related_task_id:string|null;
};
type Listing={source_type:"SIMULATED";projection:"message-admin";
  pending_reply_refs:Row[];raw_message_text_returned:false};

export function MaintainerMessageReply() {
  const {client,getToken}=useClient();
  const [list,setList]=useState<Row[]>([]);
  const [selected,setSelected]=useState("");
  const [text,setText]=useState("");
  const [revision,setRevision]=useState(0);
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [pending,setPending]=useState<{key:string;message_id:string;author:string;text:string}|null>(null);
  const [checked,setChecked]=useState(false);
  const [busy,setBusy]=useState(false);
  useEffect(()=>{
    const abort=new AbortController();
    const token=getToken();
    if(!token){setError("技术身份未认证");return;}
    setLoading(true);
    void fetch("/api/boss/ui/workspace/message-admin",{
      headers:{Authorization:"Bearer "+token},cache:"no-store",signal:abort.signal,
    }).then(async response=>{
      if(!response.ok)throw Error("无权读取模拟消息技术索引");
      const payload=await response.json() as Listing;
      if(payload.source_type!=="SIMULATED"||payload.projection!=="message-admin")
        throw Error("当前技术索引来源无效");
      return payload;
    }).then(payload=>{
      if(abort.signal.aborted)return;
      setList(payload.pending_reply_refs);
      setLoading(false);
    }).catch(e=>{
      if(abort.signal.aborted)return;
      setError(e instanceof Error?e.message:String(e));setLoading(false);
    });
    return ()=>abort.abort();
  },[getToken,revision]);
  const row=list.find(x=>x.message_id===selected);
  function prepare(){
    setError("");
    if(!row||row.send_state!=="SENT_SIMULATED"||row.reply_state!=="NOT_RECEIVED"){
      setError("请选择已经模拟发送、尚未模拟回复的消息");return;
    }
    if(!text.trim()||text.length>2400){setError("模拟回复必须是 1—2400 字");return;}
    setPending({key:"boss-"+crypto.randomUUID(),
      message_id:row.message_id,author:row.recipient_id,text:text.trim()});
    setChecked(false);
  }
  async function submit(){
    if(!checked||!pending||busy)return;
    setBusy(true);setError("");
    try{
      const result=await client.requestMutation<{
        reply_id:string;reply_state:string;task_status_after_reply:string|null;
        task_completion_confirmed:false;
      }>("boss.simulation.message.reply",{
        client_request_id:pending.key,
        message_id:pending.message_id,
        author_contact_id:pending.author,text:pending.text,
      });
      setNotice("已持久化模拟回复："+result.reply_id+
        "；关联任务："+(result.task_status_after_reply||"未变更")+
        "；完成确认：否。");
      setPending(null);setChecked(false);setText("");
      setRevision(v=>v+1);
    }catch(e){
      setError((e instanceof Error?e.message:String(e))+
        "。回执不确定时先重新查询，同一弹窗重试保留幂等标识。");
    }finally{setBusy(false);}
  }
  return <>
    <section className="boss-panel">
      <div className="boss-panel-head">
        <h2>模拟联系人回复</h2><small>A04 · 非员工登录 · 仅维护注入</small>
      </div>
      <p className="boss-helper">技术端只能读取消息 ID、收件人 ID 与模拟状态，不能查看老板正文。回复由服务端绑定先前模拟收件人；不支持伪造老板完成决定。</p>
      <div className="boss-form-grid">
        <label>选择已模拟发送消息
          <select value={selected} onChange={e=>setSelected(e.target.value)}>
            <option value="">请选择当前消息 ID</option>
            {list.filter(x=>x.send_state==="SENT_SIMULATED"&&x.reply_state==="NOT_RECEIVED")
              .map(x=><option key={x.message_id} value={x.message_id}>
                {x.message_id} · 联系人 {x.recipient_id}
              </option>)}
          </select>
        </label>
      </div>
      {row&&<div className="boss-kv"><span>关联交办</span>
        <strong>{row.related_task_id||"无"}</strong></div>}
      <label className="boss-label" htmlFor="boss-sim-reply-text">明确的模拟回复</label>
      <textarea id="boss-sim-reply-text" rows={3} value={text}
        onChange={e=>setText(e.target.value)}
        placeholder="例如：资料正在核查，当前还不能确认完成。"/>
      {error&&<div role="alert" className="boss-status boss-status-error">
        <AlertCircle size={16}/>{error}
      </div>}
      {notice&&<div role="status" className="boss-status boss-status-ok">
        <CheckCircle2 size={16}/>{notice}
      </div>}
      <div className="boss-actions">
        <button type="button" className="boss-btn boss-btn-primary" onClick={prepare} disabled={busy}>
          <MessageSquareText size={15}/> 核对模拟回复</button>
        <button type="button" className="boss-btn" onClick={()=>setRevision(x=>x+1)}>
          <RefreshCw size={15}/> 重新读取</button>
      </div>
    </section>
    {pending&&<div className="boss-confirm-backdrop">
      <section className="boss-confirm" role="dialog" aria-modal="true"
        aria-labelledby="boss-reply-review">
        <h3 id="boss-reply-review"><ShieldCheck size={18}/> 确认模拟回复</h3>
        <p>消息 ID：{pending.message_id}。来源为模拟联系人 {pending.author}，不是新增的员工账号。</p>
        <blockquote className="boss-source">{pending.text}</blockquote>
        <label className="boss-confirm-check">
          <input type="checkbox" checked={checked} disabled={busy}
            onChange={e=>setChecked(e.target.checked)}/>
          <span>确认只注入模拟回复，不直接完成交办或冒充真实外部送达。</span>
        </label>
        {error&&<p className="boss-validation-error">{error}</p>}
        <div className="boss-actions">
          <button type="button" className="boss-btn" disabled={busy}
            onClick={()=>{setPending(null);setChecked(false);}}>取消</button>
          <button type="button" className="boss-btn boss-btn-primary"
            disabled={!checked||busy} onClick={()=>void submit()}>
            {busy&&<Loader2 size={15} className="boss-spin"/>} 确认并提交
          </button>
        </div>
      </section>
    </div>}
  </>;
}
