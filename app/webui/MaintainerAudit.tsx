import {useEffect,useRef,useState} from "react";
import {Loader2,RefreshCw} from "lucide-react";
import {V7Empty,V7Fact,V7Panel,V7Pagination,V7ReadState} from "./BossV7UI";
import {useTechnicalWorkspace} from "./useTechnicalWorkspace";

type AuditRow={id:string;action:string;target_id:string;target_version:string|null;request_id:string|null;run_id:string|null;role:string;state:string;authorization_id:string|null;
  authorization_state:string;scope:string[];valid_until:string|null;revoked_at:string|null;executed_at:string|null;created_at:string;reason:string|null;
  result_refs:{type:string;id:string;version:string|null;state:string}[]};
type Projection={projection:"audit";private_body_available_here:false;records:AuditRow[];namespace:string;read_at:string};
export type {AuditRow,Projection as AuditProjection};
type Filters={query:string;type:string;state:string;date:string;action:string;authorization:string;abnormal:boolean};
type SavedView={filters:Filters;selected:string;page:number};
type AuditType="BUSINESS"|"TECHNICAL"|"READ"|"SYSTEM";
const localDate=new Intl.DateTimeFormat("en-CA",{timeZone:"Asia/Shanghai",year:"numeric",month:"2-digit",day:"2-digit"});
const TYPE_LABEL:Record<AuditType,string>={BUSINESS:"本人业务动作",TECHNICAL:"技术维护操作",READ:"只读请求",SYSTEM:"系统事件"};
const ROLE_LABEL:Record<string,string>={BOSS:"老板本人",MAINTAINER:"技术管理员",NOT_RECORDED:"系统事件，没有请求身份"};
const READ_ACTIONS=new Set(["boss.bi.query","boss.morning.query","boss.mvp.query","boss.simulation.alert.load",
  "boss.simulation.bi_scenario.load","boss.simulation.morning_coverage.load","boss.conversation.read",
  "boss.conversation.task.read","boss.conversation.business.read"]);
const RESOURCES:Record<string,string>={"assignment":"交办","assignment.extension":"交办延期","assignment.sources":"交办依据",
  "commitment":"承诺","memory":"本人记忆","reminder":"提醒","meeting":"会议","research":"调研","minutes":"会议纪要",
  "minutes.assignment":"纪要交办","knowledge.source":"资料","prompt":"Prompt","approval":"审批","message":"消息",
  "calendar":"日程","travel":"行程","people":"人员","owner.goals":"本人目标","owner.notice":"本人通知","owner.plan":"本人计划",
  "owner_workspace.personal-memory":"本人记忆","owner_workspace.authorizations":"本人授权","owner_workspace.runs":"运行取消",
  "authorization":"授权","today":"今日安排","sector":"经营板块","runtime":"模型运行配置","scheduler":"调度计划",
  "scheduler.draft":"调度草稿","scheduler.restart":"调度组件重启","simulation":"模拟环境","simulation.clock":"模拟业务时钟","simulation.event":"模拟事件",
  "simulation.application":"模拟应用资料","simulation.message":"模拟消息回复","simulation.feedback":"模拟回复",
  "simulation.bi_scenario":"经营资料场景","simulation.alert":"经营提醒输入","simulation.alert.rule":"经营提醒规则",
  "simulation.morning_coverage":"晨间覆盖输入","sop":"SOP方法","technical.datasets":"模拟数据集",
  "technical.models":"模型连接配置","alert":"经营提醒","alert.rule":"经营提醒规则",
  "alert.meeting":"提醒关联会议","alert.assignment":"提醒转交办","bi":"经营查询",
  "morning":"晨间视图","mvp":"MVP视图","conversation":"会话记录"};
const VERBS:Record<string,string>={"save":"保存","create":"新建","confirm":"确认","send":"发送","prepare":"准备",
  "nudge":"催办","complete":"完成","extend":"延期","decide":"决定","cancel":"取消","withdraw":"撤回","revise":"修改",
  "activate":"启用","deactivate":"停用","validate":"验证","pause":"暂停","resume":"恢复","ack":"知悉","snooze":"延后",
  "close":"关闭","attach":"关联","detach":"解除关联","release":"发布","revoke":"撤销","reorder":"排序",
  "coordinate":"协调","schedule":"安排","link":"关联","delete":"删除","generate":"生成","inspect-reset":"重置",
  "inspect":"检查","reset":"重置","advance":"推进","seed":"建立","reply":"回复","load":"读取","query":"查询",
  "read":"读取","manual_run":"立即触发","held":"已举行","reconcile":"核对"};

