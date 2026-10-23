import { useEffect, useRef, useState, type ReactNode } from "react";
import { AlertCircle, CalendarClock, CheckCircle2, Clock3,
  FileSearch, Loader2, RefreshCw, ShieldCheck, XCircle } from "lucide-react";
import { useClient } from "@/providers/ClientProvider";

type Contact = {
  contact_id:string;name:string;organization:string;responsibility:string;
  valid_from:string;valid_until:string;
};
type Details = {
  origin:string;destination:string;starts_at:string;ends_at:string;timezone:string;
  host_contact_id:string;buffer_minutes:number;
  transport_refs:{source_id:string;version:string}[];
};
type Impact = {
  meeting:{meeting_id:string;version:string;starts_at:string;
    end_known:boolean;requires_review:boolean;start_overlap:boolean};
  private_calendar:{version:string;status:string;conflict:boolean;private_body_exposed:boolean};
  task_deadlines:{task_id:string;version:string;due_at:string;status:string}[];
  other_confirmed_trips:{travel_id:string;version:string}[];
  transport_missing:boolean;weather_source_present:boolean;
  conflicts_need_acknowledgement:boolean;coverage:string;
};
type Travel = {
  travel_id:string;version:string;status:string;
  current:Details|null;pending:{details:Details;impact:Impact;
    review_sha256:string;reviewed_at:string}|null;
  pending_is_current?:boolean;
  impact_at_confirmation?:Impact;updated_at:string;
};
type Projection = {
  projection:"travel";source_type:"SIMULATED";business_clock:string;
  owner_timezone:string;plans:Travel[];contacts:Contact[];
  meeting:{meeting_id:string;version:string;starts_at:string;end_known:boolean};
  real_transport_bookings:boolean;real_weather_retrieval:boolean;
};
type Result = {
  travel_id:string;version:string;status:string;review_sha256?:string;
  external_booking_created?:false;external_cancellation_performed?:false;
};
type Pending = {action:string;payload:Record<string,unknown>;
  requestId:string;title:string;detail:string[]};
type Props = {onNavigate:(page:string)=>void;onViewSource:(id:string)=>void};

function Panel({title,caption,children}:{
  title:string;caption?:string;children:ReactNode;
}) {
  return <section className="boss-panel">
    <div className="boss-panel-head"><h2>{title}</h2>{caption&&<small>{caption}</small>}</div>
    {children}
  </section>;
}
function Item({label,children}:{label:string;children:ReactNode}) {
  return <div className="boss-kv"><span>{label}</span><strong>{children}</strong></div>;
}
function zoneTime(instant:string) {
  const match=instant.match(/^(.{16}):\d{2}([+-]\d{2}:\d{2})$/);
  return {local:match?.[1]||instant.slice(0,16),offset:match?.[2]||"+08:00"};
}
function checkedInstant(local:string,offset:string) {
  if(!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(local))
    throw new Error("请填写完整的本地日期与时间");
  if(!/^[+-](?:0\d|1\d|2[0-3]):[0-5]\d$/.test(offset))
    throw new Error("请填写明确的 UTC 偏移，例如 +08:00 或 -07:00");
  return local+":00"+offset;
}

