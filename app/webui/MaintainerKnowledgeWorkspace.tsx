import {useEffect,useRef,useState} from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {useClient} from "@/providers/ClientProvider";
import {V7Empty,V7Fact,V7Panel,V7Pagination,V7ReadState} from "./BossV7UI";
import {useTechnicalWorkspace,type TechnicalReceipt} from "./useTechnicalWorkspace";

type Source={id:string;title:string;author_id:string;observed_at:string;published_at:string;valid_until:string|null;visibility:string;version:string;index_state:string;withdrawn:boolean;editable:boolean;source_type:"SIMULATED";file_name:string;content_sha256:string;original_available:boolean;error:string|null};
type Projection={projection:"knowledge";private_body_available_here:false;sources:Source[];authors:{id:string;label:string}[];visibility_options:{id:string;label:string}[];namespace:string;read_at:string};
type Upload={name:string;mime_type:string;size:number;content_base64:string};
type Hit={source_id:string;version:string;title:string;excerpt:string;start:number;end:number;index_state:string};
type FormMode="create"|"revise"|null;
const EMPTY={source_id:"",title:"",author_id:"",observed_at:"",published_at:"",valid_until:"",visibility:"",change_note:""};

function formatLabel(fileName:string){
  const parts=fileName.split(".");
  return parts.length>1?parts[parts.length-1].toUpperCase():"";
}
function availability(row:Source){
  if(row.withdrawn)return "已撤销，不参与检索";
  return row.index_state==="INDEXED_CURRENT"?"已索引":"仅有目录，尚未索引";
}
function searchableVersion(row:Source|undefined){
  if(!row)return "尚未选择";
  if(row.withdrawn)return "无（已撤销）";
  return row.index_state==="INDEXED_CURRENT"?`v${row.version}（受权限与有效期约束）`:`无（索引状态 ${row.index_state}）`;
}
function receiptText(receipt:TechnicalReceipt){
  const result=receipt.result as {source_id?:string;version?:string;index_state?:string;withdrawn?:boolean;source_history_preserved?:boolean};
  return ["任务编号 "+receipt.request_id,result.source_id??"",result.version?"v"+result.version:"",result.index_state??"",result.withdrawn?"来源已撤销":"",result.source_history_preserved?"历史版本保留":""].filter(Boolean).join(" · ");
}

