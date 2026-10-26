import {useCallback,useEffect,useRef,useState} from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {V7Empty,V7Fact,V7Panel,V7Pagination,V7ReadState} from "./BossV7UI";
import {useTechnicalWorkspace} from "./useTechnicalWorkspace";
import type {DatasetProjection} from "./MaintainerDatasets";
import type {AuditProjection} from "./MaintainerAudit";
import {MaintainerSimulationInspect,type SimulationObservation} from "./MaintainerSimulationInspect";

type RuntimeProjection={projection:"local-system";private_body_available_here:false;namespace:string;read_at:string;service:{state:string;active_runs:number;scheduler_state:string;scheduler_owner:string}};
type Entry={id:string;component:string;action:string;at:string;state:string;request:string|null;objects:string[];runIds:string[];details:unknown;observation?:SimulationObservation};
type Filter="all"|"data"|"relations"|"events"|"manual";
const DATA_ACTIONS=["boss.technical.datasets.generate","boss.technical.datasets.validate","boss.technical.datasets.inspect-reset"];
function category(action:string):Filter{return action==="boss.technical.datasets.validate"?"relations":DATA_ACTIONS.includes(action)||action==="boss.simulation.bi_scenario.load"?"data":"events";}

export function MaintainerSimulationCenter({onNavigate,onOpenRun}:{onNavigate:(page:string)=>void;onOpenRun:(id:string)=>void}){
  const datasets=useTechnicalWorkspace<DatasetProjection>("datasets"),audit=useTechnicalWorkspace<AuditProjection>("audit"),runtime=useTechnicalWorkspace<RuntimeProjection>("local-system");
  const [manualOpen,setManualOpen]=useState(false),[observations,setObservations]=useState<SimulationObservation[]>([]);
  const [selected,setSelected]=useState(""),[filter,setFilter]=useState<Filter>("all"),[page,setPage]=useState(1);
  const [detailsOpen,setDetailsOpen]=useState(false);
  const recordsPanel=useRef<HTMLDivElement>(null);
  const current=datasets.data?.current;
  const loaded=current?datasets.data?.datasets.find(row=>row.id===current.dataset_id&&row.version===current.version):undefined;
  const auditMatches=!!current&&audit.data?.namespace===current.namespace;
  const runtimeMatches=!!current&&runtime.data?.namespace===current.namespace;
  const calls=observations.filter(row=>row.namespace===current?.namespace);
  const auditRows=auditMatches?audit.data!.records.filter(row=>row.action.startsWith("boss.simulation.")||DATA_ACTIONS.includes(row.action)):[];
  const events=auditRows.filter(row=>category(row.action)==="events");
  const entries:Entry[]=[
    ...auditRows.map(row=>({id:"audit:"+row.id,component:category(row.action),action:row.action,at:row.executed_at??row.created_at,state:row.state,request:row.request_id,objects:row.result_refs.map(item=>item.id),runIds:[...new Set([...(row.run_id?[row.run_id]:[]),...row.result_refs.filter(item=>item.type==="runtime_run").map(item=>item.id)])],details:row})),
    ...(datasets.data?.transitions.filter(row=>row.namespace===current?.namespace||row.previous_namespace===current?.namespace)??[]).map(row=>({id:"transition:"+row.request_id,component:"data",action:row.action==="reset"?"重置执行空间":"载入数据集",at:row.requested_at,state:row.state,request:row.request_id,objects:[row.dataset_id,row.namespace],runIds:[],details:row})),
    ...calls.map(row=>({id:"manual:"+row.id,component:"manual",action:row.result?.interface_id??"接口人工检查",at:row.at,state:row.error?"FAILED":"RESPONSE_RECEIVED",request:row.request,objects:row.result?.records.map(item=>item.object_id)??[],runIds:[],details:row.result??{error:row.error,request:row.request},observation:row})),
  ].sort((a,b)=>b.at.localeCompare(a.at));
  const records=entries.filter(row=>filter==="all"||row.component===filter),entry=entries.find(row=>row.id===selected);
  const currentPage=Math.min(page,Math.max(1,Math.ceil(records.length/10)));
  const latestCall=calls.at(-1);
  const busy=datasets.loading||datasets.busy||!!datasets.pending;
  const labels:Record<string,string>={data:"数据生成",relations:"关系检查",events:"事件与回复",manual:"人工调用"};
  const receive=useCallback((row:SimulationObservation)=>{setObservations(previous=>[...previous,row]);setSelected("manual:"+row.id);},[]);
  useEffect(()=>{setManualOpen(false);setSelected("");setPage(1);},[current?.namespace]);
  function refresh(){datasets.reload();audit.reload();runtime.reload();}
  function open(pageId:string,section?:string){const url=new URL(window.location.href);if(section)url.searchParams.set("bossSimulationSection",section);else url.searchParams.delete("bossSimulationSection");window.history.replaceState(window.history.state,"",url);onNavigate(pageId);}
  function inspect(value:Filter){setFilter(value);setPage(1);recordsPanel.current?.scrollIntoView({block:"start",behavior:"smooth"});recordsPanel.current?.focus();}
  const controls=<><button className="boss-btn boss-btn-primary" onClick={()=>open("A03","generate")}>生成或载入</button><button className="boss-btn" disabled={!current||busy} onClick={()=>setManualOpen(true)}>人工调用</button><button className="boss-btn" onClick={()=>open("A04","event")}>注入事件</button><button className="boss-btn" onClick={()=>open("A04","clock")}>推进时钟</button><button className="boss-btn" disabled={!current||busy} onClick={()=>open("A03","reset")}>重置</button></>;
  return <div className="boss-maintainer-records boss-simulation-center">
    <V7ReadState loading={datasets.loading} error={datasets.error} onReload={datasets.reload}/>
    <div className="boss-simulation-summary"><V7Fact label="数据集与版本">{current?`${current.dataset_id} · v${current.version}`:"尚未读取"}</V7Fact><V7Fact label="seed（随机种子）">{loaded?.seed??"当前数据集没有生成器记录"}</V7Fact><V7Fact label="业务时钟">{current?.business_clock??"尚未读取"}</V7Fact><V7Fact label="execution_namespace">{current?.namespace??"尚未读取"}</V7Fact></div>
    <p className="boss-status"><span className="boss-tag boss-tag-amber">SIMULATED</span> 当前资料采用独立执行空间。历史空间保持原归属，不能作为当前业务依据。<button className="boss-btn" onClick={()=>open("A03","history")}>查看历史空间</button></p>
    <div className="boss-maintainer-columns"><div className="boss-column">
      <V7Panel title="模拟运行与可观测信息" action={<span className="boss-tag boss-tag-amber">SIMULATED</span>}>
        <div className="boss-simulation-regions">
          <article><h3>数据生成</h3><p>{loaded?`${loaded.id} · v${loaded.version} · ${loaded.state}`:current?"当前资料来自已有数据集，尚无对应生成记录。":"尚未读取当前数据集。"}</p>{loaded&&<p>{loaded.period_start} — {loaded.period_end}<br/>生成器 {loaded.generator_version}</p>}<button className="boss-btn" onClick={()=>open("A03","generate")}>配置数据生成</button></article>
          <article><h3>关系检查</h3><p>{loaded?.validated_at?`实际检查时间：${loaded.validated_at}`:"尚无当前数据集的关系检查时间。"}</p>{loaded?.checks.length?<ul>{loaded.checks.map(row=><li key={row.name}>{row.name} · {row.state}</li>)}</ul>:<p>尚无已记录检查结果。</p>}<button className="boss-btn" onClick={()=>open("A03","checks")}>查看关系检查</button></article>
          <article><h3>事件与回复</h3><p>{auditMatches?`当前空间已记录 ${events.length} 项模拟操作。`:"模拟事件记录尚未读取。"}</p><div className="boss-actions"><button className="boss-btn" onClick={()=>inspect("events")}>查看操作记录</button><button className="boss-btn" onClick={()=>open("A04","feedback")}>提供模拟回复</button></div></article>
          <article><h3>人工调用</h3><p>{latestCall?`${latestCall.result?.interface_id??"接口检查"} · ${latestCall.error?"请求失败":"已收到实际响应"}`:"本页面尚未进行人工调用。"}</p><p>SI01—SI14 接口目录，当前技术入口提供获准元信息。</p><button className="boss-btn" disabled={!current||busy} onClick={()=>setManualOpen(true)}>打开人工检查</button></article>
        </div>
        <div ref={recordsPanel} tabIndex={-1}><div className="boss-v7-filter-bar"><label>记录范围<select value={filter} onChange={event=>{setFilter(event.target.value as Filter);setPage(1);}}><option value="all">全部记录</option>{Object.entries(labels).map(([id,label])=><option key={id} value={id}>{label}</option>)}</select></label><button className="boss-btn" disabled={busy||audit.loading||runtime.loading} onClick={refresh}>重新读取</button></div>
          <V7ReadState loading={audit.loading} error={audit.error} onReload={audit.reload}/>{audit.data&&current&&!auditMatches&&<p role="alert" className="boss-status boss-status-warn">审计记录与当前执行空间不一致，请重新读取。</p>}
          <div className="boss-v7-table-scroll"><table className="boss-v7-table"><thead><tr><th>组件</th><th>请求或事件</th><th>执行时间</th><th>结果状态</th><th>详情</th></tr></thead><tbody>{records.slice((currentPage-1)*10,currentPage*10).map(row=><tr key={row.id} aria-selected={row.id===selected}><td>{labels[row.component]}</td><td><button className="boss-v7-text-button" onClick={()=>setSelected(row.id)}>{row.action}</button><small>{row.request??"没有已记录请求编号"}</small></td><td>{row.at}</td><td>{row.state}</td><td><button className="boss-btn" onClick={()=>{setSelected(row.id);setDetailsOpen(true);}}>查看详情</button></td></tr>)}</tbody></table></div>{!records.length&&<V7Empty title="当前范围没有已读取记录"/>}<V7Pagination page={currentPage} total={records.length} pageSize={10} onChange={setPage}/>
        </div>
      </V7Panel>
      <V7Panel title="允许的模拟操作"><div className="boss-actions">{controls}</div><p>重置前需要核查当前空间的影响范围，确认后保留旧空间历史。技术维护不能代替老板授权或确认任务完成。</p></V7Panel>
    </div><aside className="boss-column"><V7Panel title="来源与依据"><V7Fact label="资料属性">SIMULATED</V7Fact><V7Fact label="当前操作">{entry?.action??"尚未选择"}</V7Fact><V7Fact label="请求与响应">{entry?entry.observation?entry.observation.error?"请求失败":"已收到响应":"正式操作记录":"尚未选择记录"}</V7Fact><V7Fact label="原请求">{entry?.request??"尚未选择"}</V7Fact><V7Fact label={entry?.observation?"响应对象":"保存对象引用"}>{entry?entry.objects.join("、")||"没有对象引用":"尚未选择"}</V7Fact><V7Fact label="模型运行关联">{entry?entry.runIds.join("、")||"没有已记录关联":"尚未选择"}</V7Fact>{entry?.observation&&<V7Fact label="实际请求耗时">{entry.observation.elapsed_ms.toFixed(1)} ms</V7Fact>}{entry&&<button className="boss-btn" onClick={()=>setDetailsOpen(true)}>查看实际记录</button>}<div className="boss-actions">{entry?.runIds.map(id=><button className="boss-btn" key={id} onClick={()=>onOpenRun(id)}>查看运行 {id}</button>)}</div></V7Panel>
      <V7Panel title="状态与核查"><V7ReadState loading={runtime.loading} error={runtime.error} onReload={runtime.reload}/>{runtime.data&&current&&!runtimeMatches&&<p className="boss-status boss-status-warn">运行状态与当前执行空间不一致，请重新读取。</p>}<V7Fact label="当前在途运行">{runtimeMatches?runtime.data!.service.active_runs:"尚未取得当前空间状态"}</V7Fact><V7Fact label="调度状态">{runtimeMatches?runtime.data!.service.scheduler_state:"尚未读取"}</V7Fact><V7Fact label="当前载入版本">{current?.version??"尚未读取"}</V7Fact><V7Fact label="当前数据状态">{loaded?.state??"没有对应生成记录"}</V7Fact><V7Fact label="历史执行空间">{datasets.data?`${datasets.data.history.length} 项`:"尚未读取"}</V7Fact><V7Fact label="数据读取时间">{datasets.data?.read_at??"尚未读取"}</V7Fact><V7Fact label="运行读取时间">{runtimeMatches?runtime.data!.read_at:"尚未读取"}</V7Fact><button className="boss-btn" onClick={()=>onNavigate("A15")}>查看实际运行记录</button></V7Panel>
    </aside></div>
    <footer className="boss-maintainer-actions"><span>模拟资料与本人授权分别管理</span>{controls}</footer>
    <Dialog.Root open={manualOpen} onOpenChange={setManualOpen}><Dialog.Portal><Dialog.Overlay className="boss-v7-dialog-overlay"/><Dialog.Content className="boss-v7-dialog boss-simulation-dialog"><Dialog.Title>模拟接口人工调用</Dialog.Title><Dialog.Description>当前数据集 {current?.dataset_id} · v{current?.version}，执行空间 {current?.namespace}。仅查询获准技术元信息。</Dialog.Description>{current&&<MaintainerSimulationInspect expectedContext={{namespace:current.namespace,datasetId:current.dataset_id,version:current.version}} onObservation={receive} onOpenTools={()=>{setManualOpen(false);onNavigate("A09");}}/>}<div className="boss-actions"><Dialog.Close asChild><button className="boss-btn">关闭人工检查</button></Dialog.Close></div></Dialog.Content></Dialog.Portal></Dialog.Root>
    <Dialog.Root open={detailsOpen} onOpenChange={setDetailsOpen}><Dialog.Portal><Dialog.Overlay className="boss-v7-dialog-overlay"/><Dialog.Content className="boss-v7-dialog boss-simulation-detail"><Dialog.Title>实际请求与操作记录</Dialog.Title><Dialog.Description>{entry?`${entry.action} · ${entry.at}`:"当前执行空间未找到所选记录。"}</Dialog.Description>{entry?<pre className="boss-v7-code">{JSON.stringify(entry.details,null,2)}</pre>:<V7Empty title="没有可读取的当前记录"/>}<div className="boss-actions"><Dialog.Close asChild><button className="boss-btn">关闭记录</button></Dialog.Close></div></Dialog.Content></Dialog.Portal></Dialog.Root>
  </div>;
}
