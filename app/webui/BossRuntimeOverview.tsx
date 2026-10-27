import {useEffect,useRef,useState} from "react";
import {Activity,Settings,Database,Clock3,ShieldCheck,ArrowUpRight,Search} from "lucide-react";
import {V7Panel,V7Fact,V7Empty,V7ReadState} from "./BossV7UI";
import {MaintainerRuntimeRecords,type RuntimeRecord} from "./MaintainerRuntimeRecords";
import type {LocalSystemProjection} from "./MaintainerLocalSystem";
import type {DatasetProjection} from "./MaintainerDatasets";
import {useTechnicalWorkspace} from "./useTechnicalWorkspace";

type Maintenance={scope:"MAINTAINER_METADATA_ONLY";configured_provider:string;configured_model:string;configuration_version:string;source_type:string;status:string;counts:Record<string,number>;read_at:string};
type Runs={projection:"runtime-records";source_type:"RUNTIME_RECORD";namespace:string;read_at:string;private_body_available_here:false;business_mutation_performed:false;runs:RuntimeRecord[];matched_count:number};
type Props={getToken:()=>string;identityKey:string;onNavigate:(id:string)=>void;onOpenRun:(id:string)=>void};
type SearchResult={projection:"knowledge-search";read_at:string;hits:{source_id:string;version:string;title:string;excerpt:string;start:number;end:number;index_state:string}[]};

