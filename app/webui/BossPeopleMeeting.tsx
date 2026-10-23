import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  AlertCircle, CheckCircle2, ClipboardCheck, FileSearch, Loader2,
  RefreshCw, ShieldCheck, Users, XCircle,
} from "lucide-react";
import { useClient } from "@/providers/ClientProvider";

type Contact={
  contact_id:string;name:string;organization:string;responsibility:string;
  valid_from:string;valid_until:string;
};
type Source={
  source_id:string;version:string;excerpt:string|null;author_contact_id?:string;
  published_at?:string;source_type:"SIMULATED";
};
type Task={
  task_id:string;version:string;status:string;due_at?:string;
  evidence_requirements:string[];is_historical:boolean;
};
type Feedback={
  feedback_id:string;task_id:string;kind:string;
  author_contact_id?:string;evidence_source_ids:string[];
};
type Compiled={
  contact:Contact;purpose:string;
  meeting:{meeting_id:string|null;version:string|null;contact_is_participant:boolean};
  goals:string[];sources:Source[];tasks:Task[];feedback:Feedback[];
  questions:{task_id:string;text:string}[];
  has_original_evidence:boolean;
};
type Brief={
  brief_id:string;version:string;state:string;compiled:Compiled;
  compiled_sha256:string;linked_meeting_version:string|null;
  live_evidence_current:boolean;prepared_at:string;
};
type Projection={
  projection:"people";source_type:"SIMULATED";data_version:string;
  briefs:Brief[];contacts:Contact[];
  meeting:{meeting_id:string;version:string;participant_ids:string[];starts_at:string};
  business_clock:string;
};
type Result={brief_id:string;version:string;state:string;authorization_id?:string};
type Pending={
  action:string;payload:Record<string,unknown>;key:string;
  title:string;description:string[];
};
type Props={onNavigate:(page:string)=>void;onViewSource:(source:string)=>void};

