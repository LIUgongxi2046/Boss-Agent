import {useEffect,useRef,useState} from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {FileSearch,Play,Square} from "lucide-react";
import {V7Empty,V7Fact,V7Metric,V7Pagination,V7Panel,V7ReadState,V7Tabs} from "./BossV7UI";
import {useTechnicalWorkspace} from "./useTechnicalWorkspace";

type Choice={id:string;title:string;version:string};
type Assertion={id:string;title:string;state:string;expected:unknown;observed:unknown;evidence_ids:string[];requirement_refs:string[]};
type Attempt={id:string;task_set_id:string;task_set_version:string;variant:string;dataset_snapshot_id:string;model_version:string;prompt_version:string;sop_version:string;
  namespace:string;state:string;started_at:string;finished_at:string|null;assertions:Assertion[];run_ids:string[];
  elapsed_seconds:number|null;known_cost:string|null;total_cost:string|null;currency:string|null;usage_coverage:string;failures:string[]};
type TaskSet=Choice&{input_summary:string;authorization_requirements:string[];assertion_definitions:{id:string;title:string;requirement_refs:string[]}[];
  pairing_conditions:string[];variant:string;scoring_access:string};
type Projection={projection:"evaluation";private_body_available_here:false;task_sets:TaskSet[];snapshots:Choice[];models:Choice[];prompts:Choice[];sops:Choice[];attempts:Attempt[];
  evidence:{id:string;attempt_id:string;kind:string;content:unknown}[];namespace:string;read_at:string;real_adoption_state:string};
type Selection={task_set_id:string;dataset_snapshot_id:string;model_version:string;prompt_version:string;sop_version:string};
type RecordFilter="all"|"failed"|"active";
type SavedView={selection:Selection;applied:Selection|null;variant:string;appliedVariant:string;selected:string;filter:RecordFilter;page:number};
type Confirmation={action:"start"|"reset"|"cancel";payload:Record<string,unknown>;context:string|null;attemptId:string|null;description:string};
const EMPTY:Selection={task_set_id:"",dataset_snapshot_id:"",model_version:"",prompt_version:"",sop_version:""};
const ACTIVE=["QUEUED","RUNNING","WAITING_INPUT"];
function failed(attempt:Attempt){return attempt.state==="FAILED"||attempt.failures.length>0||attempt.assertions.some(row=>row.state==="FAILED");}