function auditType(row:AuditRow):AuditType{
  if(READ_ACTIONS.has(row.action))return "READ";
  if(row.role==="NOT_RECORDED")return "SYSTEM";
  if(row.role==="MAINTAINER")return "TECHNICAL";
  return "BUSINESS";
}
function purpose(action:string):{label:string;registered:boolean}{
  const segments=action.replace(/^boss\./,"").split(".");
  for(let size=segments.length-1;size>0;size--){
    const resource=RESOURCES[segments.slice(0,size).join(".")];
    const verb=VERBS[segments.at(-1)??""];
    if(resource&&verb)return {label:resource+" · "+verb,registered:true};
  }
  return {label:action,registered:false};
}
function authorizationView(row:AuditRow):{state:string;abnormal:boolean;reason:string}{
  const type=auditType(row),executed=row.executed_at?new Date(row.executed_at):null;
  const revokedBeforeExecution=!!row.revoked_at&&!!executed&&new Date(row.revoked_at)<=executed;
  const expiredAtExecution=!!row.valid_until&&!!executed&&new Date(row.valid_until)<executed;
  if(row.authorization_id){
    if(revokedBeforeExecution)return {state:"已撤销",abnormal:type==="BUSINESS",reason:"执行时本人授权已经撤销"};
    if(expiredAtExecution)return {state:"已过期",abnormal:type==="BUSINESS",reason:"执行时已经超过授权有效期"};
    if(row.revoked_at)return {state:"执行时有效，现已撤销",abnormal:false,reason:"撤销发生在执行之后"};
    return {state:"有效授权",abnormal:false,reason:""};
  }
  if(type==="BUSINESS")return {state:"缺少必要授权",abnormal:true,reason:"业务动作没有关联本人授权"};
  return {state:"授权不适用",abnormal:false,reason:"此类型操作不要求老板本人授权"};
}
function authorizationKey(row:AuditRow):"RECORDED"|"REVOKED"|"NOT_REQUIRED"|"MISSING"{
  if(row.authorization_state==="RECORDED")return "RECORDED";
  if(row.authorization_state==="REVOKED")return "REVOKED";
  return auditType(row)==="BUSINESS"?"MISSING":"NOT_REQUIRED";
}