function Panel({title,children,note}:{
  title:string;children:ReactNode;note?:string;
}) {
  return <section className="boss-panel">
    <div className="boss-panel-head"><h2>{title}</h2>{note&&<small>{note}</small>}</div>
    {children}
  </section>;
}
function Fact({label,children}:{label:string;children:ReactNode}) {
  return <div className="boss-kv"><span>{label}</span><strong>{children}</strong></div>;
}
export function BossPeopleMeeting({onNavigate,onViewSource}:Props){
  const {client,getToken}=useClient();
  const [data,setData]=useState<Projection|null>(null);
  const [revision,setRevision]=useState(0);
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [briefId,setBriefId]=useState("");
  const [contactId,setContactId]=useState("");
  const [purpose,setPurpose]=useState("");
  const [sourceId,setSourceId]=useState("");
  const [sourceVersion,setSourceVersion]=useState("");
  const [meetingId,setMeetingId]=useState("");
  const [unlinkReason,setUnlinkReason]=useState("");
  const [pending,setPending]=useState<Pending|null>(null);
  const [approved,setApproved]=useState(false);
  const [busy,setBusy]=useState(false);
  const [checking,setChecking]=useState(false);
  const modalRef=useRef<HTMLElement|null>(null);
  const selected=data?.briefs.find(x=>x.brief_id===briefId);
  const current=data?.contacts.find(x=>x.contact_id===contactId);
  const reload=()=>setRevision(x=>x+1);

  useEffect(()=>{
    const controller=new AbortController();
    const token=getToken();
    if(!token){setError("老板身份已失效，请重新认证");return;}
    setLoading(true);
    void fetch("/api/boss/ui/workspace/people",{
      headers:{Authorization:"Bearer "+token},signal:controller.signal,cache:"no-store",
    }).then(async res=>{
      if(!res.ok)throw new Error("会面材料读取失败（HTTP "+res.status+"）");
      const projection=await res.json() as Projection;
      if(projection.source_type!=="SIMULATED"||projection.projection!=="people")
        throw new Error("资料不属于获准的会面范围");
      return projection;
    }).then(result=>{
      if(controller.signal.aborted)return;
      setData(result);setLoading(false);
    }).catch(e=>{
      if(controller.signal.aborted)return;
      setError(e instanceof Error?e.message:String(e));setLoading(false);
    });
    return ()=>controller.abort();
  },[getToken,revision]);

  useEffect(()=>{
    if(!pending)return;
    const previous=document.activeElement instanceof HTMLElement?document.activeElement:null;
    modalRef.current?.focus();
    function onKey(e:KeyboardEvent){
      if(e.key==="Escape"&&!busy&&!checking){
        setPending(null);setApproved(false);return;
      }
      if(e.key!=="Tab"||!modalRef.current)return;
      const buttons=Array.from(modalRef.current.querySelectorAll<HTMLElement>(
        "input:not([disabled]),button:not([disabled])",
      )).filter(el=>el.getClientRects().length>0);
      if(!buttons.length)return;
      if(e.shiftKey&&document.activeElement===buttons[0]){
        e.preventDefault();buttons[buttons.length-1].focus();
      }else if(!e.shiftKey&&document.activeElement===buttons[buttons.length-1]){
        e.preventDefault();buttons[0].focus();
      }
    }
    document.addEventListener("keydown",onKey);
    return ()=>{document.removeEventListener("keydown",onKey);previous?.focus();};
  },[pending?.key,busy,checking]);

  function useBrief(id:string) {
    setBriefId(id);setError("");setNotice("");
    const saved=data?.briefs.find(x=>x.brief_id===id);
    if(!saved)return;
    const x=saved.compiled;
    setContactId(x.contact.contact_id);setPurpose(x.purpose);
    setMeetingId(x.meeting.meeting_id||"");
    setSourceId(x.sources[0]?.source_id||"");
    setSourceVersion(x.sources[0]?.version||"");
  }
  function reset(){
    setBriefId("");setContactId("");setPurpose("");setSourceId("");
    setSourceVersion("");setMeetingId("");setUnlinkReason("");
    setError("");setNotice("");
  }
  function propose(action:string,payload:Record<string,unknown>,title:string,description:string[]) {
    setPending({action,payload,title,description,key:"boss-"+crypto.randomUUID()});
    setApproved(false);setError("");setNotice("");
  }
  function prepare(){
    if(!current||!purpose.trim()){setError("请先指定联系人稳定 ID 和会面目的");return;}
    if((sourceId.trim()&&!sourceVersion.trim())||(!sourceId.trim()&&sourceVersion.trim())){
      setError("原文来源 ID 和版本需要同时填写");return;
    }
    propose("boss.people.prepare",{
      brief_id:briefId||null,expected_version:selected?.version||"0",
      contact_id:contactId,purpose:purpose.trim(),meeting_id:meetingId||null,
      source_refs:sourceId.trim()?[{
        source_id:sourceId.trim(),version:sourceVersion.trim(),
      }]:[],
    },"保存本人会面准备材料",[
      "对象："+current.name+" / "+current.organization+" / "+contactId,
      "当前职责："+current.responsibility+"；有效期："+current.valid_from+" 至 "+current.valid_until,
      "目的："+purpose.trim(),
      "拟关联会议："+(meetingId||"暂未选择"),
      "证据："+(sourceId?sourceId+" v"+sourceVersion:"没有主动指定来源"),
      "仅保存可回查的工作事实，不发送消息或邀请。",
    ]);
  }
  function attach(){
    if(!selected||!selected.live_evidence_current||!selected.compiled.meeting.meeting_id){
      setError("资料没有通过现时核查，或尚未关联已有会议；请重新准备");return;
    }
    if(selected.linked_meeting_version!==null){
      setError("该会面已经关联会议，不得重复执行");return;
    }
    propose("boss.people.attach",{
      brief_id:selected.brief_id,expected_version:selected.version,
      meeting_id:selected.compiled.meeting.meeting_id,
      meeting_version:selected.compiled.meeting.version,
      compiled_sha256:selected.compiled_sha256,
    },"确认加入现有会议议题",[
      "联系人："+selected.compiled.contact.contact_id,
      "会议："+selected.compiled.meeting.meeting_id+" v"+selected.compiled.meeting.version,
      "材料："+selected.brief_id+" v"+selected.version,
      "将本次会面准备材料登记到会议议题中；不增加参会人员、不发送邀请或更改外部会议。",
    ]);
  }
  function detach(){
    if(!selected||!unlinkReason.trim()){setError("请选择已关联材料并填写解除原因");return;}
    propose("boss.people.detach",{
      brief_id:selected.brief_id,expected_version:selected.version,
      reason:unlinkReason.trim(),
    },"解除会议议题关联",[
      "会面材料："+selected.brief_id+" v"+selected.version,
      "解除原因："+unlinkReason.trim(),
      "只取消应用内模拟议题关联，不向外部发送取消消息。",
    ]);
  }
  function applied(result:Result){
    if(result.brief_id)setBriefId(result.brief_id);
    setNotice("SQLite 业务记录已保存："+result.state+"，版本 "+result.version+
      "；请以重新读取的来源状态为准。");
    setPending(null);setApproved(false);reload();
  }
  async function submit(){
    if(!pending||!approved||busy||checking)return;
    setBusy(true);setError("");
    try{
      const result=await client.requestMutation<Result>(pending.action,{
        ...pending.payload,client_request_id:pending.key,
      });
      applied(result);
    }catch(e){
      setError((e instanceof Error?e.message:String(e))+
        "。结果可能已经保存；请核查原请求回执，重试必须复用同一编号。");
    }finally{setBusy(false);}
  }
  async function reconcile(){
    if(!pending||busy||checking)return;
    const token=getToken();
    if(!token){setError("身份过期，无法查询操作回执");return;}
    setChecking(true);setError("");
    try{
      const params=new URLSearchParams({
        action:pending.action,client_request_id:pending.key,
      });
      const response=await fetch("/api/boss/ui/operation-status?"+params.toString(),{
        headers:{Authorization:"Bearer "+token},cache:"no-store",
      });
      if(!response.ok)throw new Error("幂等回执读取失败（HTTP "+response.status+"）");
      const result=await response.json() as {
        action:string;client_request_id:string;outcome:string;result?:Result;
      };
      if(result.action!==pending.action||result.client_request_id!==pending.key)
        throw new Error("回执动作或请求编号不匹配");
      if(result.outcome==="RECORDED"&&result.result)applied(result.result);
      else if(result.outcome==="NOT_FOUND_IN_CURRENT_STORE"){
        setError("当前数据库尚无此编号的回执；不等于执行失败，可核对对象后用原编号重试。");
        reload();
      }else throw new Error("无法识别执行结果，已阻止二次提交");
    }catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setChecking(false);}
  }

  return <>
    <div className="boss-workspace-toolbar">
      <span className="boss-workspace-note">
        <span className="boss-tag boss-tag-amber">SIMULATED · BOSS ONLY</span>
        F10 · 人员会面 · 当前职责 / 历史交办 / 会议议题
      </span>
      <button type="button" className="boss-btn" onClick={reload} disabled={loading}>
        {loading?<Loader2 size={15} className="boss-spin"/>:<RefreshCw size={15}/>} 重读工作事实
      </button>
    </div>
    {error&&<div className="boss-status boss-status-error" role="alert">
      <AlertCircle size={16}/>{error}
    </div>}
    {notice&&<div className="boss-status boss-status-ok" role="status">
      <CheckCircle2 size={16}/>{notice}
    </div>}
    <Panel title="会面对象、职责与目的" note="按原 v6 选择栏展开完整会面条件">
      <div className="boss-form-grid">
        <label>已保存会面资料<select value={briefId}
          onChange={e=>e.target.value?useBrief(e.target.value):reset()}>
          <option value="">新建会面准备</option>
          {(data?.briefs||[]).map(item=><option key={item.brief_id} value={item.brief_id}>
            {item.compiled.contact.name} · {item.state} · v{item.version}
          </option>)}
        </select></label>
        <label>会面对象（稳定 ID）<select value={contactId}
          onChange={e=>setContactId(e.target.value)}>
          <option value="">请选择明确对象</option>
          {(data?.contacts||[]).map(c=><option key={c.contact_id} value={c.contact_id}>
            {c.name} / {c.organization} · {c.contact_id}
          </option>)}
        </select></label>
        <label>当前职责<input readOnly value={current?.responsibility||"待选择联系人"}/></label>
        <label>加入会议（仅现有已获准会议）<select value={meetingId}
          onChange={e=>setMeetingId(e.target.value)}>
          <option value="">暂不选择</option>
          {data?.meeting&&<option value={data.meeting.meeting_id}>
            {data.meeting.meeting_id} · v{data.meeting.version}
          </option>}
        </select></label>
        <label>资料来源 ID（可空）<input value={sourceId}
          onChange={e=>setSourceId(e.target.value)} maxLength={128}
          placeholder="例如本人已授权的会议纪要"/></label>
        <label>来源版本<input value={sourceVersion}
          onChange={e=>setSourceVersion(e.target.value)} maxLength={40}
          placeholder="与来源 ID 对应"/></label>
      </div>
      <label>本次会面目的<textarea value={purpose}
        onChange={e=>setPurpose(e.target.value)} rows={3} maxLength={1200}
        placeholder="请描述需要沟通的具体工作问题及期望产出"/></label>
      <div className="boss-actions">
        <button className="boss-btn boss-btn-primary" type="button"
          disabled={loading||busy||Boolean(selected?.linked_meeting_version)}
          onClick={prepare}>
          <ClipboardCheck size={15}/> 准备并保存材料
        </button>
        <button className="boss-btn" type="button" onClick={reset}>重新选择会面对象</button>
      </div>
    </Panel>
    <div className="boss-columns">
      <div className="boss-column">
        <Panel title="工作事实与待回答问题" note="只依据已授权资料和当前任务状态">
          <Fact label="当前材料状态">{selected?.state||"尚未准备"}</Fact>
          <Fact label="资料现时有效性">{selected?
            selected.live_evidence_current?"已核对当前源版本":"NEEDS_REVIEW · 请重新准备":"待读取"}</Fact>
          <Fact label="联系人有效期">{current?
            current.valid_from+" — "+current.valid_until:"待选择"}</Fact>
          {selected?.compiled.tasks.length?
            selected.compiled.tasks.map(task=><div className="boss-workspace-item" key={task.task_id}>
              <strong>{task.task_id} · {task.status}</strong>
              <small>任务版本 {task.version} · 截止 {task.due_at||"未提供"}
                {task.is_historical?" · 历史承诺":""}</small>
              <p className="boss-helper">证据要求：{task.evidence_requirements.join("、")||"未知"}</p>
            </div>):<p className="boss-helper">当前联系人未检索到已获准的交办与历史承诺。</p>}
          {selected?.compiled.feedback.map(f=><div className="boss-workspace-item"
            key={f.feedback_id}>
            <strong>{f.kind} · {f.feedback_id}</strong>
            <small>关联 {f.task_id}；模拟反馈不代表老板已确认完成</small>
          </div>)}
          {selected?.compiled.questions.map(q=><div className="boss-workspace-item"
            key={q.task_id}>
            <strong>待回答：{q.task_id}</strong>
            <p className="boss-helper">{q.text}</p>
          </div>)}
          {selected&&!selected.compiled.questions.length&&<p className="boss-helper">
            当前任务不存在未关闭事项。是否有新问题须由本人核查，系统不推断。
          </p>}
        </Panel>
        <Panel title="会议关联" note="准备 ≠ 加入会议议题 ≠ 外部邀请">
          <Fact label="拟关联会议">{selected?.compiled.meeting.meeting_id||"尚未指定"}</Fact>
          <Fact label="是否现有参会人">{selected?.compiled.meeting.contact_is_participant?
            "是":"未确认或未列入当前参会人"}</Fact>
          <Fact label="当前议题关联">{selected?.linked_meeting_version?
            "已关联会议版本 "+selected.linked_meeting_version:"未关联"}</Fact>
          <div className="boss-actions">
            <button type="button" className="boss-btn boss-btn-primary"
              disabled={!selected||!selected.live_evidence_current||
                !selected.compiled.meeting.meeting_id||Boolean(selected.linked_meeting_version)}
              onClick={attach}><ShieldCheck size={15}/> 本人确认加入会议议题</button>
            <button type="button" className="boss-btn" onClick={()=>onNavigate("F04")}>
              <Users size={15}/> 查看 F04 会前准备
            </button>
            <button type="button" className="boss-btn" onClick={()=>onNavigate("F06")}>
              核查相关交办
            </button>
          </div>
          {selected?.linked_meeting_version&&<div className="boss-actions">
            <label>解除关联原因<input value={unlinkReason}
              onChange={e=>setUnlinkReason(e.target.value)} maxLength={400}
              placeholder="明确说明本次取消的业务理由"/></label>
            <button type="button" className="boss-btn" onClick={detach} disabled={busy}>
              <XCircle size={15}/> 解除模拟议题关联
            </button>
          </div>}
        </Panel>
      </div>
      <div className="boss-column">
        <Panel title="可追溯原文与观点" note="作者、稳定 ID、版本及发布日期">
          {(selected?.compiled.sources||[]).map(source=><div
            className="boss-workspace-item" key={source.source_id}>
            <strong>{source.source_id} · v{source.version}</strong>
            <small>作者 ID：{source.author_contact_id||"未知"}；
              发布 {source.published_at||"未提供"}</small>
            {source.excerpt?<p className="boss-helper">{source.excerpt}</p>:
              <p className="boss-helper">原文已失效或无权读取，请重新核查来源。</p>}
            <div className="boss-actions">
              <button type="button" className="boss-btn"
                onClick={()=>onViewSource(source.source_id)}
                disabled={!selected?.live_evidence_current}>
                <FileSearch size={15}/> 打开有效原文
              </button>
            </div>
          </div>)}
          {!selected?.compiled.sources.length&&<p className="boss-helper">
            尚未指定可查的原文材料；系统不会凭联系人姓名生成个人特征或未经证实的观点。
          </p>}
          <Fact label="资料清单版本">{selected?.version||"无"}</Fact>
          <Fact label="当前业务时钟">{data?.business_clock||"待查询"}</Fact>
        </Panel>
        <Panel title="操作边界与结果" note="同一份获准材料的角色与版本校验">
          <p className="boss-helper">这里只对老板开放。联系人没有 Boss-Agent 账号；
            已登记的会议议题不增加参会者、不自动发布交办，也不生成实际日历邀请。</p>
          {(data?.briefs||[]).map(b=><button type="button" className="boss-task-row"
            key={b.brief_id} onClick={()=>useBrief(b.brief_id)}>
            <strong>{b.compiled.contact.name} · {b.state}</strong>
            <small>{b.brief_id} · v{b.version} · {b.live_evidence_current?"来源当前有效":"NEEDS_REVIEW"}</small>
          </button>)}
        </Panel>
      </div>
    </div>
    {pending&&<div className="boss-confirm-backdrop">
      <section ref={modalRef} tabIndex={-1} className="boss-confirm" role="dialog"
        aria-modal="true" aria-labelledby="boss-people-confirm-title">
        <h3 id="boss-people-confirm-title"><ShieldCheck size={18}/>{pending.title}</h3>
        <dl>{pending.description.map((line,i)=><div key={i}><dd>{line}</dd></div>)}</dl>
        <label className="boss-confirm-check"><input type="checkbox"
          checked={approved} disabled={busy} onChange={e=>setApproved(e.target.checked)}/>
          <span>我已核对稳定联系人、资料版本、关联会议和动作边界，授权执行。</span>
        </label>
        {error&&<p className="boss-validation-error" role="alert">{error}</p>}
        <footer className="boss-actions">
          <button className="boss-btn" type="button" disabled={busy||checking}
            onClick={()=>{setPending(null);setApproved(false);}}>取消</button>
          <button className="boss-btn" type="button" disabled={busy||checking}
            onClick={()=>void reconcile()}>
            {checking&&<Loader2 size={14} className="boss-spin"/>} 查询原请求回执
          </button>
          <button className="boss-btn boss-btn-primary" type="button"
            disabled={!approved||busy||checking} onClick={()=>void submit()}>
            {busy&&<Loader2 size={14} className="boss-spin"/>} 确认执行
          </button>
        </footer>
      </section>
    </div>}
  </>;
}
