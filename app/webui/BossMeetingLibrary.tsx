import {useEffect,useRef,useState} from "react";
import {CalendarDays,FileText,Search} from "lucide-react";
import {useOwnerWorkspace} from "./useTechnicalWorkspace";
import {replaceBossHistory} from "./boss-history";
import {V7Panel,V7Empty,V7Pagination,V7ReadState,V7Tabs} from "./BossV7UI";
import {BossInsightList,type BossInsight} from "./BossInsightList";

const TABS=[{id:"meeting",title:"会议"},{id:"document",title:"资料"},{id:"approval",title:"待决定申请"},{id:"research",title:"研究材料"},{id:"people",title:"人员会面"}] as const;
type Kind=typeof TABS[number]["id"];
type ActionId="prepare"|"source"|"minutes"|"history"|"discuss"|"open";
export type LibraryAction={id:ActionId;title:string;enabled:boolean;disabled_reason:string|null;page:"F04"|"F05"|"F07"|"F09"|"F10"|"N11"|"N02"|"D01";source_id:string|null};
export type LibraryReference={id:string;kind:Kind;version:string;namespace:string};
type LibraryRecord={id:string;kind:Kind;title:string;version:string;at:string|null;local_date:string|null;timezone:string|null;source_type:string;
  summary:string;material_state:string;material_gaps:string[];meeting_state:string|null;preparation_state:string|null;minute_state:string|null;assignment_state:string|null;
  source_refs:{source_id:string;version:string;location:string|null}[];related_objects:{id:string;title:string;kind:string}[];actions:LibraryAction[]};
export type LibraryProjection={projection:"meeting-library";namespace:string;source_type:string;read_at:string;insights:BossInsight[];records:LibraryRecord[];coverage:{kind:Kind;state:string;reason:string|null}[]};
type Props={onOpen:(action:LibraryAction,reference:LibraryReference)=>void;onViewSource:(id:string)=>void;onDiscuss:(question:string)=>Promise<boolean|void>;refreshVersion?:number};
const MATERIAL_STATE_TABS:Kind[]=["meeting","document","research"];
const STATES:Record<string,string>={READY:"材料齐备",PARTIAL:"待补充材料",MATERIALS_MISSING:"等待材料",VALID:"可以阅读",CURRENT:"当前有效",DRAFT:"正在准备",PREPARED:"已准备",PENDING_DECISION:"待我决定",WAITING_MATERIAL:"待补充材料",APPROVED_RECORDED:"已同意",REJECTED_RECORDED:"已驳回",CONFIRMED:"已确认",HELD:"已举行",CANCELED:"已取消",WITHDRAWN:"已撤回",EXPIRED:"已到期",COMPLETED:"已完成"};
function stateLabel(value:string){return STATES[value]??"待核查";}
function displayTime(record:LibraryRecord){return record.at?new Intl.DateTimeFormat("zh-CN",{timeZone:record.timezone??"Asia/Shanghai",year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false}).format(new Date(record.at)):"时间待安排";}
function initial(){const parameters=new URLSearchParams(window.location.search);const raw=parameters.get("libraryTab");return {tab:TABS.some(item=>item.id===raw)?raw as Kind:"meeting" as Kind,query:parameters.get("libraryQuery")??"",from:parameters.get("libraryDateFrom")??"",to:parameters.get("libraryDateTo")??"",state:parameters.get("libraryState")??"",selected:parameters.get("librarySelected")??""};}
function inRange(record:LibraryRecord,from:string,to:string){
  if(!from&&!to)return true;
  if(!record.local_date)return false;
  return(!from||record.local_date>=from)&&(!to||record.local_date<=to);
}
function actionReason(action:LibraryAction){return action.disabled_reason??"当前操作条件未满足";}
function DetailAction({action,label,loading,onOpen}:{action:LibraryAction;label:string;loading:boolean;onOpen:(action:LibraryAction)=>void}){
  return <div><button className="boss-btn" disabled={!action.enabled||loading} title={action.disabled_reason??undefined} onClick={()=>onOpen(action)}>{label}</button>{!action.enabled&&<p className="boss-v7-note">{label}：{actionReason(action)}</p>}</div>;
}