export function MaintainerAudit({onOpenRun}:{onNavigate:(page:string)=>void;onOpenRun:(id:string)=>void}){
  const api=useTechnicalWorkspace<Projection>("audit");
  const saved=useRef<SavedView|undefined>(window.history.state?.bossMaintainerRecords?.A14);
  const [query,setQuery]=useState(saved.current?.filters.query??"");
  const [state,setState]=useState(saved.current?.filters.state??"");
  const [action,setAction]=useState(saved.current?.filters.action??""),[authorization,setAuthorization]=useState(saved.current?.filters.authorization??"");
  const [date,setDate]=useState(saved.current?.filters.date??"");
  const [type,setType]=useState(saved.current?.filters.type??"");
  const [abnormal,setAbnormal]=useState(saved.current?.filters.abnormal??false);
  const [filter,setFilter]=useState<Filters>({query:"",type:"",state:"",date:"",action:"",authorization:"",abnormal:false,...saved.current?.filters});
  const [page,setPage]=useState(saved.current?.page??1);
  const [selected,setSelected]=useState(saved.current?.selected??"");
  const execution=useRef<HTMLDivElement>(null);
  const states=[...new Set((api.data?.records??[]).map(row=>row.state))];
  const actions=[...new Set((api.data?.records??[]).map(row=>row.action))];
  const records=(api.data?.records??[]).filter(row=>(!filter.query||[row.target_id,row.request_id,row.run_id,row.authorization_id].some(value=>value?.toLowerCase().includes(filter.query.toLowerCase())))&&(!filter.state||row.state===filter.state)&&(!filter.action||row.action===filter.action)&&(!filter.authorization||authorizationKey(row)===filter.authorization)&&(!filter.type||auditType(row)===filter.type)&&(!filter.abnormal||authorizationView(row).abnormal)&&(!filter.date||!!row.executed_at&&localDate.format(new Date(row.executed_at))===filter.date));
  const currentPage=Math.min(page,Math.max(1,Math.ceil(records.length/10)));
  useEffect(()=>{if(!api.data)return;const state=window.history.state??{};window.history.replaceState({...state,bossMaintainerRecords:{...state.bossMaintainerRecords,A14:{filters:filter,selected,page:currentPage}}},"",window.location.href);},[api.data,filter,selected,currentPage]);
  const record=api.data?.records.find(row=>row.id===selected);
  const view=record?authorizationView(record):null;
  function focusExecution(){execution.current?.scrollIntoView({block:"start",behavior:"smooth"});execution.current?.focus();}
  function switchRecord(id:string){setSelected(id);}
  return <div className="boss-maintainer-records"><V7ReadState loading={api.loading} error={api.error} onReload={api.reload}/>
    <form className="boss-v7-filter-bar boss-maintainer-filters" onSubmit={event=>{event.preventDefault();setFilter({query,type,state,date,action,authorization,abnormal});setPage(1);}}>
      <label>关联任务<input type="search" value={query} onChange={event=>setQuery(event.target.value)} placeholder="对象、请求、运行或授权编号"/></label>
      <label>动作类型<select value={type} onChange={event=>setType(event.target.value)}><option value="">全部动作类型</option>{Object.entries(TYPE_LABEL).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>
      <label>授权状态<select value={authorization} onChange={event=>setAuthorization(event.target.value)}><option value="">全部授权状态</option><option value="RECORDED">有效授权</option><option value="REVOKED">已撤销</option><option value="NOT_REQUIRED">授权不适用</option><option value="MISSING">缺少必要授权</option></select></label>
      <label>执行日期（北京时间）<input type="date" value={date} onChange={event=>setDate(event.target.value)}/></label>
      <label>执行状态<select value={state} onChange={event=>setState(event.target.value)}><option value="">全部执行状态</option>{states.map(value=><option key={value}>{value}</option>)}</select></label>
      <label>具体动作<select value={action} onChange={event=>setAction(event.target.value)}><option value="">全部具体动作</option>{actions.map(value=><option key={value}>{value}</option>)}</select></label>
      <button className="boss-btn boss-btn-primary">查询记录</button>
      <button type="button" className="boss-btn" disabled={api.loading} aria-busy={api.loading} onClick={api.reload}>{api.loading?<Loader2 size={15} className="boss-spin"/>:<RefreshCw size={15}/>} {api.loading?"刷新中…":"刷新"}</button>
      <button type="button" className={abnormal?"boss-btn boss-btn-primary":"boss-btn"} aria-pressed={abnormal} onClick={()=>{const next=!abnormal;setAbnormal(next);setFilter(previous=>({...previous,abnormal:next}));setPage(1);}}>仅看授权异常</button>
    </form>
    <p className="boss-helper">动作类型按记录中的执行身份与操作名称区分；授权不适用与缺少必要授权分别标注。许可依据、对象版本与实际回执以原记录为准，页面不判定越权，也不提供批准、发送或确认完成操作。</p>
    <div className="boss-maintainer-columns"><div className="boss-column">
      <V7Panel title="只读记录与状态"><div className="boss-v7-table-scroll"><table className="boss-v7-table"><thead><tr><th>操作用途 · 时间</th><th>动作类型</th><th>对象版本</th><th>授权与执行状态</th></tr></thead><tbody>{records.slice((currentPage-1)*10,currentPage*10).map(row=>{const rowView=authorizationView(row),rowPurpose=purpose(row.action);return <tr key={row.id} aria-selected={row.id===selected}><td><button className="boss-v7-text-button" onClick={()=>switchRecord(row.id)}>{rowPurpose.label} · {row.executed_at??row.created_at}</button><small>{rowPurpose.registered?row.action:"用途名称未登记，主标题显示技术操作名称"}</small><small>{row.target_id||"没有对象编号"} · {row.request_id??"没有关联请求编号"}</small></td><td>{TYPE_LABEL[auditType(row)]}</td><td>{row.target_version??"未记录版本"}</td><td>{rowView.state}{rowView.abnormal&&<small>需要核查：{rowView.reason}</small>}<small>执行状态：{row.state}</small></td></tr>;})}</tbody></table></div>{!records.length&&<V7Empty title="当前条件下没有只读记录"/>}<V7Pagination page={currentPage} total={records.length} pageSize={10} onChange={setPage}/></V7Panel>
    </div><aside className="boss-column">
      {record?<>
        <V7Panel title="查看授权与请求元信息">
          <V7Fact label="操作用途">{purpose(record.action).label}</V7Fact>
          <V7Fact label="技术操作名称">{record.action}</V7Fact>
          <V7Fact label="动作类型">{TYPE_LABEL[auditType(record)]}</V7Fact>
          <V7Fact label="执行身份与主体">{ROLE_LABEL[record.role]??record.role}</V7Fact>
          <V7Fact label="权限依据">{view?.state}</V7Fact>
          <V7Fact label="依据说明">{view?.reason||"授权与业务动作类型匹配"}</V7Fact>
          <V7Fact label="记录编号">{record.id}</V7Fact>
          <V7Fact label="动作对象">{record.target_id||"未记录对象编号"}</V7Fact>
          <V7Fact label="对象版本">{record.target_version??"未记录版本"}</V7Fact>
          <V7Fact label="授权范围">{record.scope.join("、")||"未记录范围"}</V7Fact>
          <V7Fact label="有效期">{record.valid_until??"不适用或未记录"}</V7Fact>
          <V7Fact label="撤销时间">{record.revoked_at??"未记录撤销"}</V7Fact>
          <V7Fact label="授权引用">{record.authorization_id??"没有授权引用"}</V7Fact>
          <V7Fact label="原请求编号">{record.request_id??"没有关联请求编号"}</V7Fact>
          <V7Fact label="运行编号">{record.run_id??"没有关联运行编号"}</V7Fact>
          <V7Fact label="执行空间">{api.data?.namespace??"尚未读取"}</V7Fact>
          <V7Fact label="记录时间">{record.created_at}</V7Fact>
          <V7Fact label="读取时间">{api.data?.read_at??"尚未读取"}</V7Fact>
          <p className="boss-v7-note">仅显示当前技术身份获准的元信息。私人正文继续按来源权限控制，授权决定由老板本人操作。</p>
          <div className="boss-actions">
            <button className="boss-btn" onClick={focusExecution}>查看此请求的执行结果</button>
            {record.run_id&&<button className="boss-btn" onClick={()=>onOpenRun(record.run_id!)}>查看关联运行</button>}
          </div>
          {!record.run_id&&<p className="boss-helper">此记录没有关联运行编号，当前服务也不提供按请求编号查询运行记录。</p>}
        </V7Panel>
        <div ref={execution} tabIndex={-1}><V7Panel title="执行结果与原请求">
          <V7Fact label="当前正式状态">{record.state}</V7Fact>
          <V7Fact label="执行时间">{record.executed_at??"没有执行记录"}</V7Fact>
          <V7Fact label="实际执行对象">{record.result_refs.length?`${record.result_refs.length} 项引用`:"没有已执行对象引用"}</V7Fact>
          {record.result_refs.map(row=><article className="boss-workspace-item" key={row.type+row.id}><strong>{row.id} · {row.type}</strong><p>{row.state} · {row.version??"未记录版本"}</p>{row.type==="runtime_run"&&<button className="boss-btn" onClick={()=>onOpenRun(row.id)}>查看本次运行</button>}</article>)}
          <V7Fact label="拒绝原因">{record.reason??"没有已记录原因"}</V7Fact>
          <p className="boss-v7-note">只读核查该次原请求；授权依据与本页执行状态分别核对。审计投影没有模型调用结果字段，业务完成需要按关联对象核查；本页面不重新执行任何业务动作。</p>
        </V7Panel></div>
      </>:<>
        <V7Panel title="查看授权与请求元信息"><V7Empty title="请选择动作记录">从左侧列表选择一条记录，查看执行身份、权限依据、对象版本与实际回执。</V7Empty></V7Panel>
        <V7Panel title="执行结果与原请求"><V7Empty title="尚未选择记录">选择记录后可以核查原请求的执行结果与关联运行。</V7Empty></V7Panel>
      </>}
    </aside></div>
  </div>;
}