export function BossTravelView({onNavigate,onViewSource}:Props) {
  const {client,getToken}=useClient();
  const [data,setData]=useState<Projection|null>(null);
  const [loading,setLoading]=useState(false);
  const [revision,setRevision]=useState(0);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [selectedId,setSelectedId]=useState("");
  const [origin,setOrigin]=useState("");
  const [destination,setDestination]=useState("");
  const [timezone,setTimezone]=useState("Asia/Shanghai");
  const [startLocal,setStartLocal]=useState("");
  const [endLocal,setEndLocal]=useState("");
  const [startOffset,setStartOffset]=useState("+08:00");
  const [endOffset,setEndOffset]=useState("+08:00");
  const [hostId,setHostId]=useState("");
  const [buffer,setBuffer]=useState(60);
  const [sourceId,setSourceId]=useState("");
  const [sourceVersion,setSourceVersion]=useState("");
  const [cancelReason,setCancelReason]=useState("");
  const [ackConflict,setAckConflict]=useState(false);
  const [ackTransport,setAckTransport]=useState(false);
  const [pending,setPending]=useState<Pending|null>(null);
  const [approved,setApproved]=useState(false);
  const [busy,setBusy]=useState(false);
  const [checking,setChecking]=useState(false);
  const modalRef=useRef<HTMLElement|null>(null);
  const selected=data?.plans.find(p=>p.travel_id===selectedId);
  const reviewed=selected?.pending;
  const impact=reviewed?.impact||selected?.impact_at_confirmation;
  const reload=()=>setRevision(x=>x+1);

  useEffect(()=>{
    const controller=new AbortController();
    const token=getToken();
    if(!token){setError("老板身份已失效，请重新登录");return;}
    setLoading(true);
    void fetch("/api/boss/ui/workspace/travel",{
      headers:{Authorization:"Bearer "+token},cache:"no-store",
      signal:controller.signal,
    }).then(async res=>{
      if(!res.ok)throw new Error("行程读取失败（HTTP "+res.status+"）");
      const result=await res.json() as Projection;
      if(result.projection!=="travel"||result.source_type!=="SIMULATED")
        throw new Error("返回的资料超出本次获准业务范围");
      return result;
    }).then(result=>{
      if(controller.signal.aborted)return;
      setData(result);setLoading(false);
      if(!selectedId&&result.plans.length===0)setTimezone(result.owner_timezone);
    }).catch(e=>{
      if(controller.signal.aborted)return;
      setError(e instanceof Error?e.message:String(e));
      setLoading(false);
    });
    return ()=>controller.abort();
  },[revision,getToken]);

  useEffect(()=>{
    if(!pending)return;
    const before=document.activeElement instanceof HTMLElement?document.activeElement:null;
    modalRef.current?.focus();
    const onKey=(event:KeyboardEvent)=>{
      if(event.key==="Escape"&&!busy&&!checking){
        setPending(null);setApproved(false);return;
      }
      if(event.key!=="Tab"||!modalRef.current)return;
      const elements=Array.from(modalRef.current.querySelectorAll<HTMLElement>(
        "input:not([disabled]),button:not([disabled])"
      )).filter(el=>el.getClientRects().length>0);
      if(!elements.length)return;
      if(event.shiftKey&&document.activeElement===elements[0]){
        event.preventDefault();elements[elements.length-1].focus();
      }else if(!event.shiftKey&&document.activeElement===elements[elements.length-1]){
        event.preventDefault();elements[0].focus();
      }
    };
    document.addEventListener("keydown",onKey);
    return ()=>{document.removeEventListener("keydown",onKey);before?.focus();};
  },[pending?.requestId,busy,checking]);

  function loadTravel(id:string) {
    setSelectedId(id);setError("");setNotice("");setAckConflict(false);setAckTransport(false);
    const record=data?.plans.find(x=>x.travel_id===id);
    const details=record?.pending?.details||record?.current;
    if(!details)return;
    setOrigin(details.origin);setDestination(details.destination);
    setTimezone(details.timezone);setHostId(details.host_contact_id);
    setBuffer(details.buffer_minutes);
    setStartLocal(zoneTime(details.starts_at).local);
    setStartOffset(zoneTime(details.starts_at).offset);
    setEndLocal(zoneTime(details.ends_at).local);
    setEndOffset(zoneTime(details.ends_at).offset);
    setSourceId(details.transport_refs[0]?.source_id||"");
    setSourceVersion(details.transport_refs[0]?.version||"");
  }
  function resetForm() {
    setSelectedId("");setOrigin("");setDestination("");
    setStartLocal("");setEndLocal("");setHostId("");setBuffer(60);
    setTimezone(data?.owner_timezone||"Asia/Shanghai");
    setSourceId("");setSourceVersion("");
    setCancelReason("");setAckConflict(false);setAckTransport(false);
    setError("");setNotice("");
  }
  function propose(action:string,payload:Record<string,unknown>,title:string,detail:string[]){
    setPending({action,payload,requestId:"boss-"+crypto.randomUUID(),title,detail});
    setApproved(false);setError("");setNotice("");
  }
  function review() {
    try{
      if(!origin.trim()||!destination.trim()||!hostId)
        throw new Error("起点、目的地及接待联系人必须填写");
      if(sourceId.trim()&&!sourceVersion.trim()||!sourceId.trim()&&sourceVersion.trim())
        throw new Error("交通来源与版本必须同时填写");
      const starts_at=checkedInstant(startLocal,startOffset);
      const ends_at=checkedInstant(endLocal,endOffset);
      propose("boss.travel.review",{
        travel_id:selectedId||null,expected_version:selected?.version||"0",
        origin:origin.trim(),destination:destination.trim(),
        starts_at,ends_at,timezone:timezone.trim(),
        host_contact_id:hostId,buffer_minutes:buffer,
        transport_refs:sourceId.trim()?[{
          source_id:sourceId.trim(),version:sourceVersion.trim(),
        }]:[],
      },"保存并核查行程草稿",[
        origin+" → "+destination,
        starts_at+" — "+ends_at+" / "+timezone,
        "接待人："+hostId+"，缓冲："+buffer+"分钟",
        "本次不订票，不修改外部会议/日历。核查后仍需本人单独确认。",
      ]);
    }catch(e){setError(e instanceof Error?e.message:String(e));}
  }
  function confirm() {
    if(!selected||!reviewed||!selected.pending_is_current){
      setError("待确认方案已失效，请重新核查当前业务对象");return;
    }
    if(impact?.conflicts_need_acknowledgement&&!ackConflict){
      setError("必须先明确知晓会议、任务或私人时间冲突");return;
    }
    if(impact?.transport_missing&&!ackTransport){
      setError("必须先确认当前没有可验证的交通/预订依据");return;
    }
    propose("boss.travel.confirm",{
      travel_id:selected.travel_id,expected_version:selected.version,
      review_sha256:reviewed.review_sha256,
      acknowledge_conflicts:ackConflict,acknowledge_missing_transport:ackTransport,
    },"本人确认模拟行程",[
      "行程 ID："+selected.travel_id+"，待核查版本："+selected.version,
      reviewed.details.starts_at+" — "+reviewed.details.ends_at,
      "已知会议/任务冲突："+(impact?.conflicts_need_acknowledgement?"存在":"未识别"),
      "交通资料："+(impact?.transport_missing?"没有获准依据":"已固定版本"),
      "只写入本人 SQLite 行程；没有实际预订、订票或外部改期。",
    ]);
  }
  function cancel() {
    if(!selected||!cancelReason.trim()){setError("请选择行程并填写取消原因");return;}
    propose("boss.travel.cancel",{
      travel_id:selected.travel_id,expected_version:selected.version,
      reason:cancelReason.trim(),
    },"取消模拟行程",[
      "行程 ID："+selected.travel_id+"，当前版本："+selected.version,
      "原因："+cancelReason.trim(),
      "仅取消应用内模拟计划；不会取消实际预订。",
    ]);
  }
  function applied(result:Result){
    if(result.travel_id)setSelectedId(result.travel_id);
    setNotice("SQLite 事务已记录："+result.status+"（版本 "+result.version+
      "）。此结果不代表外部订票、通知或实际日历变更。");
    setAckConflict(false);setAckTransport(false);
    setPending(null);setApproved(false);reload();
  }
  async function submit(){
    if(!pending||!approved||busy||checking)return;
    setBusy(true);setError("");
    try{
      const result=await client.requestMutation<Result>(pending.action,{
        ...pending.payload,client_request_id:pending.requestId,
      });
      applied(result);
    }catch(e){
      setError((e instanceof Error?e.message:String(e))+
        "。当前可能已有已写入回执，请先按同一编号查询，勿更换请求编号重试。");
    }finally{setBusy(false);}
  }
  async function reconcile(){
    if(!pending||busy||checking)return;
    const token=getToken();
    if(!token){setError("身份失效，不能核对本次回执");return;}
    setChecking(true);setError("");
    try{
      const params=new URLSearchParams({
        action:pending.action,client_request_id:pending.requestId,
      });
      const response=await fetch("/api/boss/ui/operation-status?"+params,{
        headers:{Authorization:"Bearer "+token},cache:"no-store",
      });
      if(!response.ok)throw new Error("回执查询失败，HTTP "+response.status);
      const data=await response.json() as {
        action:string;client_request_id:string;outcome:string;result?:Result;
      };
      if(data.action!==pending.action||data.client_request_id!==pending.requestId)
        throw new Error("回执动作及请求标识不一致");
      if(data.outcome==="RECORDED"&&data.result)applied(data.result);
      else if(data.outcome==="NOT_FOUND_IN_CURRENT_STORE"){
        setError("当前库未找到原请求回执，不代表未执行；可按同一请求编号重试或重新读取业务对象。");
        reload();
      }else throw new Error("未识别回执状态，拒绝重复提交");
    }catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setChecking(false);}
  }

  return <>
    <div className="boss-workspace-toolbar">
      <span className="boss-workspace-note">
        <span className="boss-tag boss-tag-amber">SIMULATED · BOSS ONLY</span>
        F11 · 行程安排 · 核查 / 本人确认 / 取消
      </span>
      <button className="boss-btn" onClick={reload} disabled={loading}>
        {loading?<Loader2 size={15} className="boss-spin"/>:<RefreshCw size={15}/>} 重读行程
      </button>
    </div>
    {error&&<div className="boss-status boss-status-error" role="alert">
      <AlertCircle size={16}/>{error}
    </div>}
    {notice&&<div className="boss-status boss-status-ok" role="status">
      <CheckCircle2 size={16}/>{notice}
    </div>}
    {loading&&<div className="boss-status"><Loader2 size={16} className="boss-spin"/>正在检查行程版本…</div>}
    <div className="boss-columns">
      <div className="boss-column">
        <Panel title="行程草稿与时间范围" caption="采用原 Desktop v6 的筛选与工作卡片结构">
          <div className="boss-form-grid">
            <label>当前行程<select value={selectedId} onChange={e=>e.target.value?loadTravel(e.target.value):resetForm()}>
              <option value="">新建行程</option>
              {(data?.plans||[]).map(p=><option key={p.travel_id} value={p.travel_id}>
                {p.travel_id.slice(0,18)} · {p.status} · v{p.version}
              </option>)}
            </select></label>
            <label>起点<input value={origin} onChange={e=>setOrigin(e.target.value)}
              placeholder="填写确切起点" maxLength={240}/></label>
            <label>目的地<input value={destination} onChange={e=>setDestination(e.target.value)}
              placeholder="填写确切目的地" maxLength={240}/></label>
            <label>IANA 时区<input value={timezone} onChange={e=>setTimezone(e.target.value)}
              placeholder="Asia/Shanghai" maxLength={80}/></label>
            <label>开始本地时间<input type="datetime-local" value={startLocal}
              onChange={e=>setStartLocal(e.target.value)}/></label>
            <label>开始 UTC 偏移<input value={startOffset} onChange={e=>setStartOffset(e.target.value)}
              placeholder="+08:00" maxLength={6}/></label>
            <label>结束本地时间<input type="datetime-local" value={endLocal}
              onChange={e=>setEndLocal(e.target.value)}/></label>
            <label>结束 UTC 偏移<input value={endOffset} onChange={e=>setEndOffset(e.target.value)}
              placeholder="+08:00" maxLength={6}/></label>
            <label>接待联系人（稳定 ID）<select value={hostId} onChange={e=>setHostId(e.target.value)}>
              <option value="">请选择获准联系人</option>
              {(data?.contacts||[]).map(c=><option key={c.contact_id} value={c.contact_id}>
                {c.name} · {c.organization} / {c.contact_id}
              </option>)}
            </select></label>
            <label>预留缓冲（分钟）<select value={buffer} onChange={e=>setBuffer(Number(e.target.value))}>
              {[0,30,60,120,240,360].map(n=><option key={n} value={n}>{n} 分钟</option>)}
            </select></label>
            <label>交通/预订依据 ID（可空）<input value={sourceId}
              onChange={e=>setSourceId(e.target.value)} maxLength={128}
              placeholder="尚无可信来源时留空"/></label>
            <label>依据当前版本<input value={sourceVersion}
              onChange={e=>setSourceVersion(e.target.value)} maxLength={30}
              placeholder="与来源 ID 一起填写"/></label>
          </div>
          <p className="boss-helper">本地时间和 UTC 偏移必须同时与 IANA 时区吻合；
            系统拒绝不存在的夏令时时刻。日期参考模拟业务时钟，不会推定实际交通时长。</p>
          <Item label="模拟业务时钟">{data?.business_clock||"待读取"}</Item>
          <div className="boss-actions">
            <button type="button" className="boss-btn boss-btn-primary"
              disabled={loading||busy||selected?.status==="CANCELED"} onClick={review}>
              <CalendarClock size={15}/> 保存草稿并检查冲突
            </button>
            <button type="button" className="boss-btn" onClick={resetForm}>另建行程</button>
          </div>
        </Panel>
        <Panel title="已保存行程" caption="同一 SQLite 行程版本；不显示虚构预订">
          {(data?.plans||[]).length?
            data?.plans.map(p=><button type="button" className="boss-task-row"
              key={p.travel_id} onClick={()=>loadTravel(p.travel_id)}>
              <strong>{p.current?.origin||p.pending?.details.origin||"待核查"}
                {" → "}{p.current?.destination||p.pending?.details.destination||"待核查"}</strong>
              <small>{p.travel_id} · {p.status} · 版本 {p.version}
                {p.pending?" · 有待本人确认的核查稿":""}</small>
            </button>):<p className="boss-helper">暂无已保存行程；第一次核查会生成持久化草稿。</p>}
        </Panel>
      </div>
      <div className="boss-column">
        <Panel title="冲突与准备事项" caption="固定当前会议、私人日历及任务版本">
          <Item label="行程状态">{selected?.status||"尚未保存"}</Item>
          <Item label="核查有效性">{reviewed?
            selected?.pending_is_current?"当前有效":"来源已变化，需重新核查":"无待确认稿"}</Item>
          <Item label="固定会议">{data?.meeting.meeting_id||"未载入"}</Item>
          <Item label="会议时间">{data?.meeting.starts_at||"未知"}（结束时刻未知）</Item>
          <Item label="会议影响">{impact?.meeting.requires_review?"需要复核":"未发现已知开始时刻冲突"}</Item>
          <Item label="私人时间冲突">{impact?.private_calendar.conflict?"检测到重叠":"未发现重叠"}</Item>
          <Item label="受影响期限">{impact?.task_deadlines.length??0} 项</Item>
          <Item label="其他已确认行程冲突">{impact?.other_confirmed_trips.length??0} 项</Item>
          <Item label="交通/预订凭据">{impact?.transport_missing?"缺失，不能证明已订":"来源版本已固定"}</Item>
          {(impact?.task_deadlines||[]).map(row=><div className="boss-workspace-item" key={row.task_id}>
            <strong>{row.task_id}</strong><small>任务 v{row.version} · {row.status} · 期限 {row.due_at}</small>
          </div>)}
          {(impact?.other_confirmed_trips||[]).map(row=><div className="boss-workspace-item" key={row.travel_id}>
            <strong>其他行程：{row.travel_id}</strong><small>当前 v{row.version}</small>
          </div>)}
          {!impact&&<p className="boss-helper">保存核查稿之后才显示基于实际业务对象的冲突结论。</p>}
          {reviewed&&<div className="boss-actions">
            <label className="boss-confirm-check"><input type="checkbox" checked={ackConflict}
              onChange={e=>setAckConflict(e.target.checked)}/>
              <span>已核实会议、任务、私人时间及未知会议结束时刻的影响</span></label>
            <label className="boss-confirm-check"><input type="checkbox" checked={ackTransport}
              onChange={e=>setAckTransport(e.target.checked)}/>
              <span>已知缺少交通预订或天气依据，不将模拟计划视为真实订票</span></label>
            <button type="button" className="boss-btn boss-btn-primary"
              disabled={busy||!selected?.pending_is_current}
              onClick={confirm}><ShieldCheck size={15}/> 本人确认当前版本行程</button>
          </div>}
          {selected&&selected.status!=="CANCELED"&&<div className="boss-actions">
            <label>取消原因<input value={cancelReason} onChange={e=>setCancelReason(e.target.value)}
              placeholder="说明取消原因" maxLength={400}/></label>
            <button type="button" className="boss-btn" disabled={busy}
              onClick={cancel}><XCircle size={15}/> 取消该模拟行程</button>
          </div>}
        </Panel>
        <Panel title="关联任务和资料" caption="F11 → F04 / F12 / N05">
          <div className="boss-actions">
            <button type="button" className="boss-btn" onClick={()=>onNavigate("F04")}>
              <FileSearch size={15}/> 查看会前材料复核状态
            </button>
            <button type="button" className="boss-btn" onClick={()=>onNavigate("F12")}>
              <Clock3 size={15}/> 核对本人私人日程
            </button>
            <button type="button" className="boss-btn" onClick={()=>onNavigate("N05")}>检查任务期限</button>
            {sourceId&&<button type="button" className="boss-btn"
              onClick={()=>onViewSource(sourceId)}>打开交通依据原文</button>}
          </div>
          <p className="boss-helper">行程确认只写入模拟计划，不会自动更改会议、发布交办、
            发送外部消息、预订交通或声称天气查询已完成。</p>
        </Panel>
      </div>
    </div>
    {pending&&<div className="boss-confirm-backdrop">
      <section ref={modalRef} role="dialog" aria-modal="true" tabIndex={-1}
        className="boss-confirm" aria-labelledby="boss-travel-confirm-title">
        <h3 id="boss-travel-confirm-title"><ShieldCheck size={18}/>{pending.title}</h3>
        <p>当前老板身份需单独核实此次对象、时间、版本和范围。</p>
        <dl>{pending.detail.map((line,i)=><div key={i}><dd>{line}</dd></div>)}</dl>
        <label className="boss-confirm-check"><input type="checkbox"
          checked={approved} disabled={busy} onChange={e=>setApproved(e.target.checked)}/>
          <span>我已核对上述字段并同意执行本次模拟事务。</span>
        </label>
        {error&&<p className="boss-validation-error" role="alert">{error}</p>}
        <footer className="boss-actions">
          <button type="button" className="boss-btn" onClick={()=>{setPending(null);setApproved(false);}}
            disabled={busy||checking}>返回</button>
          <button type="button" className="boss-btn" disabled={busy||checking}
            onClick={()=>void reconcile()}>{checking&&<Loader2 size={14} className="boss-spin"/> 查询原请求回执</button>
          <button type="button" className="boss-btn boss-btn-primary"
            disabled={busy||checking||!approved} onClick={()=>void submit()}>
            {busy&&<Loader2 size={14} className="boss-spin"/> 确认并写入
          </button>
        </footer>
      </section>
    </div>}
  </>;
}
