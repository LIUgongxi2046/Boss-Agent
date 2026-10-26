import {useEffect,useRef,useState} from "react";
import {V7Empty,V7Fact,V7Panel,V7Pagination,V7ReadState} from "./BossV7UI";
import {useTechnicalWorkspace} from "./useTechnicalWorkspace";

type AuditRow={id:string;action:string;target_id:string;target_version:string|null;request_id:string|null;run_id:string|null;role:string;state:string;authorization_id:string|null;
  authorization_state:string;scope:string[];valid_until:string|null;revoked_at:string|null;executed_at:string|null;created_at:string;reason:string|null;
  result_refs:{type:string;id:string;version:string|null;state:string}[]};
type Projection={projection:"audit";private_body_available_here:false;records:AuditRow[];namespace:string;read_at:string};
export type {AuditRow,Projection as AuditProjection};
type Filters={query:string;state:string;date:string;action:string;authorization:string};
type SavedView={filters:Filters;selected:string;page:number};
const localDate=new Intl.DateTimeFormat("en-CA",{timeZone:"Asia/Shanghai",year:"numeric",month:"2-digit",day:"2-digit"});

export function MaintainerAudit({onNavigate,onOpenRun}:{onNavigate:(page:string)=>void;onOpenRun:(id:string)=>void}){
  const api=useTechnicalWorkspace<Projection>("audit");
  const saved=useRef<SavedView|undefined>(window.history.state?.bossMaintainerRecords?.A14);
  const [query,setQuery]=useState(saved.current?.filters.query??"");
  const [state,setState]=useState(saved.current?.filters.state??"");
  const [action,setAction]=useState(saved.current?.filters.action??""),[authorization,setAuthorization]=useState(saved.current?.filters.authorization??"");
  const [date,setDate]=useState(saved.current?.filters.date??"");
  const [filter,setFilter]=useState<Filters>(saved.current?.filters??{query:"",state:"",date:"",action:"",authorization:""});
  const [page,setPage]=useState(saved.current?.page??1);
  const [selected,setSelected]=useState(saved.current?.selected??"");
  const metadata=useRef<HTMLDivElement>(null),execution=useRef<HTMLDivElement>(null);
  const states=[...new Set((api.data?.records??[]).map(row=>row.state))];
  const actions=[...new Set((api.data?.records??[]).map(row=>row.action))],authorizations=[...new Set((api.data?.records??[]).map(row=>row.authorization_state))];
  const records=(api.data?.records??[]).filter(row=>(!filter.query||[row.target_id,row.request_id,row.run_id,row.authorization_id].some(value=>value?.toLowerCase().includes(filter.query.toLowerCase())))&&(!filter.state||row.state===filter.state)&&(!filter.action||row.action===filter.action)&&(!filter.authorization||row.authorization_state===filter.authorization)&&(!filter.date||!!row.executed_at&&localDate.format(new Date(row.executed_at))===filter.date));
  const currentPage=Math.min(page,Math.max(1,Math.ceil(records.length/10)));
  useEffect(()=>{if(!api.data)return;const state=window.history.state??{};window.history.replaceState({...state,bossMaintainerRecords:{...state.bossMaintainerRecords,A14:{filters:filter,selected,page:currentPage}}},"",window.location.href);},[api.data,filter,selected,currentPage]);
  const record=api.data?.records.find(row=>row.id===selected);
  function focus(region:"metadata"|"execution"){const target=region==="metadata"?metadata.current:execution.current;target?.scrollIntoView({block:"start",behavior:"smooth"});target?.focus();}
  return <div className="boss-maintainer-records"><V7ReadState loading={api.loading} error={api.error} onReload={api.reload}/>
    <form className="boss-v7-filter-bar boss-maintainer-filters" onSubmit={event=>{event.preventDefault();setFilter({query,state,date,action,authorization});setPage(1);}}>
      <label>关联任务<input type="search" value={query} onChange={event=>setQuery(event.target.value)} placeholder="对象、请求、运行或授权编号"/></label>
      <label>动作类型<select value={action} onChange={event=>setAction(event.target.value)}><option value="">全部动作</option>{actions.map(value=><option key={value}>{value}</option>)}</select></label>
      <label>授权状态<select value={authorization} onChange={event=>setAuthorization(event.target.value)}><option value="">全部授权状态</option>{authorizations.map(value=><option key={value}>{value}</option>)}</select></label>
      <label>执行日期（北京时间）<input type="date" value={date} onChange={event=>setDate(event.target.value)}/></label>
      <label>执行状态<select value={state} onChange={event=>setState(event.target.value)}><option value="">全部执行状态</option>{states.map(value=><option key={value}>{value}</option>)}</select></label><button className="boss-btn boss-btn-primary">查询 / 应用</button>
    </form>
    <div className="boss-maintainer-columns"><div className="boss-column">
      <div ref={metadata} tabIndex={-1}><V7Panel title="获准元信息核查"><V7Fact label="动作对象">{record?.target_id||"尚未选择"}</V7Fact><V7Fact label="内容版本">{record?.target_version??"尚未记录"}</V7Fact><V7Fact label="授权范围">{record?.scope.join("、")||"尚未选择"}</V7Fact><V7Fact label="有效期">{record?.valid_until??"不适用或未记录"}</V7Fact><V7Fact label="授权引用">{record?.authorization_id??"没有授权引用"}</V7Fact><p className="boss-v7-note">仅显示当前技术身份获准的元信息。私人正文继续按来源权限控制，授权决定由老板本人操作。</p></V7Panel></div>
      <V7Panel title="只读记录与状态"><div className="boss-v7-table-scroll"><table className="boss-v7-table"><thead><tr><th>对象与范围</th><th>事件版本</th><th>状态</th><th>审计入口</th></tr></thead><tbody>{records.slice((currentPage-1)*10,currentPage*10).map(row=><tr key={row.id} aria-selected={row.id===selected}><td><button className="boss-v7-text-button" onClick={()=>setSelected(row.id)}>{row.target_id||row.action}</button><small>{row.action}</small><small>{row.scope.join("、")}</small></td><td>{row.target_version??"未记录版本"}</td><td>{row.state}<small>授权：{row.authorization_state}</small><small>{row.executed_at??"没有执行时间"}</small></td><td><button className="boss-btn" onClick={()=>{setSelected(row.id);focus("metadata");}}>查看元信息</button><small>{row.request_id??"没有关联请求编号"}</small></td></tr>)}</tbody></table></div>{!records.length&&<V7Empty title="当前条件下没有只读记录"/>}<V7Pagination page={currentPage} total={records.length} pageSize={10} onChange={setPage}/></V7Panel>
    </div><aside className="boss-column"><V7Panel title="来源与依据"><V7Fact label="授权状态">{record?.authorization_state??"尚未选择"}</V7Fact><V7Fact label="执行身份">{record?.role??"尚未选择"}</V7Fact><V7Fact label="撤销时间">{record?.revoked_at??"未记录撤销"}</V7Fact><V7Fact label="已执行对象">{record?`${record.result_refs.length} 项引用`:"尚未选择"}</V7Fact><V7Fact label="正文访问">当前页面仅提供技术元信息</V7Fact><V7Fact label="执行空间">{api.data?.namespace??"尚未读取"}</V7Fact><V7Fact label="读取时间">{api.data?.read_at??"尚未读取"}</V7Fact></V7Panel>
      <div ref={execution} tabIndex={-1}><V7Panel title="状态与核查">{record?<><V7Fact label="当前正式状态">{record.state}</V7Fact><V7Fact label="原请求编号">{record.request_id??"没有关联"}</V7Fact><V7Fact label="运行编号">{record.run_id??"没有关联"}</V7Fact><V7Fact label="执行时间">{record.executed_at??"没有执行记录"}</V7Fact><V7Fact label="记录时间">{record.created_at}</V7Fact><h3>实际执行对象</h3>{record.result_refs.length?record.result_refs.map(row=><article className="boss-workspace-item" key={row.type+row.id}><strong>{row.id} · {row.type}</strong><p>{row.state} · {row.version??"未记录版本"}</p>{row.type==="runtime_run"&&<button className="boss-btn" onClick={()=>onOpenRun(row.id)}>查看运行结果</button>}</article>):<p>没有已执行对象引用。</p>}<V7Fact label="拒绝原因">{record.reason??"没有已记录原因"}</V7Fact>{record.run_id&&<button className="boss-btn" onClick={()=>onOpenRun(record.run_id!)}>打开关联运行</button>}</>:<V7Empty title="请选择动作记录"/>}</V7Panel></div>
    </aside></div>
    <footer className="boss-maintainer-actions"><span>{record?`记录 ${record.id} · ${record.state}`:"获准记录待选择"}</span><button className="boss-btn" disabled={!record} onClick={()=>focus("metadata")}>查询元信息</button><button className="boss-btn" disabled={!record} onClick={()=>focus("execution")}>查看执行结果</button><button className="boss-btn" disabled={api.loading} onClick={api.reload}>重新查询</button><button className="boss-btn" onClick={()=>onNavigate("A15")}>运行记录</button></footer>
  </div>;
}
