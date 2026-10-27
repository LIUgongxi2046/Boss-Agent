import {useEffect,useRef,useState} from "react";
import {CalendarDays,FileText,Search} from "lucide-react";
import {useOwnerWorkspace} from "./useTechnicalWorkspace";
import {replaceBossHistory} from "./boss-history";
import {V7Panel,V7Empty,V7Fact,V7Pagination,V7ReadState,V7Tabs} from "./BossV7UI";

const TABS=[{id:"meeting",title:"会议"},{id:"document",title:"资料"},{id:"approval",title:"待决定申请"},{id:"research",title:"研究材料"},{id:"people",title:"人员会面"}] as const;
type Kind=typeof TABS[number]["id"];
type ActionId="prepare"|"source"|"minutes"|"history"|"discuss"|"open";
export type LibraryAction={id:ActionId;title:string;enabled:boolean;disabled_reason:string|null;page:"F04"|"F05"|"F07"|"F09"|"F10"|"N11"|"N02"|"D01";source_id:string|null};
export type LibraryReference={id:string;kind:Kind;version:string;namespace:string};
type LibraryRecord={id:string;kind:Kind;title:string;version:string;at:string|null;local_date:string|null;timezone:string|null;source_type:string;
  summary:string;material_state:string;material_gaps:string[];meeting_state:string|null;preparation_state:string|null;minute_state:string|null;assignment_state:string|null;
  source_refs:{source_id:string;version:string;location:string|null}[];related_objects:{id:string;title:string;kind:string}[];actions:LibraryAction[]};
type Projection={projection:"meeting-library";namespace:string;source_type:string;read_at:string;records:LibraryRecord[];coverage:{kind:Kind;state:string;reason:string|null}[]};
type Props={onOpen:(action:LibraryAction,reference:LibraryReference)=>void;onViewSource:(id:string)=>void;refreshVersion?:number};
const MATERIAL_STATE_TABS:Kind[]=["meeting","document","research"];
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

