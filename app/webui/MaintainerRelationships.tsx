import {useEffect,useRef,useState} from "react";
import {V7Empty,V7Fact,V7Panel,V7Pagination,V7ReadState,V7Tabs} from "./BossV7UI";
import {useTechnicalWorkspace} from "./useTechnicalWorkspace";

type Row={id:string;kind:"contact"|"meeting"|"matter";name:string;version:string;source_id:string;source_type:"SIMULATED";responsibility:string;organization:string;valid_from:string;valid_until:string;state:string;editable:boolean;
  relations:{id:string;kind:string;version:string;state:string}[]};
type Projection={projection:"relationships";private_body_available_here:false;records:Row[];namespace:string;read_at:string};
type SavedView={tab:"all"|Row["kind"];filters:{query:string;date:string;scope:string};selected:string;page:number};

export function MaintainerRelationships({onNavigate,onDirtyChange,onViewSource}:{onNavigate:(page:string)=>void;onDirtyChange:(value:boolean)=>void;onViewSource:(id:string)=>void}){
  const api=useTechnicalWorkspace<Projection>("relationships");
  const saved=useRef<SavedView|undefined>(window.history.state?.bossMaintainerRecords?.A11);
  const [tab,setTab]=useState<"all"|Row["kind"]>(saved.current?.tab??"all");
  const [query,setQuery]=useState(saved.current?.filters.query??"");
  const [date,setDate]=useState(saved.current?.filters.date??"");
  const [scope,setScope]=useState(saved.current?.filters.scope??"");
  const [applied,setApplied]=useState(saved.current?.filters??{query:"",date:"",scope:""});
  const [selected,setSelected]=useState(saved.current?.selected??"");
  const [page,setPage]=useState(saved.current?.page??1);
  const [edit,setEdit]=useState<Record<string,string>|null>(null);
  const editingVersion=useRef("0"),relationPanel=useRef<HTMLDetailsElement>(null),editor=useRef<HTMLFormElement>(null);
  const records=(api.data?.records??[]).filter(row=>(tab==="all"||row.kind===tab)&&(!applied.scope||row.source_id===applied.scope)&&(!applied.query||(row.id+row.name+row.organization+row.responsibility).toLowerCase().includes(applied.query.toLowerCase()))&&(!applied.date||row.kind==="contact"&&row.valid_from<=applied.date&&row.valid_until>=applied.date));
  const currentPage=Math.min(page,Math.max(1,Math.ceil(records.length/10)));
  useEffect(()=>{if(!api.data)return;const state=window.history.state??{};window.history.replaceState({...state,bossMaintainerRecords:{...state.bossMaintainerRecords,A11:{tab,filters:applied,selected,page:currentPage}}},"",window.location.href);},[api.data,tab,applied,selected,currentPage]);
  const item=api.data?.records.find(row=>row.id===selected);
  const busy=api.loading||api.busy||!!api.pending;
  const scopes=[...new Set(api.data?.records.map(row=>row.source_id))];
  const evidence=item?.relations.filter(row=>["SOURCE_AUTHOR","MATERIAL"].includes(row.kind))??[];
  function choose(row:Row){if(edit||busy)return;setSelected(row.id);}
  function start(){if(!item?.editable||busy)return;editingVersion.current=item.version;setEdit({name:item.name,organization:item.organization,responsibility:item.responsibility,valid_from:item.valid_from,valid_until:item.valid_until});onDirtyChange(true);requestAnimationFrame(()=>{editor.current?.scrollIntoView({block:"center",behavior:"smooth"});editor.current?.querySelector("input")?.focus();});}
  function showRelations(){if(relationPanel.current){relationPanel.current.open=true;relationPanel.current.scrollIntoView({block:"center",behavior:"smooth"});relationPanel.current.querySelector("summary")?.focus();}}
  return <div className="boss-maintainer-records">
    <V7ReadState loading={api.loading} error={api.error} onReload={edit?undefined:api.reload}/>
    {api.pending&&<p className="boss-status boss-status-warn">资料操作等待核查。<button className="boss-btn" disabled={api.busy} onClick={()=>void api.reconcile()}>核查原请求</button></p>}
    {api.receipt&&<p className="boss-status boss-status-ok" role="status">资料操作已记录 · {api.receipt.request_id}</p>}
    <div className="boss-maintainer-columns"><div className="boss-column"><V7Panel title="对象与记录">
      <V7Tabs label="对象类型" value={tab} onChange={value=>{setTab(value);setPage(1);}} items={[{id:"all",title:"全部对象"},{id:"contact",title:"模拟联系人"},{id:"meeting",title:"会议"},{id:"matter",title:"事项"}]}/>
      <form className="boss-v7-filter-bar" onSubmit={event=>{event.preventDefault();setApplied({query,date,scope});setPage(1);}}><label>对象与职责<input value={query} onChange={event=>setQuery(event.target.value)} placeholder="名称、稳定 ID、职责或组织"/></label><label>职责有效日期<input type="date" value={date} onChange={event=>setDate(event.target.value)}/></label><label>模拟范围<select value={scope} onChange={event=>setScope(event.target.value)}><option value="">全部获准范围</option>{scopes.map(value=><option key={value}>{value}</option>)}</select></label><button className="boss-btn boss-btn-primary">查询对象关系</button></form>
      {records.length?<div className="boss-v7-table-scroll"><table className="boss-v7-table"><thead><tr><th>稳定对象 ID</th><th>模拟来源</th><th>职责字段</th><th>关联记录</th><th>当前状态</th></tr></thead><tbody>{records.slice((currentPage-1)*10,currentPage*10).map(row=><tr key={row.id} aria-selected={row.id===selected}><td><button className="boss-btn" disabled={!!edit} onClick={()=>choose(row)}>{row.name||row.id}</button><small>{row.id}</small></td><td>{row.source_type}<small>{row.source_id}</small></td><td>{row.responsibility||"不适用"}<small>{row.organization}</small></td><td>{row.relations.length} 项</td><td>{row.state}<small>v{row.version}</small></td></tr>)}</tbody></table></div>:<V7Empty title="当前条件下没有记录"/>}
      <V7Pagination total={records.length} page={currentPage} pageSize={10} onChange={setPage}/>
      <details ref={relationPanel} className="boss-maintainer-relations"><summary>关联记录{item?` · ${item.name||item.id} · ${item.relations.length} 项`:" · 尚未选择对象"}</summary>{item?.relations.length?<div className="boss-v7-table-scroll"><table className="boss-v7-table"><thead><tr><th>对象</th><th>关系类别</th><th>版本</th><th>状态</th><th>获准证据</th></tr></thead><tbody>{item.relations.map(row=><tr key={row.kind+row.id}><td>{row.id}</td><td>{row.kind}</td><td>{row.version}</td><td>{row.state}</td><td>{["SOURCE_AUTHOR","MATERIAL"].includes(row.kind)?<button className="boss-btn" disabled={!!edit||busy} onClick={()=>onViewSource(row.id)}>查看关系依据</button>:"对象引用"}</td></tr>)}</tbody></table></div>:<V7Empty title={item?"当前对象没有已记录关系":"尚未选择对象"}/>}</details>
    </V7Panel>
    </div><aside className="boss-column"><V7Panel title="选中记录">
      {item?<><V7Fact label="对象 ID">{item.id}</V7Fact><V7Fact label="版本">{item.version}</V7Fact><V7Fact label="来源">{item.source_id}</V7Fact><V7Fact label="职责有效期">{item.valid_from} — {item.valid_until}</V7Fact><V7Fact label="当前状态">{item.state}</V7Fact>
        {edit&&<form ref={editor} onSubmit={event=>{event.preventDefault();void api.execute("save",{object_id:item.id,expected_version:editingVersion.current,values:edit}).then(saved=>{if(saved){setEdit(null);onDirtyChange(false);}});}}><fieldset className="boss-v7-form-fieldset" disabled={busy}>{([ ["name","名称"],["organization","组织"],["responsibility","职责"],["valid_from","生效日期"],["valid_until","结束日期"]] as const).map(([key,label])=><label className="boss-field" key={key}>{label}<input required type={key.startsWith("valid_")?"date":"text"} value={edit[key]} onChange={event=>{setEdit(current=>({...current!,[key]:event.target.value}));onDirtyChange(true);}}/></label>)}<div className="boss-actions"><button className="boss-btn boss-btn-primary">保存资料</button><button type="button" className="boss-btn" onClick={()=>{setEdit(null);onDirtyChange(false);}}>取消编辑</button></div></fieldset></form>}
      </>:<V7Empty title="尚未选择记录">选择条目后查看对象、来源及当前状态。</V7Empty>}
    </V7Panel><V7Panel title="状态与核查"><V7Fact label="关联对象">{item?`${item.relations.length} 项`:"尚未选择"}</V7Fact><V7Fact label="资料证据">{item?`${evidence.length} 项来源引用`:"尚未选择"}</V7Fact><V7Fact label="维护权限">{item?item.editable?"获准模拟资料":"仅供查询":"尚未选择"}</V7Fact><V7Fact label="执行空间">{api.data?.namespace??"尚未读取"}</V7Fact><V7Fact label="读取时间">{api.data?.read_at??"尚未读取"}</V7Fact><p>联系人属于资料对象，没有产品账号。老板交办决定、授权引用和正式状态历史仅供有权查询。</p><button className="boss-btn" onClick={()=>onNavigate("A14")}>查看动作授权记录</button></V7Panel></aside></div>
    <footer className="boss-maintainer-actions"><span>{item?`${item.name||item.id} · v${item.version}`:"资料待选择"}</span><button className="boss-btn boss-btn-primary" disabled={!item?.editable||!!edit||busy} title={!item?"请先选择一条记录":!item.editable?"当前对象不是获准模拟资料":undefined} onClick={start}>编辑模拟资料</button><button className="boss-btn" disabled={!item||!!edit} onClick={showRelations}>查看此对象的关系</button><button className="boss-btn" disabled={!item||item.kind!=="matter"||busy} title={!item?"请先选择一条记录":item.kind!=="matter"?"只有模拟事项可以回复":undefined} onClick={()=>onNavigate("A04")}>为此模拟事项提供回复</button><button className="boss-btn" disabled={!evidence.length||!!edit||busy} title={!evidence.length?"当前对象没有关系依据":undefined} onClick={()=>{if(evidence.length===1)onViewSource(evidence[0].id);else showRelations();}}>查看关系依据</button></footer>
  </div>;
}