export function MaintainerKnowledgeWorkspace({onDirtyChange}:{onDirtyChange:(dirty:boolean)=>void;onNavigate:(page:string)=>void}){
  const api=useTechnicalWorkspace<Projection>("knowledge");
  const {getToken}=useClient();
  const [tab,setTab]=useState<"catalog"|"pending"|"retrieval"|"withdrawn">("catalog");
  const [formMode,setFormMode]=useState<FormMode>(null);
  const [selected,setSelected]=useState("");
  const [values,setValues]=useState(EMPTY),[upload,setUpload]=useState<Upload|null>(null),[text,setText]=useState("");
  const [dirty,setDirty]=useState(false),[reading,setReading]=useState(false);
  const [query,setQuery]=useState(""),[hits,setHits]=useState<Hit[]|null>(null),[searching,setSearching]=useState(false),[searchError,setSearchError]=useState("");
  const [page,setPage]=useState(1),[error,setError]=useState("");
  const [filters,setFilters]=useState({document:"",source:"",version:"",validUntil:"",index:""});
  const [action,setAction]=useState<"ingest"|"revise"|"withdraw"|null>(null),[confirmed,setConfirmed]=useState(false);
  const searchSequence=useRef(0);
  const searchController=useRef<AbortController|null>(null);
  const fileReader=useRef<FileReader|null>(null);
  useEffect(()=>()=>{searchSequence.current++;searchController.current?.abort();fileReader.current?.abort();},[]);
  const fileInput=useRef<HTMLInputElement>(null);
  const searchInput=useRef<HTMLInputElement>(null);
  const editingVersion=useRef("0");
  const selectedSource=api.data?.sources.find(row=>row.id===selected);
  const matching=(api.data?.sources??[]).filter(row=>
    (!filters.document||[row.title,row.id,row.file_name].some(value=>value.toLocaleLowerCase().includes(filters.document.toLocaleLowerCase())))
    &&(!filters.source||row.author_id===filters.source)&&(!filters.version||row.version===filters.version)
    &&(!filters.validUntil||!!row.valid_until&&row.valid_until<=filters.validUntil)&&(!filters.index||row.index_state===filters.index));
  const active=matching.filter(row=>!row.withdrawn);
  const pending=active.filter(row=>row.index_state!=="INDEXED_CURRENT");
  const unindexed=(api.data?.sources??[]).filter(row=>!row.withdrawn&&row.index_state!=="INDEXED_CURRENT").length;
  const withdrawn=matching.filter(row=>row.withdrawn);
  const records=tab==="withdrawn"?withdrawn:tab==="pending"?pending:active;
  const currentPage=Math.min(page,Math.max(1,Math.ceil(records.length/10)));
  const busy=api.loading||api.busy||!!api.pending||reading;
  const visibilityLabel=(id:string)=>api.data?.visibility_options.find(row=>row.id===id)?.label??(id||"尚未选择");
  const writeBlocked=busy?"正在读取或提交，请等待本次操作结束。":dirty?"资料正在编辑，请先保存或取消本次编辑。":"";
  const canSubmit=!busy&&dirty&&!!(upload||text.trim())&&(formMode!=="revise"||!!selectedSource?.editable);
  const submitReason=busy?"正在读取或提交，请等待本次操作结束。":!dirty?"尚未填写本次资料内容。":!(upload||text.trim())?"请选择文件或录入获准文本后再开始摄取。":formMode==="revise"&&!selectedSource?.editable?"所选来源不属于维护端录入的模拟资料，或已撤销，不能提交新版本。":"";
  const refreshReason=busy?"正在读取或提交，请等待本次操作结束。":"";
  const searchReason=searching?"正在检索，请等待本次结果。":!api.data?"尚未读取资料目录，不能执行检索检查。":busy?"正在读取或提交，请等待本次操作结束。":!query.trim()?"请输入检索内容后再执行检索检查。":"";
  function filter(key:keyof typeof filters,value:string){setFilters(previous=>({...previous,[key]:value}));setPage(1);}
  function clearSearch(){searchSequence.current++;searchController.current?.abort();setSearching(false);setHits(null);setSearchError("");}
  useEffect(()=>{clearSearch();},[api.data]);
  function sourceValues(source:Source){return{source_id:source.id,title:source.title,author_id:source.author_id,observed_at:source.observed_at,published_at:source.published_at,valid_until:source.valid_until??"",visibility:source.visibility,change_note:""};}
  function edit(key:keyof typeof values,value:string){setValues(old=>({...old,[key]:value}));setDirty(true);onDirtyChange(true);}
  function choose(source:Source){if(dirty||busy)return;setSelected(source.id);setValues(sourceValues(source));editingVersion.current=source.version;setUpload(null);setText("");setError("");setFormMode(null);}
  function startCreate(){if(dirty||busy)return;setSelected("");setValues(EMPTY);editingVersion.current="0";setUpload(null);setText("");setError("");setFormMode("create");setTab("catalog");setPage(1);}
  function startRevise(){if(!selectedSource?.editable||dirty||busy)return;setFormMode("revise");setValues(sourceValues(selectedSource));editingVersion.current=selectedSource.version;setUpload(null);setText("");setError("");}
  useEffect(()=>{if(!dirty&&selectedSource){setValues(sourceValues(selectedSource));editingVersion.current=selectedSource.version;}},[selectedSource,dirty]);
  function readFile(file:File){
    if(!file.size||file.size>20*1024*1024){setError("请选择包含内容且不超过20 MB的文件。");return;}
    setReading(true);setError("");const reader=new FileReader();fileReader.current=reader;
    reader.onload=()=>{const encoded=reader.result;if(typeof encoded!=="string")throw new Error("文件读取结果无效");setUpload({name:file.name,mime_type:file.type,size:file.size,content_base64:encoded.slice(encoded.indexOf(",")+1)});setText("");setReading(false);setDirty(true);onDirtyChange(true);setFormMode(mode=>mode??"create");};
    reader.onerror=()=>{setError(reader.error?.message??"文件读取失败");setReading(false);};reader.readAsDataURL(file);
  }
  function search(){
    const value=query.trim();
    if(!value){setHits(null);setSearchError("请输入检索内容后再执行检索检查。");return;}
    searchController.current?.abort();
    const controller=new AbortController();searchController.current=controller;
    const token=getToken();
    const sequence=++searchSequence.current;setSearching(true);setSearchError("");
    void fetch("/api/boss/ui/admin/technical/knowledge/search?"+new URLSearchParams({query:value}),{headers:{Authorization:"Bearer "+token},cache:"no-store",signal:controller.signal}).then(async response=>{if(!response.ok)throw new Error("检索失败（HTTP "+response.status+"）");const result=await response.json() as {projection:string;hits:Hit[]};if(result.projection!=="knowledge-search")throw new Error("检索返回类型无效");if(sequence===searchSequence.current&&getToken()===token){setHits(result.hits);setSearching(false);}}).then(undefined,reason=>{if(sequence===searchSequence.current&&getToken()===token&&!controller.signal.aborted){setSearchError(reason instanceof Error?reason.message:String(reason));setSearching(false);}});
  }
  function submit(){if(!action||!confirmed||busy)return;const sourceId=selected||values.source_id;void api.execute(action,{source_id:sourceId,expected_version:editingVersion.current,values,upload,text,confirmation:true}).then(saved=>{if(saved){setSelected(sourceId);setDirty(false);onDirtyChange(false);setUpload(null);setText("");setFormMode(null);clearSearch();setTab(action==="withdraw"?"withdrawn":"catalog");}});setAction(null);}
  function cancelEdit(){setValues(selectedSource?sourceValues(selectedSource):EMPTY);editingVersion.current=selectedSource?.version??"0";setUpload(null);setText("");setError("");setDirty(false);onDirtyChange(false);setFormMode(null);}
  function openSearch(){setTab("retrieval");searchInput.current?.scrollIntoView({block:"center",behavior:"smooth"});searchInput.current?.focus();}
  const tabs=[{id:"catalog",title:"文档目录",count:active.length},{id:"pending",title:"待摄取资料",count:pending.length},{id:"retrieval",title:"检索命中",count:hits?.length},{id:"withdrawn",title:"撤销状态",count:withdrawn.length}] as const;
  return <div className="boss-knowledge-workspace"><V7ReadState loading={api.loading} error={api.error||error} onReload={dirty?undefined:api.reload}/>{api.pending&&<p className="boss-status boss-status-warn">摄取或版本操作等待核查。<button className="boss-btn" disabled={api.busy} onClick={()=>void api.reconcile()}>核查原请求</button></p>}
    {api.receipt&&<p className="boss-status boss-status-ok" role="status">操作已记录 · {receiptText(api.receipt)}</p>}
    <div className="boss-v7-filter-bar boss-knowledge-filters" role="search" aria-label="来源目录筛选">
      <label>文档<input type="search" value={filters.document} onChange={event=>filter("document",event.target.value)} placeholder="标题、标识或文件名称"/></label>
      <label>来源作者<select value={filters.source} onChange={event=>filter("source",event.target.value)}><option value="">全部作者</option>{api.data?.authors.map(row=><option key={row.id} value={row.id}>{row.label}</option>)}</select></label>
      <label>版本<input value={filters.version} onChange={event=>filter("version",event.target.value)} placeholder="全部版本"/></label>
      <label>有效期截止<input type="date" value={filters.validUntil} onChange={event=>filter("validUntil",event.target.value)}/></label>
      <label>索引状态<select value={filters.index} onChange={event=>filter("index",event.target.value)}><option value="">全部状态</option>{[...new Set(api.data?.sources.map(row=>row.index_state))].map(value=><option key={value}>{value}</option>)}</select></label>
      <button className="boss-btn" disabled={busy} onClick={api.reload}>{api.loading?"刷新中…":"刷新列表"}</button>
    </div>
    <p className="boss-v7-note">筛选同时作用于资料列表与导航数量。刷新列表只读取目录与状态，不清除未保存编辑。</p>
    {busy&&<p className="boss-v7-note">正在读取或提交，刷新列表需等待本次操作结束。</p>}
    <div className="boss-knowledge-columns"><aside className="boss-column"><V7Panel title="获准知识目录">
      <button className="boss-btn boss-btn-primary" disabled={!!writeBlocked} onClick={startCreate}>添加来源资料</button>
      {writeBlocked&&<p className="boss-v7-note">{writeBlocked}</p>}
      <nav className="boss-knowledge-directory" aria-label="知识资料视图">{tabs.map(item=><button className="boss-btn" key={item.id} aria-current={tab===item.id?"page":undefined} onClick={()=>{setTab(item.id);setPage(1);if(item.id==="retrieval")openSearch();}}><span>{item.title}</span>{"count" in item&&item.count!==undefined&&<small>{item.count} 条</small>}</button>)}</nav>
      <p className="boss-v7-note">支持 TXT、Markdown、PDF、DOCX，最多20 MB。仅接收获准模拟资料。</p>
    </V7Panel></aside>
    <div className="boss-column"><V7Panel title={formMode==="create"?"添加来源资料":formMode==="revise"?"添加新版本":"来源资料与版本"}>
    {formMode?<form id="boss-knowledge-editor" onSubmit={event=>{event.preventDefault();setConfirmed(false);setAction(formMode==="revise"?"revise":"ingest");}}>
      <fieldset disabled={busy||!api.data||(formMode==="revise"&&!selectedSource?.editable)} className="boss-v7-form-fieldset"><div className="boss-form-grid">
        <label>来源标识<input required readOnly={formMode==="revise"} value={values.source_id} onChange={event=>edit("source_id",event.target.value)}/></label><label>资料标题<input required value={values.title} onChange={event=>edit("title",event.target.value)}/></label>
        <label>作者<select required value={values.author_id} onChange={event=>edit("author_id",event.target.value)}><option value="">请选择</option>{api.data?.authors.map(row=><option key={row.id} value={row.id}>{row.label}</option>)}</select></label><label>观察日期<input required type="date" value={values.observed_at} onChange={event=>edit("observed_at",event.target.value)}/></label>
        <label>发布日期<input required type="date" value={values.published_at} onChange={event=>edit("published_at",event.target.value)}/></label><label>有效期限<input type="date" min={values.published_at||undefined} value={values.valid_until} onChange={event=>edit("valid_until",event.target.value)}/></label>
        <label>可见范围<select required value={values.visibility} onChange={event=>edit("visibility",event.target.value)}><option value="">请选择</option>{api.data?.visibility_options.map(row=><option key={row.id} value={row.id}>{row.label}</option>)}</select></label>
      </div>
      <div className="boss-actions"><input ref={fileInput} type="file" accept=".txt,.md,.pdf,.docx" hidden disabled={busy} onChange={event=>{const file=event.target.files?.[0];if(file)readFile(file);event.target.value="";}}/><button type="button" className="boss-btn" disabled={busy||!api.data} onClick={()=>fileInput.current?.click()}>选择文件</button>{upload?<span>{upload.name} · {upload.size.toLocaleString()} 字节 · {formatLabel(upload.name)||"格式未识别"}<button type="button" className="boss-btn" onClick={()=>{setUpload(null);setDirty(true);onDirtyChange(true);}}>移除所选文件</button></span>:<span>尚未选择文件；选择文件只形成待提交内容。</span>}</div>
      <label className="boss-field">直接录入获准文本<textarea rows={6} disabled={!!upload} value={text} onChange={event=>{setText(event.target.value);setDirty(true);onDirtyChange(true);}}/></label><label className="boss-field">变更说明<textarea required rows={3} value={values.change_note} onChange={event=>edit("change_note",event.target.value)}/></label></fieldset>
      {formMode==="revise"&&!selectedSource?.editable&&<p className="boss-status boss-status-warn" role="status">所选来源不属于维护端录入的模拟资料，或已撤销，不能提交新版本。</p>}
      <p className="boss-v7-note">所选版本：{formMode==="revise"?`v${selectedSource?.version??"未知"}，提交后生成新版本并保留历史版本`:"新建来源，提交后生成 v1"} · 可见范围：{values.visibility?visibilityLabel(values.visibility):"尚未选择"} · 提交后显示任务编号</p>
      <div className="boss-actions"><button type="submit" className="boss-btn boss-btn-primary" disabled={!canSubmit}>开始摄取所选资料</button><button type="button" className="boss-btn" disabled={busy} onClick={cancelEdit}>取消本次编辑</button></div>
      {submitReason&&<p className="boss-v7-note">{submitReason}</p>}
    </form>:<>
      <div className="boss-knowledge-metadata"><V7Fact label="作者">{api.data?.authors.find(row=>row.id===selectedSource?.author_id)?.label??selectedSource?.author_id??"尚未选择"}</V7Fact><V7Fact label="观察日期">{selectedSource?.observed_at||"尚未选择"}</V7Fact><V7Fact label="发布日期">{selectedSource?.published_at||"尚未选择"}</V7Fact><V7Fact label="有效期限">{selectedSource?selectedSource.valid_until??"未设置期限":"尚未选择"}</V7Fact><V7Fact label="可见范围">{selectedSource?visibilityLabel(selectedSource.visibility):"尚未选择"}</V7Fact></div>
      <div className="boss-v7-table-scroll"><table className="boss-v7-table"><thead><tr><th>资料</th><th>作者与日期</th><th>有效期</th><th>可见范围</th><th>索引状态</th></tr></thead><tbody>{records.slice((currentPage-1)*10,currentPage*10).map(row=><tr key={row.id} aria-selected={row.id===selected}><td><button className="boss-v7-text-button" disabled={dirty||busy} onClick={()=>choose(row)}>{row.title||row.id} · v{row.version}</button><small>{row.file_name?`${row.file_name} · ${formatLabel(row.file_name)||"格式未记录"}`:"原文件未记录"}</small></td><td>{api.data?.authors.find(author=>author.id===row.author_id)?.label??row.author_id}<small>发布 {row.published_at||"未记录"} · 观察 {row.observed_at||"未记录"}</small></td><td>{row.valid_until??"未设置期限"}</td><td>{visibilityLabel(row.visibility)}</td><td>{row.index_state}<small>{availability(row)}</small></td></tr>)}</tbody></table></div>{!records.length&&<V7Empty title={tab==="pending"?"当前没有待摄取资料":tab==="withdrawn"?"当前没有已撤销资料":"当前条件下没有来源记录"}>{tab==="pending"?"只有目录或尚未完成索引的来源会出现在这里；进入本页签不会自动开始摄取。":undefined}</V7Empty>}{tab==="pending"&&<p className="boss-v7-note">待摄取资料指只有目录或尚未完成索引的来源；现有服务通过“添加来源资料”或“添加新版本”提交完整内容后执行解析索引，没有对已有目录资料单独提交摄取的接口。</p>}{(dirty||busy)&&<p className="boss-v7-note">资料正在编辑或正在读取，列表中的资料暂不能切换；请先保存或取消本次编辑。</p>}<V7Pagination total={records.length} page={currentPage} pageSize={10} onChange={setPage}/>
    </>}
    </V7Panel></div>
    <aside className="boss-column"><V7Panel title="检索检查"><form className="boss-v7-filter-bar" onSubmit={event=>{event.preventDefault();search();}}><label>检索内容<input ref={searchInput} required maxLength={500} value={query} onChange={event=>{clearSearch();setQuery(event.target.value);}}/></label><button className="boss-btn boss-btn-primary" disabled={!!searchReason}>{searching?"正在检索…":"执行检索检查"}</button></form>{searchReason&&<p className="boss-v7-note">{searchReason}</p>}
      <p className="boss-v7-note">使用当前资料的版本与权限执行检索，只读取现有索引，不重新摄取。</p>
      {searchError?<p className="boss-status boss-status-error" role="alert">检索检查失败：{searchError}。请按错误原因核查后重试；本次没有形成命中结论。</p>
      :hits===null?<V7Empty title="尚未执行检索">输入检索内容后点“执行检索检查”，结果显示命中文段、来源与原文位置。</V7Empty>
      :hits.length?<>{hits.map(hit=><article className="boss-workspace-item" key={hit.source_id+hit.version+hit.start}><strong>{hit.title} · v{hit.version}</strong><blockquote>{hit.excerpt}</blockquote><p>原文位置 {hit.start}—{hit.end}<small>{hit.source_id} · {hit.index_state}</small></p><button className="boss-btn" disabled={dirty||busy||!api.data?.sources.some(row=>row.id===hit.source_id)} onClick={()=>{const source=api.data?.sources.find(row=>row.id===hit.source_id);if(source){choose(source);setTab("catalog");}}}>查看来源资料</button></article>)}<p className="boss-v7-note">当前检索服务未返回相关度分数，命中文段按来源与原文位置列出。</p></>
      :<V7Empty title="本次检索没有命中">{unindexed?`另有${unindexed}份资料尚未摄取，不参与本次检索。`:""}检索服务未返回被权限或有效期过滤排除的来源数量，也没有返回未命中原因，请结合上方命中与索引状态核查。</V7Empty>}
      {dirty&&<p className="boss-v7-note">资料正在编辑，检索结果暂不能跳转到来源；请先保存或取消本次编辑。</p>}
    </V7Panel>
    <V7Panel title="来源与依据"><V7Fact label="当前来源">{selectedSource?.id??"尚未选择"}</V7Fact><V7Fact label="版本">{selectedSource?.version??"尚未保存"}</V7Fact><V7Fact label="可检索版本">{searchableVersion(selectedSource)}</V7Fact><V7Fact label="索引状态">{selectedSource?.index_state??"尚未读取"}</V7Fact><V7Fact label="解析状态">{selectedSource?"当前服务未返回解析状态":"尚未选择"}</V7Fact><V7Fact label="原文件">{selectedSource?selectedSource.file_name||"未记录":"尚未选择"}</V7Fact><V7Fact label="格式">{selectedSource?formatLabel(selectedSource.file_name)||"未记录":"尚未选择"}</V7Fact><V7Fact label="可见范围">{selectedSource?visibilityLabel(selectedSource.visibility):"尚未选择"}</V7Fact><V7Fact label="正文 SHA-256">{selectedSource?.content_sha256||"没有获准摘要"}</V7Fact><V7Fact label="读取权限">{selectedSource?.original_available?"仅获准的模拟来源":"仅目录元信息"}</V7Fact><V7Fact label="执行空间">{api.data?.namespace??"尚未读取"}</V7Fact><V7Fact label="读取时间">{api.data?.read_at??"尚未读取"}</V7Fact>{selectedSource?.error&&<p className="boss-status boss-status-error">{selectedSource.error}</p>}
      {selectedSource?<><p className="boss-v7-note">刷新摄取状态只读取当前资料的解析、索引与可检索结果，不会重新摄取，也不清除未保存编辑。</p><button className="boss-btn" disabled={busy} onClick={()=>api.reload()}>{api.loading?"刷新中…":"刷新摄取状态"}</button>{refreshReason&&<p className="boss-v7-note">{refreshReason}</p>}
        <details><summary>更多操作</summary>{selectedSource.withdrawn?<p>该资料已撤销，撤销操作已从当前资料操作区移除；历史版本保留。</p>:selectedSource.editable?<><p className="boss-v7-note">撤销前预览受影响索引、引用与后续检索；当前服务只提供版本与索引字段，引用清单需服务端返回。</p><button className="boss-btn" disabled={busy} onClick={()=>{setConfirmed(false);setAction("withdraw");}}>撤销此资料</button>{refreshReason&&<p className="boss-v7-note">{refreshReason}</p>}</>:<p>该来源不属于维护端录入的模拟资料，当前没有可执行的撤销操作。</p>}</details></>
      :<p className="boss-v7-note">选择一份资料后可刷新摄取状态；撤销操作在选中资料的更多操作中提供。</p>}
      <p className="boss-v7-note">解析状态与检索相关度分数需要服务端字段；当前页面显示索引状态与命中片段。</p></V7Panel></aside></div>
    <footer className="boss-knowledge-actions"><span>{selectedSource?`${selectedSource.title} · v${selectedSource.version}`:formMode?"正在新增资料":dirty?"资料正在编辑":"尚未选择来源"}</span>
      {!formMode&&(selectedSource?<><button className="boss-btn" disabled={!selectedSource.editable||dirty||busy} onClick={startRevise}>添加新版本</button>{(!selectedSource.editable||dirty||busy)&&<p className="boss-v7-note">{selectedSource.withdrawn?"所选资料已撤销，不能添加新版本。":!selectedSource.editable?"该来源不属于维护端录入的模拟资料，不能添加新版本。":dirty?"资料正在编辑，请先保存或取消本次编辑。":"正在读取或提交，请等待本次操作结束。"}</p>}</>:<p className="boss-v7-note">选择一份资料后可添加新版本、刷新摄取状态或撤销；新增资料使用左侧“添加来源资料”。</p>)}
    </footer>
    <Dialog.Root open={!!action} onOpenChange={open=>{if(!open)setAction(null);}}><Dialog.Portal><Dialog.Overlay className="boss-v7-dialog-overlay"/><Dialog.Content className="boss-v7-dialog"><Dialog.Title>{action==="withdraw"?"撤销资料":action==="revise"?"添加新版本并开始摄取":"添加来源资料并开始摄取"}</Dialog.Title><Dialog.Description>{action==="withdraw"?`资料 ${selectedSource?.title??(selected||values.source_id)} · v${selectedSource?.version??"未知"}，可见范围 ${selectedSource?visibilityLabel(selectedSource.visibility):"尚未选择"}。撤销后当前版本从检索索引移除，后续检索不再返回该来源原文；历史版本与审计保留。`:`来源 ${selected||values.source_id}，${action==="revise"?`当前版本 v${selectedSource?.version??"未知"}，提交后生成新版本并保留历史版本`:"新建来源，提交后生成 v1"}。服务端核查资料范围、版本与索引结果。`}</Dialog.Description>{action==="withdraw"&&<ul className="boss-v7-note"><li>受影响索引：当前 v{selectedSource?.version??"未知"}（{selectedSource?.index_state??"状态未知"}）从检索索引移除。</li><li>后续检索：撤销后不再返回该来源原文。</li><li>历史与引用：历史版本保留；受影响引用清单需要服务端字段，当前无法逐项列出。</li></ul>}<label className="boss-confirm-check"><input type="checkbox" checked={confirmed} onChange={event=>setConfirmed(event.target.checked)}/>{action==="withdraw"?"确认撤销该资料的当前版本及其检索索引":"确认当前模拟资料、来源与变更范围"}</label><div className="boss-actions"><Dialog.Close asChild><button className="boss-btn">取消</button></Dialog.Close><button className="boss-btn boss-btn-primary" disabled={!confirmed||busy} onClick={submit}>{action==="withdraw"?"确认撤销资料":"确认提交摄取"}</button></div></Dialog.Content></Dialog.Portal></Dialog.Root>
  </div>;
}