export function MaintainerEvaluation({pageId,onNavigate,onDirtyChange,onOpenRun}:{pageId:"A16"|"F31";onNavigate:(page:string)=>void;onDirtyChange:(value:boolean)=>void;onOpenRun:(id:string)=>void}){
  const api=useTechnicalWorkspace<Projection>("evaluation");
  const saved=useRef<SavedView|undefined>(window.history.state?.bossEvaluation?.[pageId]);
  const [selection,setSelection]=useState<Selection>(saved.current?.selection??EMPTY);
  const [applied,setApplied]=useState<Selection|null>(saved.current?.applied??null);
  const [variant,setVariant]=useState(saved.current?.variant??""),[appliedVariant,setAppliedVariant]=useState(saved.current?.appliedVariant??"");
  const [selected,setSelected]=useState(saved.current?.selected??"");
  const [filter,setFilter]=useState<RecordFilter>(saved.current?.filter??"all");
  const [page,setPage]=useState(saved.current?.page??1);
  const [confirmation,setConfirmation]=useState<Confirmation|null>(null);
  const [confirmedContext,setConfirmedContext]=useState<string|null>(null);
  const [dirty,setDirty]=useState(false);
  const [evidenceId,setEvidenceId]=useState(""),[evidenceOpen,setEvidenceOpen]=useState(false);
  const recordsPanel=useRef<HTMLDivElement>(null),sourcePanel=useRef<HTMLDivElement>(null);
  const options=[
    ["task_set_id",pageId==="A16"?"评测任务集":"任务集",api.data?.task_sets],
    ["dataset_snapshot_id",pageId==="A16"?"数据快照":"数据版本",api.data?.snapshots],
    ["model_version",pageId==="A16"?"模型版本":"模型配置",api.data?.models],
    ["prompt_version","Prompt 版本",api.data?.prompts],["sop_version","SOP 版本",api.data?.sops],
  ] as const;
  const task=api.data?.task_sets.find(item=>item.id===selection.task_set_id);
  const resolved=options.map(([key,,choices])=>choices?.find(item=>item.id===selection[key]));
  const context=task&&task.assertion_definitions.length>0&&task.pairing_conditions.length>0&&task.scoring_access.trim()&&resolved.every(Boolean)?JSON.stringify({selection,versions:resolved.map(row=>row!.version),task}):null;
  const paired=context!==null&&confirmedContext===context;
  const ready=paired&&!!task;
  const busy=api.loading||api.busy||!!api.pending;
  const all=api.data?.attempts??[];
  const records=all.filter(item=>(filter==="all"||filter==="failed"&&failed(item)||filter==="active"&&ACTIVE.includes(item.state))
    &&(!applied||Object.entries(applied).every(([key,value])=>!value||item[key as keyof Selection]===value))
    &&(!appliedVariant||item.variant===appliedVariant));
  const attempt=all.find(item=>item.id===selected);
  const attemptEvidence=api.data?.evidence.filter(item=>item.attempt_id===selected)??[];
  const evidence=attemptEvidence.find(item=>item.id===evidenceId);
  const currentPage=Math.min(page,Math.max(1,Math.ceil(records.length/10)));
  const canCancel=!!attempt&&ACTIVE.includes(attempt.state);
  const confirmationCurrent=confirmation?.action==="cancel"?all.some(row=>row.id===confirmation.attemptId&&ACTIVE.includes(row.state)&&row.state===confirmation.payload.expected_state&&row.namespace===confirmation.payload.expected_namespace):!!confirmation&&confirmation.context===context&&ready;

  useEffect(()=>{onDirtyChange(dirty);},[dirty,onDirtyChange]);
  useEffect(()=>{if(!api.data)return;const state=window.history.state??{};window.history.replaceState({...state,bossEvaluation:{...state.bossEvaluation,[pageId]:{selection,applied,variant,appliedVariant,selected,filter,page:currentPage}}},"",window.location.href);},[api.data,pageId,selection,applied,variant,appliedVariant,selected,filter,currentPage]);
  function edit(key:keyof Selection,value:string){setSelection(current=>({...current,[key]:value}));setConfirmedContext(null);setDirty(true);}
  function inspect(region:"records"|"sources"){const target=region==="records"?recordsPanel.current:sourcePanel.current;target?.scrollIntoView({block:"start",behavior:"smooth"});target?.focus();}
  function selectAttempt(id:string){setSelected(id);setEvidenceId("");}
  function showEvidence(id=selected,reference=""){setSelected(id);setEvidenceId(reference||api.data?.evidence.find(row=>row.attempt_id===id)?.id||"");setEvidenceOpen(true);}
  function propose(action:Confirmation["action"]){
    if(busy)return;
    if(action==="cancel"){
      if(!attempt||!canCancel)return;
      setConfirmation({action,payload:{attempt_id:attempt.id,expected_state:attempt.state,expected_namespace:attempt.namespace},context:null,attemptId:attempt.id,description:`尝试 ${attempt.id}，执行空间 ${attempt.namespace}。仅取消尚未执行的项目，已开始的尝试及其结果继续保留。`});
      return;
    }
    if(!ready)return;
    setConfirmation({action,payload:{...selection,expected_versions:Object.fromEntries(options.map(([key],index)=>[key,resolved[index]!.version])),pairing_conditions_confirmed:true},context,attemptId:null,description:`任务集 ${task.id} · v${task.version}，数据快照 ${selection.dataset_snapshot_id}。使用独立执行空间，保留本次全部尝试和实际用量。`});
  }
  function execute(){if(!confirmation||!confirmationCurrent||busy)return;const request=confirmation;setConfirmation(null);void api.execute(request.action,request.payload).then(recorded=>{if(recorded&&request.action!=="cancel"){setDirty(false);setConfirmedContext(null);}});}
  function apply(){setApplied({...selection});setAppliedVariant(variant);setPage(1);}
  return <div className="boss-maintainer-records boss-evaluation-workspace">
    <V7ReadState loading={api.loading} error={api.error} onReload={api.reload}/>
    {api.pending&&<div className="boss-status boss-status-warn">原请求 {api.pending.request_id} 需要核查。<button className="boss-btn" disabled={api.busy} onClick={()=>void api.reconcile()}>核查回执</button></div>}
    {api.receipt&&<p className="boss-status" role="status">操作已记录 · {api.receipt.request_id}</p>}
    <form className="boss-v7-filter-bar boss-maintainer-filters" onSubmit={event=>{event.preventDefault();apply();}}>
      {options.map(([key,label,choices])=><label key={key}>{label}<select value={selection[key]} disabled={busy} onChange={event=>edit(key,event.target.value)}><option value="">请选择</option>{choices?.map(item=><option key={item.id} value={item.id}>{item.title} · v{item.version}</option>)}</select></label>)}
      <label>任务类型<select value={variant} onChange={event=>setVariant(event.target.value)}><option value="">全部任务类型</option>{[...new Set(api.data?.task_sets.map(row=>row.variant))].map(value=><option key={value}>{value}</option>)}</select></label><button className="boss-btn" disabled={busy}>查询评测记录</button>
      <button type="button" className="boss-btn" disabled={busy} onClick={()=>{setApplied(null);setAppliedVariant("");setFilter("all");setPage(1);}}>清除记录筛选</button>
    </form>
    <div className="boss-maintainer-columns"><div className="boss-column">
      <V7Panel title="评测任务与执行方法">
        {task?<><V7Fact label="当前配置任务">{task.title} · v{task.version}</V7Fact><V7Fact label="任务变体">{task.variant}</V7Fact><h3>输入与有效授权</h3><p>{task.input_summary}</p>{task.authorization_requirements.length?<ul>{task.authorization_requirements.map(row=><li key={row}>{row}</li>)}</ul>:<p>任务集没有提供授权要求。</p>}
          <h3>独立断言</h3>{task.assertion_definitions.length?task.assertion_definitions.map(row=><div key={row.id} className="boss-workspace-item"><strong>{row.id} · {row.title}</strong><small>{row.requirement_refs.join(" · ")}</small></div>):<p>尚未提供独立断言。</p>}
          <h3>人工配对条件</h3>{task.pairing_conditions.length?<ul>{task.pairing_conditions.map(row=><li key={row}>{row}</li>)}</ul>:<p>尚未提供人工配对条件。</p>}<label className="boss-confirm-check"><input type="checkbox" checked={paired} disabled={busy||!context} onChange={event=>{setConfirmedContext(event.target.checked?context:null);setDirty(true);}}/>已核查独立初始资料、运行顺序、熟悉程度与有效授权</label><V7Fact label="评分访问隔离">{task.scoring_access}</V7Fact>
        </>:<V7Empty title="请选择任务集">读取完整输入、授权要求、独立断言和人工配对条件。</V7Empty>}
        <h3>独立核查条件</h3><div className="boss-evaluation-checks"><V7Fact label="方法配置">{context?"所选版本在当前目录中可用":"等待完整版本选择"}</V7Fact><V7Fact label="人工配对核查">{paired?"已确认当前配置":"尚未确认当前配置"}</V7Fact><V7Fact label="全部尝试">{api.data?`${all.length} 条记录`:"尚未读取"}</V7Fact><V7Fact label="质量错误">{attempt?`${attempt.assertions.filter(row=>row.state==="FAILED").length} 项断言失败 · ${attempt.failures.length} 条失败记录`:"尚未选择尝试"}</V7Fact></div>
        {dirty&&<button className="boss-btn" disabled={busy} onClick={()=>{setSelection(saved.current?.selection??EMPTY);setConfirmedContext(null);setDirty(false);}}>取消本次配置修改</button>}
      </V7Panel>
      <div ref={recordsPanel} tabIndex={-1}><V7Panel title="全部尝试与失败证据">
        <V7Tabs label="评测记录筛选" value={filter} onChange={value=>{setFilter(value);setPage(1);}} items={[{id:"all",title:"全部尝试"},{id:"failed",title:"失败记录"},{id:"active",title:"进行中"}]}/>
        <p className="boss-v7-note">{applied||appliedVariant?"当前记录按已应用的版本与任务类型查询。":"当前显示全部版本；失败、取消及条件不足的记录保留。"}</p>
        {records.length?<div className="boss-v7-table-scroll"><table className="boss-v7-table"><thead><tr><th>任务集与时间</th><th>任务与版本</th><th>状态</th><th>断言结果</th><th>原始证据</th></tr></thead><tbody>{records.slice((currentPage-1)*10,currentPage*10).map(row=><tr key={row.id} aria-selected={selected===row.id}><td><button className="boss-v7-text-button" onClick={()=>selectAttempt(row.id)}>{api.data?.task_sets.find(item=>item.id===row.task_set_id)?.title??row.task_set_id}</button><small>{row.started_at}</small></td><td>{row.task_set_id} · v{row.task_set_version}<small>{row.dataset_snapshot_id}</small><small>{row.variant}</small></td><td>{row.state}</td><td>{row.assertions.filter(item=>item.state==="PASSED").length} 通过 / {row.assertions.filter(item=>item.state==="FAILED").length} 失败<small>{row.assertions.length} 项断言</small></td><td><button className="boss-btn" onClick={()=>showEvidence(row.id)}>查看本次证据</button></td></tr>)}</tbody></table></div>:<V7Empty title="当前范围没有评测尝试">尚未运行的评测没有评分与通过率。</V7Empty>}
        <V7Pagination page={currentPage} total={records.length} pageSize={10} onChange={setPage}/>
        {attempt&&<div className="boss-evaluation-results"><h3>独立核查结果 · {attempt.id}</h3><div className="boss-v7-metrics"><V7Metric label="实际耗时" value={attempt.elapsed_seconds===null?"未知":attempt.elapsed_seconds+" 秒"}/><V7Metric label="已知费用小计" value={attempt.known_cost===null?"未知":attempt.known_cost+" "+(attempt.currency??"币种未知")}/><V7Metric label="完整费用" value={attempt.total_cost===null?"未知":attempt.total_cost+" "+(attempt.currency??"币种未知")}/></div>
          {attempt.assertions.map(row=><article key={row.id} className="boss-workspace-item"><strong>{row.title} · {row.state}</strong><V7Fact label="G / H / M 与需求引用">{row.requirement_refs.join(" · ")}</V7Fact><details><summary>预期与实际观察</summary><pre className="boss-v7-code">{JSON.stringify({expected:row.expected,observed:row.observed},null,2)}</pre></details><div className="boss-actions">{row.evidence_ids.map(id=><button className="boss-btn" key={id} onClick={()=>showEvidence(attempt.id,id)}><FileSearch size={16}/>{id}</button>)}</div></article>)}
          {!attempt.assertions.length&&<p>本次尝试尚无独立断言结果。</p>}<h3>失败与质量错误</h3>{attempt.failures.length?attempt.failures.map((row,index)=><p key={index} className="boss-status boss-status-error">{row}</p>):<p>没有额外失败记录；逐项结果采用上方断言状态。</p>}
        </div>}
      </V7Panel></div>
    </div><aside className="boss-column"><div ref={sourcePanel} tabIndex={-1}><V7Panel title="来源与依据"><V7Fact label="选中尝试">{attempt?.id??"尚未选择"}</V7Fact><V7Fact label="任务集">{attempt?.task_set_id??"尚未选择"}</V7Fact><V7Fact label="数据快照">{attempt?.dataset_snapshot_id??"尚未选择"}</V7Fact><V7Fact label="模型版本">{attempt?.model_version??"尚未选择"}</V7Fact><V7Fact label="Prompt 版本">{attempt?.prompt_version??"尚未选择"}</V7Fact><V7Fact label="SOP 版本">{attempt?.sop_version??"尚未选择"}</V7Fact><V7Fact label="执行空间">{attempt?.namespace??api.data?.namespace??"尚未读取"}</V7Fact><V7Fact label="费用覆盖">{attempt?.usage_coverage??"尚未运行"}</V7Fact><V7Fact label="真实采用">{api.data?.real_adoption_state??"尚未读取"}</V7Fact><button className="boss-btn" onClick={()=>onNavigate("F32")}>查看评分依据</button></V7Panel></div>
      <V7Panel title="状态与核查"><V7Fact label="选中尝试状态">{attempt?.state??"未选择尝试"}</V7Fact><V7Fact label="开始时间">{attempt?.started_at??"尚未读取"}</V7Fact><V7Fact label="结束时间">{attempt?.finished_at??"尚未记录"}</V7Fact><V7Fact label="原始证据">{attempt?`${attemptEvidence.length} 项`:"尚未选择"}</V7Fact><V7Fact label="读取时间">{api.data?.read_at??"尚未读取"}</V7Fact><p>全部尝试与中途取消保留记录。质量错误逐项判定；未知效率和费用阈值保持待定。</p><div className="boss-actions">{attempt?.run_ids.map(id=><button className="boss-btn" key={id} onClick={()=>onOpenRun(id)}>查看运行 {id}</button>)}</div></V7Panel>
    </aside></div>
    <footer className="boss-maintainer-actions"><span>{task?`${task.title} · ${paired?"配对条件已确认":"配对条件待确认"}`:"评测任务待选择"}</span><button className="boss-btn boss-btn-primary" disabled={!ready||busy} onClick={()=>propose("start")}><Play size={16}/>{pageId==="F31"?"运行所选故事评测":"运行所选评测"}</button><button className="boss-btn" disabled={!ready||busy} onClick={()=>propose("reset")}>重置此评测空间</button><button className="boss-btn" disabled={busy||!canCancel} onClick={()=>propose("cancel")}><Square size={16}/>取消未执行项</button>{pageId==="A16"&&<button className="boss-btn" onClick={()=>inspect("sources")}>查看断言与证据来源</button>}<button className="boss-btn" disabled={busy} onClick={api.reload}>刷新评测记录</button></footer>
    <Dialog.Root open={!!confirmation} onOpenChange={open=>{if(!open)setConfirmation(null);}}><Dialog.Portal><Dialog.Overlay className="boss-v7-dialog-overlay"/><Dialog.Content className="boss-v7-dialog"><Dialog.Title>{confirmation?.action==="cancel"?"取消未执行评测项":confirmation?.action==="reset"?"独立重置并运行评测":"开始当前评测"}</Dialog.Title><Dialog.Description>{confirmation?.description}</Dialog.Description>{!confirmationCurrent&&<p role="alert">当前配置、配对条件或尝试状态已经变化，请重新核查。</p>}<div className="boss-actions"><Dialog.Close asChild><button className="boss-btn">取消操作</button></Dialog.Close><button className="boss-btn boss-btn-primary" disabled={busy||!confirmationCurrent} onClick={execute}>确认操作</button></div></Dialog.Content></Dialog.Portal></Dialog.Root>
    <Dialog.Root open={evidenceOpen} onOpenChange={setEvidenceOpen}><Dialog.Portal><Dialog.Overlay className="boss-v7-dialog-overlay"/><Dialog.Content className="boss-v7-dialog boss-evaluation-evidence"><Dialog.Title>原始证据</Dialog.Title><Dialog.Description>尝试 {selected} · 仅显示当前身份获准读取的评测证据。</Dialog.Description><label className="boss-field">证据记录<select value={evidenceId} onChange={event=>setEvidenceId(event.target.value)}><option value="">请选择证据</option>{attemptEvidence.map(row=><option key={row.id} value={row.id}>{row.id} · {row.kind}</option>)}</select></label>{evidence?<pre className="boss-v7-code">{JSON.stringify(evidence.content,null,2)}</pre>:<V7Empty title={evidenceId?"当前身份无法读取此证据":"本次尝试尚未选择证据"}/>}<div className="boss-actions"><Dialog.Close asChild><button className="boss-btn">关闭证据</button></Dialog.Close></div></Dialog.Content></Dialog.Portal></Dialog.Root>
  </div>;
}