export function BossMeetingLibrary({onOpen,onViewSource,onDiscuss,refreshVersion}:Props){
  const api=useOwnerWorkspace<LibraryProjection>("meeting-library");
  const [sending,setSending]=useState(false);
  const discussionActive=useRef(false);
  const [view,setView]=useState(initial),[query,setQuery]=useState(view.query),[from,setFrom]=useState(view.from),[to,setTo]=useState(view.to),[state,setState]=useState(view.state),[page,setPage]=useState(1);
  const previousRefresh=useRef(refreshVersion);
  useEffect(()=>{if(previousRefresh.current===refreshVersion)return;previousRefresh.current=refreshVersion;api.reload();},[refreshVersion,api.reload]);
  const records=api.data?.records??[];
  const directory=records.filter(record=>record.kind===view.tab);
  const stateFilter=MATERIAL_STATE_TABS.includes(view.tab);
  const filtered=directory.filter(record=>(!view.query||[record.title,record.id,...record.related_objects.flatMap(item=>[item.title,item.id])].join(" ").toLocaleLowerCase().includes(view.query.toLocaleLowerCase()))&&inRange(record,view.from,view.to)&&(!stateFilter||!view.state||record.material_state===view.state));
  const selected=filtered.find(record=>record.id===view.selected);
  const missingSelected=Boolean(view.selected&&api.data&&!api.loading&&!api.data.records.some(record=>record.kind===view.tab&&record.id===view.selected));
  const coverage=api.data?.coverage.find(item=>item.kind===view.tab);
  const currentPage=Math.min(page,Math.max(1,Math.ceil(filtered.length/10)));
  function update(next:typeof view,resetPage=true){
    setView(next);if(resetPage)setPage(1);const url=new URL(window.location.href);
    for(const [key,value] of Object.entries({libraryTab:next.tab,libraryQuery:next.query,libraryDateFrom:next.from,libraryDateTo:next.to,libraryState:next.state,librarySelected:next.selected}))value?url.searchParams.set(key,value):url.searchParams.delete(key);
    replaceBossHistory(url);
  }
  function changeTab(tab:Kind){
    const states=records.filter(record=>record.kind===tab).map(record=>record.material_state);
    const keep=MATERIAL_STATE_TABS.includes(tab)&&states.includes(state);
    if(!keep)setState("");
    update({...view,tab,state:keep?state:"",selected:""});
  }
  function clearFilters(){setQuery("");setFrom("");setTo("");setState("");update({...view,query:"",from:"",to:"",state:""});}
  async function discussRecord(record:LibraryRecord){
    if(!api.data||discussionActive.current)return;
    discussionActive.current=true;setSending(true);
    const question=["请读取当前获准资料，分析所选事项的依据、影响、尚待核查内容及建议行动。",
      "事项："+record.title,"对象类别："+record.kind,"对象编号："+record.id,"对象版本："+record.version,
      "执行空间："+api.data.namespace,"当前记录摘要："+record.summary,
      "来源："+record.source_refs.map(source=>source.source_id+" v"+source.version).join("、"),
      "请使用业务工具重新读取当前记录与原文；事实、推断和建议分别表达。此请求仅查询分析，不授权业务变更或发送消息。"].join("\n");
    try{
      const result=await onDiscuss(question);
      if(result===false)throw new Error("当前会话没有接受问题，请重新提交。");
      onOpen({id:"discuss",title:"继续讨论",enabled:true,disabled_reason:null,page:"N02",source_id:null},
        {id:record.id,kind:record.kind,version:record.version,namespace:api.data.namespace});
    }finally{discussionActive.current=false;setSending(false);}
  }
  function open(action:LibraryAction){
    if(!selected||!api.data||!action.enabled||api.loading||sending)return;
    if(action.id==="source"){if(!action.source_id)throw new Error("原文入口缺少来源标识");onViewSource(action.source_id);return;}
    if(action.id==="discuss"){void discussRecord(selected);return;}
    onOpen(action,{id:selected.id,kind:selected.kind,version:selected.version,namespace:api.data.namespace});
  }
  const findAction=(id:ActionId)=>selected?.actions.find(item=>item.id===id);
  const prepare=selected?.kind==="meeting"?findAction("prepare"):undefined,openAction=findAction("open");
  const sourceAction=findAction("source"),minutes=findAction("minutes"),history=findAction("history"),discuss=findAction("discuss");
  const primary=prepare??openAction;
  const primaryLabel=prepare?"准备会前材料":openAction?.title??"";
  const discussLabel=selected?.kind==="meeting"?"讨论这场会议":selected?.kind==="document"?"让 Boss Agent 整理这份资料":discuss?.title??"继续讨论";
  return <div className="boss-meeting-library">
    {sending&&<p role="status">正在提交问题…</p>}
    <V7ReadState loading={api.loading} error={api.error} onReload={api.reload}/>
    <div className="boss-library-columns"><div className="boss-column"><V7Panel title="对象与记录">
      <V7Tabs label="会议资料分类" value={view.tab} onChange={changeTab} items={TABS.map(item=>({...item,count:api.data?records.filter(record=>record.kind===item.id).length:undefined}))}/>
      <form className="boss-v7-filter-bar boss-library-filters" onSubmit={event=>{event.preventDefault();update({...view,query:query.trim(),from,to,state,selected:""});}}>
        <label>起始日期<input type="date" value={from} onChange={event=>setFrom(event.target.value)}/></label><label>结束日期<input type="date" value={to} onChange={event=>setTo(event.target.value)}/></label><label>关联对象<input value={query} onChange={event=>setQuery(event.target.value)} placeholder="按名称搜索当前分类"/></label>{stateFilter&&<label>材料状态<select value={state} onChange={event=>setState(event.target.value)}><option value="">全部状态</option>{[...new Set(directory.map(record=>record.material_state))].map(value=><option key={value} value={value}>{stateLabel(value)}</option>)}</select></label>}<button className="boss-btn boss-btn-primary" type="submit" disabled={api.loading}><Search size={16}/>筛选</button><button className="boss-btn" type="button" disabled={api.loading} onClick={clearFilters}>清除筛选</button>
      </form>
      {coverage&&coverage.state!=="COMPLETE"&&<p className="boss-status boss-status-warn">{coverage.reason??"当前类别还有材料需要补充。"}</p>}
      <div className="boss-v7-table-scroll"><table className="boss-v7-table"><thead><tr><th>标题</th><th>时间</th><th>状态</th><th>相关人员与事项</th></tr></thead><tbody>{filtered.slice((currentPage-1)*10,currentPage*10).map(record=><tr key={record.kind+record.id} aria-selected={record.id===selected?.id}><td><button className="boss-v7-text-button" aria-label={record.title+"，"+displayTime(record)} onClick={()=>update({...view,selected:record.id},false)}>{record.kind==="meeting"?<CalendarDays size={17}/>:<FileText size={17}/>}<span>{record.title}</span></button></td><td>{displayTime(record)}</td><td>{stateLabel(record.material_state)}</td><td>{record.related_objects.map(item=>item.title).join("；")||"暂无关联事项"}</td></tr>)}</tbody></table></div>
      {!filtered.length&&<V7Empty title={api.loading?"正在读取当前目录":api.error?"目录读取失败":api.data?"当前条件下没有已读取记录":"目录待读取"}>按当前本人权限查询，缺少资料时保留明确状态。</V7Empty>}{api.data&&<V7Pagination page={currentPage} total={filtered.length} pageSize={10} onChange={setPage}/>}
    </V7Panel>{selected&&<V7Panel title={selected.title}><p>{selected.summary}</p><p>{displayTime(selected)} · {stateLabel(selected.material_state)}</p>{selected.source_refs.map((source,index)=><button key={source.source_id} className="boss-btn" disabled={!sourceAction?.enabled} onClick={()=>onViewSource(source.source_id)}>阅读材料 {index+1}</button>)}
        {minutes&&<DetailAction action={minutes} label="打开纪要" loading={api.loading} onOpen={open}/>}
        {history&&<DetailAction action={history} label="查看历史决定" loading={api.loading} onOpen={open}/>}
        {discuss&&<DetailAction action={discuss} label={discussLabel} loading={api.loading} onOpen={open}/>}
      </V7Panel>}{missingSelected&&<p role="status">上次选中的记录已经更新，请重新选择。</p>}</div><aside className="boss-column"><V7Panel title="Boss Agent 建议">
        {api.data&&<BossInsightList items={api.data.insights.filter(item=>item.target_kind===view.tab&&(!selected||item.target_id===selected.id))} disabled={api.loading||sending} label="查看依据与继续分析" onOpen={item=>{const record=records.find(row=>row.id===item.target_id&&row.kind===item.target_kind);if(!record||!api.data)throw new Error("提醒关联资料已经变化");const action=record.actions.find(row=>row.id==="discuss"&&row.enabled);if(action)void discussRecord(record);else update({...view,selected:record.id},false);}}/>}
        {selected&&discuss&&<DetailAction action={discuss} label="与 Boss Agent 讨论" loading={api.loading} onOpen={open}/>}
      </V7Panel>
    </aside></div>
    {(!selected||primary)&&<footer className="boss-owner-actions">{selected&&primary?<><button className={"boss-btn boss-btn-primary"} disabled={!primary.enabled||api.loading} title={primary.disabled_reason??undefined} onClick={()=>open(primary)}>{primaryLabel}</button>{!primary.enabled&&<p className="boss-v7-note">{primaryLabel}：{actionReason(primary)}</p>}</>:<p className="boss-v7-note">请先选择目录记录，再执行准备会前材料或打开当前对象。</p>}</footer>}
  </div>;
}