export function BossMeetingLibrary({onOpen,onViewSource,refreshVersion}:Props){
  const api=useOwnerWorkspace<Projection>("meeting-library");
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
  function open(action:LibraryAction){
    if(!selected||!api.data||!action.enabled||api.loading)return;
    if(action.id==="source"){if(!action.source_id)throw new Error("原文入口缺少来源标识");onViewSource(action.source_id);return;}
    onOpen(action,{id:selected.id,kind:selected.kind,version:selected.version,namespace:api.data.namespace});
  }
  const findAction=(id:ActionId)=>selected?.actions.find(item=>item.id===id);
  const prepare=selected?.kind==="meeting"?findAction("prepare"):undefined,openAction=findAction("open");
  const sourceAction=findAction("source"),minutes=findAction("minutes"),history=findAction("history"),discuss=findAction("discuss");
  const primary=prepare??openAction;
  const primaryLabel=prepare?"准备会前材料":openAction?.title??"";
  const discussLabel=selected?.kind==="meeting"?"讨论这场会议":selected?.kind==="document"?"让大鹏整理这份资料":discuss?.title??"继续讨论";
  return <div className="boss-meeting-library">
    <V7ReadState loading={api.loading} error={api.error} onReload={api.reload}/>
    <div className="boss-library-columns"><div className="boss-column"><V7Panel title="对象与记录">
      <V7Tabs label="会议资料分类" value={view.tab} onChange={changeTab} items={TABS.map(item=>({...item,count:api.data?records.filter(record=>record.kind===item.id).length:undefined}))}/>
      <form className="boss-v7-filter-bar boss-library-filters" onSubmit={event=>{event.preventDefault();update({...view,query:query.trim(),from,to,state,selected:""});}}>
        <label>起始日期<input type="date" value={from} onChange={event=>setFrom(event.target.value)}/></label><label>结束日期<input type="date" value={to} onChange={event=>setTo(event.target.value)}/></label><label>关联对象<input value={query} onChange={event=>setQuery(event.target.value)} placeholder="按名称搜索当前分类"/></label>{stateFilter&&<label>材料状态<select value={state} onChange={event=>setState(event.target.value)}><option value="">全部已读取状态</option>{[...new Set(directory.map(record=>record.material_state))].map(value=><option key={value}>{value}</option>)}</select></label>}<button className="boss-btn boss-btn-primary" type="submit" disabled={api.loading}><Search size={16}/>筛选</button><button className="boss-btn" type="button" disabled={api.loading} onClick={clearFilters}>清除筛选</button>
      </form>
      {coverage&&coverage.state!=="COMPLETE"&&<p className="boss-status boss-status-warn">{coverage.state} · {coverage.reason??"当前类别资料覆盖尚不完整"}</p>}
      <div className="boss-v7-table-scroll"><table className="boss-v7-table"><thead><tr><th>标题</th><th>时间与时区</th><th>来源版本</th><th>准备或核查状态</th><th>材料缺口</th><th>关联事项</th></tr></thead><tbody>{filtered.slice((currentPage-1)*10,currentPage*10).map(record=><tr key={record.kind+record.id} aria-selected={record.id===selected?.id}><td><button className="boss-v7-text-button" aria-label={record.title+"，"+(record.at??"时间尚未提供")} onClick={()=>update({...view,selected:record.id},false)}>{record.kind==="meeting"?<CalendarDays size={17}/>:<FileText size={17}/>}<span>{record.title}</span></button></td><td>{record.at??"尚未提供"}<small>{record.timezone??"时区尚未提供"}</small></td><td>{record.version}<small>{record.source_type}</small></td><td>{record.material_state}</td><td>{record.material_gaps.length?record.material_gaps.join("；"):"当前记录未列出材料缺口"}</td><td>{record.related_objects.map(item=>item.title+"（"+item.id+"）").join("；")||"没有已读取关联"}</td></tr>)}</tbody></table></div>
      {!filtered.length&&<V7Empty title={api.loading?"正在读取当前目录":api.error?"目录读取失败":api.data?"当前条件下没有已读取记录":"目录待读取"}>按当前本人权限查询，缺少资料时保留明确状态。</V7Empty>}{api.data&&<V7Pagination page={currentPage} total={filtered.length} pageSize={10} onChange={setPage}/>}
    </V7Panel></div><aside className="boss-column"><V7Panel title="选中记录">{selected?<><h3>{selected.title}</h3><p>{selected.summary}</p><V7Fact label="对象与版本">{selected.id} · v{selected.version}</V7Fact><V7Fact label="时间与时区">{selected.at??"尚未提供"} · {selected.timezone??"未知"}</V7Fact><V7Fact label="材料缺口">{selected.material_gaps.join("；")||"当前记录未列出缺口"}</V7Fact><V7Fact label="来源属性">{selected.source_type}</V7Fact>{selected.source_refs.length?selected.source_refs.map(source=><article className="boss-workspace-item" key={source.source_id+source.version}><strong>{source.source_id} · v{source.version}</strong><p>{source.location??"原文位置待核查"}</p>{sourceAction?.enabled&&<button className="boss-btn" onClick={()=>onViewSource(source.source_id)}>阅读原文</button>}</article>):<p className="boss-v7-note">当前记录尚未产生原文依据。</p>}{sourceAction&&!sourceAction.enabled&&<p className="boss-v7-note">阅读原文：{actionReason(sourceAction)}</p>}
        {minutes&&<DetailAction action={minutes} label="打开纪要" loading={api.loading} onOpen={open}/>}
        {history&&<DetailAction action={history} label="查看历史决定" loading={api.loading} onOpen={open}/>}
        {discuss&&<DetailAction action={discuss} label={discussLabel} loading={api.loading} onOpen={open}/>}
      </>:missingSelected?<V7Empty title="上次选中的记录已不在当前目录">该记录可能已被撤销或移出目录，详情已经清理；请重新选择当前目录记录。</V7Empty>:<V7Empty title="尚未选择记录">选择当前目录记录，查看摘要和关联操作。</V7Empty>}</V7Panel>
      <V7Panel title="状态与核查"><V7Fact label="会议举行">{selected?.meeting_state??"尚未取得对应记录"}</V7Fact><V7Fact label="材料准备">{selected?.preparation_state??"尚未取得对应记录"}</V7Fact><V7Fact label="纪要确认">{selected?.minute_state??"尚未取得对应记录"}</V7Fact><V7Fact label="交办状态">{selected?.assignment_state??"尚未取得对应记录"}</V7Fact><V7Fact label="目录读取时间">{api.data?.read_at??"尚未读取"}</V7Fact></V7Panel>
    </aside></div>
    {(!selected||primary)&&<footer className="boss-owner-actions">{selected&&primary?<><button className={"boss-btn boss-btn-primary"} disabled={!primary.enabled||api.loading} title={primary.disabled_reason??undefined} onClick={()=>open(primary)}>{primaryLabel}</button>{!primary.enabled&&<p className="boss-v7-note">{primaryLabel}：{actionReason(primary)}</p>}</>:<p className="boss-v7-note">请先选择目录记录，再执行准备会前材料或打开当前对象。</p>}</footer>}
  </div>;
}
