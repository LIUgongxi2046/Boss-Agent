import {useEffect,useRef,useState} from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {useClient} from "@/providers/ClientProvider";
import {V7Empty,V7Fact,V7Panel,V7Pagination,V7ReadState} from "./BossV7UI";
import {useTechnicalWorkspace} from "./useTechnicalWorkspace";

type Source={id:string;title:string;author_id:string;observed_at:string;published_at:string;valid_until:string|null;visibility:string;version:string;index_state:string;withdrawn:boolean;editable:boolean;source_type:"SIMULATED";file_name:string;content_sha256:string;original_available:boolean;error:string|null};
type Projection={projection:"knowledge";private_body_available_here:false;sources:Source[];authors:{id:string;label:string}[];visibility_options:{id:string;label:string}[];namespace:string;read_at:string};
type Upload={name:string;mime_type:string;size:number;content_base64:string};
type Hit={source_id:string;version:string;title:string;excerpt:string;start:number;end:number;index_state:string};
const EMPTY={source_id:"",title:"",author_id:"",observed_at:"",published_at:"",valid_until:"",visibility:"",change_note:""};

export function MaintainerKnowledgeWorkspace({onDirtyChange,onNavigate}:{onDirtyChange:(dirty:boolean)=>void;onNavigate:(page:string)=>void}){
  const api=useTechnicalWorkspace<Projection>("knowledge");
  const {getToken}=useClient();
  const [tab,setTab]=useState<"catalog"|"ingestion"|"retrieval"|"withdrawn">("catalog");
  const [selected,setSelected]=useState("");
  const [values,setValues]=useState(EMPTY),[upload,setUpload]=useState<Upload|null>(null),[text,setText]=useState("");
  const [dirty,setDirty]=useState(false),[reading,setReading]=useState(false);
  const [query,setQuery]=useState(""),[hits,setHits]=useState<Hit[]|null>(null),[searching,setSearching]=useState(false);
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
  const records=(api.data?.sources??[]).filter(row=>(tab!=="withdrawn"||row.withdrawn)
    &&(!filters.document||[row.title,row.id,row.file_name].some(value=>value.toLocaleLowerCase().includes(filters.document.toLocaleLowerCase())))
    &&(!filters.source||row.author_id===filters.source)&&(!filters.version||row.version===filters.version)
    &&(!filters.validUntil||!!row.valid_until&&row.valid_until<=filters.validUntil)&&(!filters.index||row.index_state===filters.index));
  const currentPage=Math.min(page,Math.max(1,Math.ceil(records.length/10)));
  const busy=api.loading||api.busy||!!api.pending||reading;
  function filter(key:keyof typeof filters,value:string){setFilters(previous=>({...previous,[key]:value}));setPage(1);}
  function clearSearch(){searchSequence.current++;searchController.current?.abort();setSearching(false);setHits(null);}
  useEffect(()=>{clearSearch();},[api.data]);
  function sourceValues(source:Source){return{source_id:source.id,title:source.title,author_id:source.author_id,observed_at:source.observed_at,published_at:source.published_at,valid_until:source.valid_until??"",visibility:source.visibility,change_note:""};}
  function edit(key:keyof typeof values,value:string){setValues(old=>({...old,[key]:value}));setDirty(true);onDirtyChange(true);}
  function choose(source:Source){if(dirty||busy)return;setSelected(source.id);setValues(sourceValues(source));editingVersion.current=source.version;setUpload(null);setText("");setError("");}
  function newSource(){if(dirty||busy)return;setSelected("");setValues(EMPTY);editingVersion.current="0";setUpload(null);setText("");setError("");setTab("ingestion");}
  useEffect(()=>{if(!dirty&&selectedSource){setValues(sourceValues(selectedSource));editingVersion.current=selectedSource.version;}},[selectedSource,dirty]);
  function readFile(file:File){
    if(!file.size||file.size>20*1024*1024){setError("请选择包含内容且不超过20 MB的文件。");return;}
    setReading(true);setError("");const reader=new FileReader();fileReader.current=reader;
    reader.onload=()=>{const encoded=reader.result;if(typeof encoded!=="string")throw new Error("文件读取结果无效");setUpload({name:file.name,mime_type:file.type,size:file.size,content_base64:encoded.slice(encoded.indexOf(",")+1)});setText("");setReading(false);setDirty(true);onDirtyChange(true);setTab("ingestion");};
    reader.onerror=()=>{setError(reader.error?.message??"文件读取失败");setReading(false);};reader.readAsDataURL(file);
  }
  function search(){
    searchController.current?.abort();
    const controller=new AbortController();searchController.current=controller;
    const token=getToken();
    const sequence=++searchSequence.current;setSearching(true);setError("");
    void fetch("/api/boss/ui/admin/technical/knowledge/search?"+new URLSearchParams({query}),{headers:{Authorization:"Bearer "+token},cache:"no-store",signal:controller.signal}).then(async response=>{if(!response.ok)throw new Error("检索失败（HTTP "+response.status+"）");const result=await response.json() as {projection:string;hits:Hit[]};if(result.projection!=="knowledge-search")throw new Error("检索返回类型无效");if(sequence===searchSequence.current&&getToken()===token){setHits(result.hits);setSearching(false);}}).then(undefined,reason=>{if(sequence===searchSequence.current&&getToken()===token&&!controller.signal.aborted){setError(reason.message);setSearching(false);}});
  }
  function submit(){if(!action||!confirmed||busy)return;const sourceId=selected||values.source_id;void api.execute(action,{source_id:sourceId,expected_version:editingVersion.current,values,upload,text,confirmation:true}).then(saved=>{if(saved){setSelected(sourceId);setDirty(false);onDirtyChange(false);setUpload(null);setText("");clearSearch();setTab(action==="withdraw"?"withdrawn":"catalog");}});setAction(null);}
  function cancelEdit(){setValues(selectedSource?sourceValues(selectedSource):EMPTY);editingVersion.current=selectedSource?.version??"0";setUpload(null);setText("");setError("");setDirty(false);onDirtyChange(false);}
  function openSearch(){setTab("retrieval");searchInput.current?.scrollIntoView({block:"center",behavior:"smooth"});searchInput.current?.focus();}
  const tabs=[{id:"catalog",title:"文档目录",count:api.data?.sources.length},{id:"ingestion",title:"摄取资料"},{id:"retrieval",title:"检索命中",count:hits?.length},{id:"withdrawn",title:"撤销状态",count:api.data?.sources.filter(row=>row.withdrawn).length}] as const;
  return <div className="boss-knowledge-workspace"><V7ReadState loading={api.loading} error={api.error||error} onReload={dirty?undefined:api.reload}/>{api.pending&&<p className="boss-status boss-status-warn">摄取或版本操作等待核查。<button className="boss-btn" disabled={api.busy} onClick={()=>void api.reconcile()}>核查原请求</button></p>}
    {api.receipt&&<p className="boss-status boss-status-ok" role="status">操作已记录 · {api.receipt.request_id}</p>}
    <div className="boss-v7-filter-bar boss-knowledge-filters" role="search" aria-label="来源目录筛选">
      <label>文档<input type="search" value={filters.document} onChange={event=>filter("document",event.target.value)} placeholder="标题、标识或文件名称"/></label>
      <label>来源作者<select value={filters.source} onChange={event=>filter("source",event.target.value)}><option value="">全部作者</option>{api.data?.authors.map(row=><option key={row.id} value={row.id}>{row.label}</option>)}</select></label>
      <label>版本<input value={filters.version} onChange={event=>filter("version",event.target.value)} placeholder="全部版本"/></label>
      <label>有效期截止<input type="date" value={filters.validUntil} onChange={event=>filter("validUntil",event.target.value)}/></label>
      <label>索引状态<select value={filters.index} onChange={event=>filter("index",event.target.value)}><option value="">全部状态</option>{[...new Set(api.data?.sources.map(row=>row.index_state))].map(value=><option key={value}>{value}</option>)}</select></label>
      <button className="boss-btn" disabled={busy||dirty} onClick={api.reload}>重新读取</button>
    </div>
    <div className="boss-knowledge-columns"><aside className="boss-column"><V7Panel title="获准知识目录">
      <input ref={fileInput} type="file" accept=".txt,.md,.pdf,.docx" hidden disabled={busy} onChange={event=>{const file=event.target.files?.[0];if(file)readFile(file);event.target.value="";}}/>
      <button className="boss-btn boss-btn-primary" disabled={busy||!!selected&&!selectedSource?.editable} onClick={()=>fileInput.current?.click()}>上传获准资料</button>
      <nav className="boss-knowledge-directory" aria-label="知识资料视图">{tabs.map(item=><button className="boss-btn" key={item.id} aria-current={tab===item.id?"page":undefined} onClick={()=>{setTab(item.id);setPage(1);if(item.id==="retrieval")openSearch();}}><span>{item.title}</span>{"count" in item&&item.count!==undefined&&<small>{item.count} 条</small>}</button>)}</nav>
      <button className="boss-btn" disabled={dirty||busy} onClick={newSource}>新增来源资料</button>
      <p className="boss-v7-note">支持 TXT、Markdown、PDF、DOCX，最多20 MB。仅接收获准模拟资料。</p>
    </V7Panel></aside>
    <div className="boss-column"><V7Panel title="来源资料与版本">
    {tab==="ingestion"?<form id="boss-knowledge-editor" onSubmit={event=>{event.preventDefault();setConfirmed(false);setAction(selected?"revise":"ingest");}}><fieldset disabled={busy||!api.data||!!selected&&!selectedSource?.editable} className="boss-v7-form-fieldset"><div className="boss-form-grid">
      <label>来源标识<input required readOnly={!!selected} value={values.source_id} onChange={event=>edit("source_id",event.target.value)}/></label><label>资料标题<input required value={values.title} onChange={event=>edit("title",event.target.value)}/></label>
      <label>作者<select required value={values.author_id} onChange={event=>edit("author_id",event.target.value)}><option value="">请选择</option>{api.data?.authors.map(row=><option key={row.id} value={row.id}>{row.label}</option>)}</select></label><label>观察日期<input required type="date" value={values.observed_at} onChange={event=>edit("observed_at",event.target.value)}/></label>
      <label>发布日期<input required type="date" value={values.published_at} onChange={event=>edit("published_at",event.target.value)}/></label><label>有效期限<input type="date" min={values.published_at||undefined} value={values.valid_until} onChange={event=>edit("valid_until",event.target.value)}/></label>
      <label>可见范围<select required value={values.visibility} onChange={event=>edit("visibility",event.target.value)}><option value="">请选择</option>{api.data?.visibility_options.map(row=><option key={row.id} value={row.id}>{row.label}</option>)}</select></label><V7Fact label="当前文件">{upload?.name??"尚未上传"}</V7Fact>
    </div>{upload&&<div className="boss-actions"><span>{upload.name} · {upload.size.toLocaleString()} bytes</span><button type="button" className="boss-btn" onClick={()=>{setUpload(null);setDirty(true);onDirtyChange(true);}}>移除所选文件</button></div>}<label className="boss-field">直接录入获准文本<textarea rows={6} disabled={!!upload} value={text} onChange={event=>{setText(event.target.value);setDirty(true);onDirtyChange(true);}}/></label><label className="boss-field">变更说明<textarea required rows={3} value={values.change_note} onChange={event=>edit("change_note",event.target.value)}/></label></fieldset></form>:<>
      <div className="boss-knowledge-metadata"><V7Fact label="作者">{api.data?.authors.find(row=>row.id===selectedSource?.author_id)?.label??selectedSource?.author_id??"尚未选择"}</V7Fact><V7Fact label="观察日期">{selectedSource?.observed_at||"尚未选择"}</V7Fact><V7Fact label="发布日期">{selectedSource?.published_at||"尚未选择"}</V7Fact><V7Fact label="有效期限">{selectedSource?selectedSource.valid_until??"未设置期限":"尚未选择"}</V7Fact><V7Fact label="可见范围">{api.data?.visibility_options.find(row=>row.id===selectedSource?.visibility)?.label??selectedSource?.visibility??"尚未选择"}</V7Fact></div>
      <div className="boss-v7-table-scroll"><table className="boss-v7-table"><thead><tr><th>来源文件</th><th>作者与日期</th><th>版本</th><th>可见范围</th><th>索引状态</th></tr></thead><tbody>{records.slice((currentPage-1)*10,currentPage*10).map(row=><tr key={row.id} aria-selected={row.id===selected}><td><button className="boss-v7-text-button" disabled={dirty||busy} onClick={()=>choose(row)}>{row.title||row.id}</button><small>{row.file_name||row.id}</small></td><td>{api.data?.authors.find(author=>author.id===row.author_id)?.label??row.author_id}<small>{row.published_at}</small></td><td>{row.version}</td><td>{api.data?.visibility_options.find(option=>option.id===row.visibility)?.label??row.visibility}</td><td>{row.index_state}<small>{row.withdrawn?"已撤销":"当前资料"}</small></td></tr>)}</tbody></table></div>{!records.length&&<V7Empty title="当前条件下没有来源记录"/>}<V7Pagination total={records.length} page={currentPage} pageSize={10} onChange={setPage}/>
    </>}
    </V7Panel></div>
    <aside className="boss-column"><V7Panel title="检索检查"><form className="boss-v7-filter-bar" onSubmit={event=>{event.preventDefault();search();}}><label>检索内容<input ref={searchInput} required maxLength={500} value={query} onChange={event=>{clearSearch();setQuery(event.target.value);}}/></label><button className="boss-btn boss-btn-primary" disabled={searching||busy||!api.data}>{searching?"正在检索":"检索检查"}</button></form>{hits?.length?hits.map(hit=><article className="boss-workspace-item" key={hit.source_id+hit.version+hit.start}><strong>{hit.title} · v{hit.version}</strong><blockquote>{hit.excerpt}</blockquote><p>{hit.source_id} · 原文位置 {hit.start}—{hit.end} · {hit.index_state}</p><button className="boss-btn" disabled={dirty||busy||!api.data?.sources.some(row=>row.id===hit.source_id)} onClick={()=>{const source=api.data?.sources.find(row=>row.id===hit.source_id);if(source){choose(source);setTab("catalog");}}}>查看来源资料</button></article>):<V7Empty title={hits?"没有获准来源命中":"尚未执行检索"}>检索后显示实际命中片段及原文位置。</V7Empty>}</V7Panel>
    <V7Panel title="来源与依据"><V7Fact label="当前来源">{selectedSource?.id??"尚未选择"}</V7Fact><V7Fact label="版本">{selectedSource?.version??"尚未保存"}</V7Fact><V7Fact label="当前索引">{selectedSource?.index_state??"尚未摄取"}</V7Fact><V7Fact label="正文 SHA-256">{selectedSource?.content_sha256||"没有获准摘要"}</V7Fact><V7Fact label="读取权限">{selectedSource?.original_available?"仅获准的模拟来源":"仅目录元信息"}</V7Fact><V7Fact label="执行空间">{api.data?.namespace??"尚未读取"}</V7Fact><V7Fact label="读取时间">{api.data?.read_at??"尚未读取"}</V7Fact>{selectedSource?.error&&<p className="boss-status boss-status-error">{selectedSource.error}</p>}<button className="boss-btn" onClick={()=>onNavigate("A12")}>检查索引状态</button><p>资料修订和撤销影响后续检索；历史记录保留当时来源版本。</p></V7Panel></aside></div>
    <footer className="boss-knowledge-actions"><span>{selectedSource?`${selectedSource.title} · v${selectedSource.version}`:dirty?"资料正在编辑":"尚未选择来源"}</span>
      {tab==="ingestion"?<button type="submit" form="boss-knowledge-editor" className="boss-btn boss-btn-primary" disabled={busy||!dirty||!upload&&!text.trim()||!!selected&&!selectedSource?.editable}>{selected?"更新版本":"摄取资料"}</button>:<><button className="boss-btn boss-btn-primary" disabled={busy||dirty} onClick={newSource}>摄取资料</button><button className="boss-btn" disabled={!selectedSource?.editable||dirty||busy} onClick={()=>setTab("ingestion")}>更新版本</button></>}
      {dirty&&<button className="boss-btn" disabled={busy} onClick={cancelEdit}>取消本次编辑</button>}<button className="boss-btn" onClick={openSearch}>检索检查</button><button className="boss-btn" disabled={!selectedSource?.editable||selectedSource.withdrawn||dirty||busy} onClick={()=>{setConfirmed(false);setAction("withdraw");}}>撤销资料</button>
    </footer>
    <Dialog.Root open={!!action} onOpenChange={open=>{if(!open)setAction(null);}}><Dialog.Portal><Dialog.Overlay className="boss-v7-dialog-overlay"/><Dialog.Content className="boss-v7-dialog"><Dialog.Title>{action==="withdraw"?"撤销当前来源":action==="revise"?"更新来源版本":"摄取获准资料"}</Dialog.Title><Dialog.Description>来源 {selected||values.source_id}，当前版本 {selectedSource?.version??"尚未保存"}。服务端核查资料范围、版本与索引结果。</Dialog.Description><label className="boss-confirm-check"><input type="checkbox" checked={confirmed} onChange={event=>setConfirmed(event.target.checked)}/>确认当前模拟资料、来源与变更范围</label><div className="boss-actions"><Dialog.Close asChild><button className="boss-btn">取消</button></Dialog.Close><button className="boss-btn boss-btn-primary" disabled={!confirmed||busy} onClick={submit}>确认操作</button></div></Dialog.Content></Dialog.Portal></Dialog.Root>
  </div>;
}