export function BossRuntimeOverview({getToken,identityKey,onNavigate,onOpenRun}:Props){
  const local=useTechnicalWorkspace<LocalSystemProjection>("local-system");
  const datasets=useTechnicalWorkspace<DatasetProjection>("datasets");
  const [maintenance,setMaintenance]=useState<{identity:string;value:Maintenance}|null>(null);
  const [runs,setRuns]=useState<{identity:string;value:Runs}|null>(null);
  const [errors,setErrors]=useState({maintenance:"",runs:""});
  const [loading,setLoading]=useState({maintenance:true,runs:true});
  const [revision,setRevision]=useState(0);
  const [query,setQuery]=useState(""),[search,setSearch]=useState("");
  const [searchResult,setSearchResult]=useState<SearchResult|null>(null),[searchError,setSearchError]=useState(""),[searching,setSearching]=useState(false);
  const searchController=useRef<AbortController|null>(null);
  const config=maintenance?.identity===identityKey?maintenance.value:null;
  const records=runs?.identity===identityKey?runs.value:null;
  const current=datasets.data?.current;
  const localMatches=!!current&&local.data?.namespace===current.namespace;
  const runsMatch=!!current&&records?.namespace===current.namespace;
  useEffect(()=>{
    const abort=new AbortController();setMaintenance(null);setRuns(null);setErrors({maintenance:"",runs:""});setLoading({maintenance:true,runs:true});
    async function read<T>(url:string):Promise<T>{
      const response=await fetch(url,{headers:{Authorization:"Bearer "+getToken()},cache:"no-store",signal:abort.signal});
      if(response.status===401)window.dispatchEvent(new Event("boss-auth-expired"));
      if(!response.ok)throw new Error("读取失败（HTTP "+response.status+"）");
      return await response.json() as T;
    }
    void read<Maintenance>("/api/boss/ui/maintenance").then(value=>{
      if(value.scope!=="MAINTAINER_METADATA_ONLY")throw new Error("维护信息不符合当前访问范围");
      if(!abort.signal.aborted){setMaintenance({identity:identityKey,value});setLoading(state=>({...state,maintenance:false}));}
    }).then(undefined,error=>{if(!abort.signal.aborted){setErrors(state=>({...state,maintenance:error.message}));setLoading(state=>({...state,maintenance:false}));}});
    void read<Runs>("/api/boss/ui/runtime-records?limit=10").then(value=>{
      if(value.projection!=="runtime-records"||value.source_type!=="RUNTIME_RECORD"||value.private_body_available_here!==false||value.business_mutation_performed!==false)throw new Error("运行记录不符合当前来源与访问范围");
      if(!abort.signal.aborted){setRuns({identity:identityKey,value});setLoading(state=>({...state,runs:false}));}
    }).then(undefined,error=>{if(!abort.signal.aborted){setErrors(state=>({...state,runs:error.message}));setLoading(state=>({...state,runs:false}));}});
    return()=>abort.abort();
  },[getToken,identityKey,revision]);
  useEffect(()=>{setQuery("");setSearch("");setSearchResult(null);setSearchError("");setSearching(false);return()=>searchController.current?.abort();},[identityKey,current?.namespace]);
  function find(){
    if(!query.trim()||!current)return;
    searchController.current?.abort();const abort=new AbortController();searchController.current=abort;
    const token=getToken();setSearch(query.trim());setSearchResult(null);setSearchError("");setSearching(true);
    void fetch("/api/boss/ui/admin/technical/knowledge/search?"+new URLSearchParams({query:query.trim()}),{headers:{Authorization:"Bearer "+token},cache:"no-store",signal:abort.signal}).then(async response=>{
      if(response.status===401)window.dispatchEvent(new Event("boss-auth-expired"));
      if(!response.ok)throw new Error("获准资料检索失败（HTTP "+response.status+"）");
      const value=await response.json() as SearchResult;
      if(value.projection!=="knowledge-search")throw new Error("检索来源不符合当前要求");
      if(!abort.signal.aborted&&getToken()===token){setSearchResult(value);setSearching(false);}
    }).then(undefined,error=>{if(!abort.signal.aborted&&getToken()===token){setSearchError(error.message);setSearching(false);}});
  }
  function refresh(){local.reload();datasets.reload();setRevision(value=>value+1);}
  const domains=[{title:"服务概况",description:"本地环境、服务及恢复说明",page:"F32",Icon:Activity},{title:"配置采用",description:"模型、Provider和有效版本",page:"A08",Icon:Settings},{title:"数据空间",description:"当前数据集、来源和历史空间",page:"A03",Icon:Database},{title:"最近运行",description:"执行结果、用量与终止原因",page:"A15",Icon:Clock3},{title:"Tools与连接",description:"工具版本及接口参数",page:"A09",Icon:Settings},{title:"调度计划",description:"触发条件、去重与运行记录",page:"A13",Icon:Clock3},{title:"维护权限",description:"技术访问范围及本人权限边界",page:"A01",Icon:ShieldCheck},{title:"评测管理",description:"任务集、最近评测覆盖与失败",page:"A16",Icon:Activity}];
  const matches=domains.filter(item=>(item.title+item.description).toLocaleLowerCase().includes(search.toLocaleLowerCase()));
  const states=[
    {name:"本地服务",content:localMatches?local.data!.application_version:"尚未读取当前空间状态",state:localMatches?local.data!.service.state:"未检查",at:localMatches?local.data!.read_at:null,page:"F32"},
    {name:"配置读取",content:config?`${config.configured_provider} / ${config.configured_model} · v${config.configuration_version}`:"尚未读取",state:config?"配置已读取，实际采用按运行核查":"未检查",at:config?.read_at,page:"A08"},
    {name:"数据空间",content:current?`${current.dataset_id} · v${current.version}`:"尚未读取",state:current?"当前模拟空间":"未检查",at:datasets.data?.read_at,page:"A03"},
    {name:"调度责任",content:localMatches?local.data!.service.scheduler_owner:"尚未读取",state:localMatches?local.data!.service.scheduler_state:"未检查",at:localMatches?local.data!.read_at:null,page:"A13"},
    {name:"最近运行",content:runsMatch?`已读取 ${records!.runs.length} 项，共 ${records!.matched_count} 项`:"总数未知",state:runsMatch?"已读取获准记录":"未检查",at:runsMatch?records!.read_at:null,page:"A15"},
  ];
  const busy=local.loading||datasets.loading||loading.maintenance||loading.runs;
  return <div className="boss-maintainer-records boss-runtime-overview">
    <div className="boss-run-goal"><span>版本摘要</span><strong>{local.data?.application_version??"应用版本尚未读取"} · 上游 {local.data?.upstream_version??"尚未读取"}</strong><small>{current?current.dataset_id+" · v"+current.version:"数据集尚未读取"} · 检查时间 {localMatches?local.data!.read_at:"尚未检查"}</small><div className="boss-actions"><button className="boss-btn boss-btn-primary" disabled={busy} onClick={refresh}>检查运行状态</button></div></div>
    <V7ReadState loading={busy} error={local.error||datasets.error||errors.maintenance||errors.runs} onReload={refresh}/>
    {current&&((local.data&&!localMatches)||(records&&!runsMatch))&&<p role="alert" className="boss-status boss-status-warn">部分检查记录与当前执行空间不同，请重新读取。</p>}
    <div className="boss-maintainer-columns"><div className="boss-column">
      <V7Panel title="工作领域"><div className="boss-v7-domain-grid">{matches.map(({title,description,page,Icon})=><button key={page} onClick={()=>onNavigate(page)}><span className="boss-chat-file-icon"><Icon size={21}/></span><span><strong>{title}</strong><small>{description}</small></span><ArrowUpRight size={17}/></button>)}</div>{!matches.length&&<V7Empty title="没有匹配的维护内容"/>}</V7Panel>
      <V7Panel title="当前范围与状态"><div className="boss-v7-table-scroll"><table className="boss-v7-table"><thead><tr><th>模块</th><th>已读取资料</th><th>当前状态</th><th>更新时间</th><th>入口</th></tr></thead><tbody>{states.map(row=><tr key={row.name}><td>{row.name}</td><td>{row.content}</td><td>{row.state}</td><td>{row.at??"尚未检查"}</td><td><button className="boss-btn" onClick={()=>onNavigate(row.page)}>{row.name==="本地服务"?"查看本地服务":row.name==="配置读取"?"查看模型配置":row.name==="数据空间"?"查看数据集":row.name==="调度责任"?"查看调度状态":"查看运行记录"}</button></td></tr>)}</tbody></table></div></V7Panel>
      <V7Panel title="最近获准运行"><V7ReadState loading={loading.runs} error={errors.runs}/><div className="boss-v7-table-scroll"><table className="boss-v7-table"><thead><tr><th>运行编号</th><th>Provider / 模型</th><th>真实开始时间</th><th>状态与终止原因</th><th>入口</th></tr></thead><tbody>{runsMatch&&records!.runs.map(run=><tr key={run.run_id}><td>{run.run_id}</td><td>{run.runtime.provider}<small>{run.runtime.model_id}</small></td><td>{run.started_at}</td><td>{run.status}<small>{run.stop_reason??"尚无终止原因"}</small></td><td><button className="boss-btn" onClick={()=>onOpenRun(run.run_id)}>打开记录</button></td></tr>)}</tbody></table></div>{(!runsMatch||!records!.runs.length)&&<V7Empty title={runsMatch?"当前空间没有已记录运行":"最近运行尚未读取"}/>}<details className="boss-runtime-extra"><summary>按条件查询获准运行记录</summary><MaintainerRuntimeRecords getToken={getToken} identityKey={identityKey}/></details></V7Panel>
    </div><aside className="boss-column">
      <V7Panel title="智能检索"><form className="boss-overview-search" onSubmit={event=>{event.preventDefault();find();}}><label htmlFor="boss-overview-search">查找维护入口与当前获准资料</label><textarea id="boss-overview-search" required maxLength={500} rows={3} value={query} onChange={event=>{searchController.current?.abort();setSearching(false);setSearchResult(null);setSearchError("");setQuery(event.target.value);}} placeholder="输入业务主题、任务目标或资料内容"/><button className="boss-btn boss-btn-primary" type="submit" disabled={!current||searching}><Search size={16}/>{searching?"正在检索":"查找维护入口"}</button></form><V7ReadState loading={searching} error={searchError}/>{searching&&<button className="boss-btn" onClick={()=>{searchController.current?.abort();setSearching(false);}}>取消本次查询</button>}{search&&<p>检索内容：{search}<button className="boss-v7-text-button" onClick={()=>{searchController.current?.abort();setSearching(false);setSearch("");setQuery("");setSearchResult(null);setSearchError("");}}>清除检索</button></p>}{searchResult&&<><p className="boss-v7-note">获准资料读取于 {searchResult.read_at}</p>{searchResult.hits.length?searchResult.hits.map(hit=><article className="boss-workspace-item" key={hit.source_id+hit.version+hit.start}><strong>{hit.title} · v{hit.version}</strong><p>{hit.excerpt}</p><small>{hit.source_id} · 原文位置 {hit.start}—{hit.end} · {hit.index_state}</small></article>):<V7Empty title="当前获准资料没有匹配内容"/>}<button className="boss-btn" onClick={()=>onNavigate("A07")}>打开知识目录</button></>}</V7Panel>
      <V7Panel title="状态与核查"><V7Fact label="真实检查时间">{localMatches?local.data!.read_at:"尚未检查"}</V7Fact><V7Fact label="服务状态">{localMatches?local.data!.service.state:"未检查"}</V7Fact><V7Fact label="在途运行">{localMatches?local.data!.service.active_runs:"总数未知"}</V7Fact><V7Fact label="配置读取">{config?.status??"尚未读取"}</V7Fact><V7Fact label="实际采用">按具体运行记录核查</V7Fact><V7Fact label="费用总额">未知</V7Fact><V7Fact label="待处理错误">{errors.maintenance||errors.runs||local.error||datasets.error||"当前查询没有返回错误；全部业务错误另行查询"}</V7Fact><button className="boss-btn" onClick={()=>onNavigate("F30")}>查看运行与用量</button></V7Panel>
      <V7Panel title="维护权限边界"><ShieldCheck size={24} color="#005bac"/><p>当前身份管理技术配置、模拟资料和获准运行元信息。本人目标、私人正文和业务决定由本人管理。</p><div className="boss-actions"><button className="boss-btn" onClick={()=>onNavigate("A01")}>档案与访问</button><button className="boss-btn" onClick={()=>onNavigate("A14")}>授权记录</button></div></V7Panel>
      <V7Panel title="资料范围"><V7Fact label="当前执行空间">{current?.namespace??"尚未读取"}</V7Fact><V7Fact label="业务时钟">{current?.business_clock??"尚未读取"}</V7Fact>{config&&Object.entries(config.counts).map(([name,count])=><V7Fact key={name} label={name}>{count}</V7Fact>)}<button className="boss-btn" onClick={()=>onNavigate("F32")}>运行与恢复说明</button></V7Panel>
    </aside></div>
  </div>;
}
