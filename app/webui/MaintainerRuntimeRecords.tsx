import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from "react";
import { AlertCircle, ClipboardCopy, FileSearch, Loader2, RefreshCw, Square } from "lucide-react";
import {V7Empty,V7Panel,V7Tabs} from "./BossV7UI";

type Usage = {
  prompt_tokens?: number | null; completion_tokens?: number | null; total_tokens?: number | null;
  prompt_cache_hit_tokens?: number | null; prompt_cache_miss_tokens?: number | null;
};
type ModelRequest = {
  model_request_id: string; http_status?: number | null; response_ids: string[];
  finish_reasons: string[]; usage?: Usage | null; request_sha256?: string;
  tool_config_sha256?: string;
};
type ToolResult = {
  tool_id: string; tool_call_id: string; query_id?: string; task_id?: string;
  message_id?: string; version?: string; status?: string; task_version?: string; task_status?: string;
};
export type RuntimeRecord = {
  source_type?: "SIMULATED"; external_model_invoked?: false;
  owner_task_links?: {task_id:string;task_version:string;request_id:string;preparation_sha256:string;action:string}[];
  run_id: string; request_id: string; request_id_source: string; session_id: string;
  turn_id?: string | null; namespace: string; started_at: string; finished_at?: string | null;
  status: string; stop_reason?: string | null; termination_source?: string | null;
  dataset_id?: string | null; dataset_version?: string | null;
  configuration_id: string; configuration_version: string;
  runtime: { provider: string; model_id: string; api_type: string; timeout: number;
    max_tool_rounds: number; max_output_tokens: number; config_sha256: string };
  prompt_versions: { prompt_id: string; prompt_version: string; active_version: string;
    kind: string; content_sha256: string; source_refs: {source_id: string; version: string}[] }[];
  tool_config_sha256: string;
  tool_configuration: { tool_id: string; implementation: string;
    schema_sha256: string; implementation_sha256?: string }[];
  model_requests: ModelRequest[]; tool_results: ToolResult[]; usage: Usage | null;
  usage_coverage: string; model_attempts_coverage?: string; cost_total: string | null;
  price_version: string | null; model_completion_observed: boolean;
  model_behavior_evaluation_passed: boolean; private_body_recorded: false;
};
type Cursor = {cursor_started_at: string; cursor_run_id: string};
type Projection = {
  projection: "runtime-records"; source_type: "RUNTIME_RECORD"; namespace: string; read_at: string;
  runs: RuntimeRecord[]; matched_count: number; limit: number; next_cursor: Cursor | null;
  private_body_available_here: false; business_mutation_performed: false;
};
type Props = {getToken: () => string; identityKey:string; pageId?:"A15"|"F30"; onOpenTask?: (taskId: string, runId: string) => void; initialRunId?: string;
  onOpenRunDetails?: (runId: string) => void; onBackToList?: () => void};
type TaskReference = {
  projection: "runtime-task-reference"; source_type: "RUNTIME_RECORD"; task_source_type: "SIMULATED";
  namespace: string; run_id: string; dataset_id: string; dataset_version: string;
  task_id: string; task_version: string; task_status: string; read_at: string;
  private_body_available_here: false; business_mutation_performed: false;
};
type Filters = {provider: string; run_id: string; dataset_id: string; status: string;
  stop_reason: string; started_from: string; started_until: string; limit: string};
type SavedView = {filters: Filters; applied: string; selected: string; pageId:"A15"|"F30"};
const STATUSES = ["QUEUED", "RUNNING", "WAITING_INPUT", "SUCCEEDED", "FAILED", "CANCELED", "TIMED_OUT"];
const RANGE_DAYS = 7;
const TASK_PURPOSE: Record<string, string> = {
  "boss.supply_quality.coordinate": "经营供给协调",
  "boss.owner_workspace.runs.cancel": "取消运行",
  "boss.assignment.send": "交办发送",
  "boss.commitment.create": "本人承诺",
};
const shanghaiTime = new Intl.DateTimeFormat("en-CA", {timeZone: "Asia/Shanghai", year: "numeric",
  month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false});
const value = (item: ReactNode) => item === null || item === undefined || item === "" ? "未知" : item;
function localInput(date: Date): string {
  const parts = Object.fromEntries(shanghaiTime.formatToParts(date).map(part => [part.type, part.value]));
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour === "24" ? "00" : parts.hour}:${parts.minute}:${parts.second}`;
}
function defaultFilters(initialRunId?: string): Filters {
  const until = new Date();
  return {provider: "", run_id: initialRunId ?? "", dataset_id: "", status: "", stop_reason: "",
    started_from: initialRunId ? "" : localInput(new Date(until.getTime() - RANGE_DAYS * 86400000)),
    started_until: initialRunId ? "" : localInput(until), limit: "10"};
}
function filtersToParameters(filters: Filters): URLSearchParams {
  const parameters = new URLSearchParams();
  for (const [key, input] of Object.entries(filters)) {
    if (!input.trim()) continue;
    parameters.set(key, key.startsWith("started_") ? new Date(input + "+08:00").toISOString() : input.trim());
  }
  return parameters;
}
function rangeInvalid(filters: Filters): boolean {
  if (!filters.started_from || !filters.started_until) return false;
  return new Date(filters.started_from + "+08:00").getTime() > new Date(filters.started_until + "+08:00").getTime();
}
function appliedSummary(parameters: URLSearchParams | null): string {
  if (!parameters) return "尚未应用筛选";
  const parts: string[] = [];
  const from = parameters.get("started_from"), until = parameters.get("started_until");
  if (from || until) parts.push("开始时间 " + (from ? shanghaiTime.format(new Date(from)) : "不限")
    + " — " + (until ? shanghaiTime.format(new Date(until)) : "不限"));
  const labels: Record<string, string> = {provider: "Provider", run_id: "运行编号", dataset_id: "数据集",
    status: "运行状态", stop_reason: "错误类型或终止原因"};
  for (const [key, label] of Object.entries(labels)) {
    const input = parameters.get(key);
    if (input) parts.push(label + " " + input);
  }
  return parts.length ? parts.join(" · ") : "未限制条件";
}
function Detail({label, children}: {label: string; children?: ReactNode}) {
  return <div className="boss-kv"><span>{label}</span><strong>{value(children)}</strong></div>;
}
function UsageFields({usage}: {usage?: Usage | null}) {
  return <>
    <Detail label="输入 Token">{usage?.prompt_tokens}</Detail>
    <Detail label="输出 Token">{usage?.completion_tokens}</Detail>
    <Detail label="总 Token">{usage?.total_tokens}</Detail>
    <Detail label="缓存命中 Token">{usage?.prompt_cache_hit_tokens}</Detail>
    <Detail label="缓存未命中 Token">{usage?.prompt_cache_miss_tokens}</Detail>
  </>;
}
function runPurpose(record: RuntimeRecord): string {
  const action = record.owner_task_links?.[0]?.action;
  if (action) return TASK_PURPOSE[action] ?? action;
  if (record.dataset_id) return "数据集 " + record.dataset_id + " 的运行";
  return "运行的模型与工具记录";
}
function businessState(record: RuntimeRecord): string {
  if (record.owner_task_links?.length) return "关联任务 " + record.owner_task_links.length + " 项，业务结果按任务核查";
  return "本投影未判定业务结果";
}

export function MaintainerRuntimeRecords({getToken, identityKey, pageId="A15", onOpenTask, initialRunId, onOpenRunDetails, onBackToList}: Props) {
  const formId=useId();
  const savedView=useState<SavedView|undefined>(()=>pageId==="A15"?window.history.state?.bossMaintainerRecords?.A15:undefined)[0];
  // 从运行列表进入F30再返回时沿用原筛选；从其他页面指定运行编号进入时以该编号为准。
  const restoreList=pageId==="A15"&&Boolean(savedView)&&(!initialRunId||savedView?.selected===initialRunId);
  const [tab,setTab]=useState<"model"|"tools"|"business"|"configuration">("model");
  const [filters, setFilters] = useState<Filters>(restoreList&&savedView ? savedView.filters : defaultFilters(initialRunId));
  const [data, setData] = useState<Projection | null>(null);
  const [selected, setSelected] = useState<RuntimeRecord | null>(null);
  const [task, setTask] = useState<TaskReference | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [details, setDetails] = useState(false);
  const [technical, setTechnical] = useState(restoreList);
  const active = useRef<AbortController | null>(null);
  const pending = useRef<{kind:"list"|"detail";parameters:URLSearchParams}|null>(null);
  const applied = useRef<URLSearchParams | null>(restoreList&&savedView ? new URLSearchParams(savedView.applied) : null);
  const restoreSelected = useRef(restoreList&&savedView ? savedView.selected : "");
  const detailPanel = useRef<HTMLDivElement>(null);
  const mountIdentity=useRef(identityKey);
  useEffect(() => {
    const initial = restoreList && mountIdentity.current===identityKey ? savedView : undefined;
    const start = initial?.filters ?? defaultFilters(initialRunId);
    const parameters = initial?.applied ? new URLSearchParams(initial.applied) : filtersToParameters(start);
    setFilters(start); setTab("model"); setData(null); setSelected(null); setTask(null);
    setDetails(false); setError(""); setNotice(""); setTechnical(false);
    if (pageId==="F30" && !initialRunId) {setLoading(false); return () => active.current?.abort();}
    void read(parameters);
    return () => active.current?.abort();
  }, [getToken, identityKey, initialRunId, pageId]);
  useEffect(() => {
    if (pageId!=="A15" || !applied.current) return;
    const state = window.history.state ?? {};
    window.history.replaceState({...state, bossMaintainerRecords: {...state.bossMaintainerRecords, A15: {
      filters, applied: applied.current.toString(), selected: selected?.run_id ?? "", pageId: "A15" as const}}}, "", window.location.href);
  }, [pageId, filters, selected, data]);

  function read(parameters: URLSearchParams, append = false, detail = false) {
    active.current?.abort();
    const abort = new AbortController(); active.current = abort;
    pending.current = {kind: detail ? "detail" : "list", parameters};
    setError(""); setNotice(""); setTask(null); setLoading(true);
    if (!append && !detail) setDetails(false);
    const token = getToken();
    if (!token) {setData(null); setSelected(null); setError("技术维护身份已失效，请重新登录"); setLoading(false); return;}
    void fetch("/api/boss/ui/runtime-records?" + parameters.toString(), {
      headers: {Authorization: "Bearer " + token}, cache: "no-store", signal: abort.signal,
    }).then(async response => {
      if (!response.ok) throw Error("运行记录读取失败（HTTP " + response.status + "）");
      const result = await response.json() as Projection;
      if (result.projection !== "runtime-records" || result.source_type !== "RUNTIME_RECORD" ||
        result.private_body_available_here !== false || result.business_mutation_performed !== false)
        throw Error("运行记录来源或读取范围无效");
      return result;
    }).then(result => {
      if (abort.signal.aborted) return;
      if (append&&data&&result.namespace!==data.namespace) throw Error("当前执行空间已经变化，请重新查询运行记录");
      if (detail) {
        if (result.runs.length !== 1 || result.runs[0].run_id !== parameters.get("run_id"))
          throw Error("运行记录编号与详情响应不一致");
        setSelected(result.runs[0]); setDetails(true); setNotice("已刷新当前运行的获准技术记录与用量");
      } else {
        applied.current = parameters;
        setData(previous => append && previous ? {...result, runs: [...previous.runs, ...result.runs]} : result);
        setSelected(previous => previous ?? result.runs.find(run => run.run_id === restoreSelected.current) ?? null);
        restoreSelected.current = "";
        setNotice(append ? "已读取更多获准运行记录" : "已按当前条件读取获准运行记录");
      }
      pending.current = null;
      setLoading(false);
    }).then(undefined, failure => {
      if (abort.signal.aborted) return;
      pending.current = null;
      setError(failure instanceof Error ? failure.message : String(failure));
      setLoading(false);
    });
  }
  function openTask(taskId: string, record: RuntimeRecord) {
    if (onOpenTask) {onOpenTask(taskId, record.run_id); return;}
    active.current?.abort();
    const abort = new AbortController(); active.current = abort;
    setTask(null); setError(""); setNotice(""); setLoading(true);
    const token = getToken();
    if (!token) {setData(null); setSelected(null); setError("技术维护身份已失效，请重新登录"); setLoading(false); return;}
    const parameters = new URLSearchParams({run_id: record.run_id, task_id: taskId});
    void fetch("/api/boss/ui/runtime-records/task?" + parameters.toString(), {
      headers: {Authorization: "Bearer " + token}, cache: "no-store", signal: abort.signal,
    }).then(async response => {
      if (!response.ok) throw Error("关联任务读取失败（HTTP " + response.status + "）");
      const result = await response.json() as TaskReference;
      if (result.projection !== "runtime-task-reference" || result.source_type !== "RUNTIME_RECORD" ||
        result.task_source_type !== "SIMULATED" || result.run_id !== record.run_id || result.task_id !== taskId ||
        result.namespace !== record.namespace || result.dataset_id !== record.dataset_id ||
        result.dataset_version !== record.dataset_version || result.private_body_available_here !== false ||
        result.business_mutation_performed !== false) throw Error("关联任务来源或读取范围无效");
      if (abort.signal.aborted) return;
      setTask(result); setLoading(false);
    }).then(undefined, failure => {
      if (abort.signal.aborted) return;
      setError(failure instanceof Error ? failure.message : String(failure));
      setTask(null); setDetails(false); setLoading(false);
    });
  }
  function query(event: FormEvent) {
    event.preventDefault();
    if (rangeInvalid(filters)) {setError("真实开始时间范围无效：开始时间必须早于结束时间"); return;}
    read(filtersToParameters(filters));
  }
  function quickFailed() {
    const next = {...filters, status: filters.status === "FAILED" ? "" : "FAILED"};
    setFilters(next);
    if (rangeInvalid(next)) {setError("真实开始时间范围无效：开始时间必须早于结束时间"); return;}
    read(filtersToParameters(next));
  }
  function more() {
    if (!data?.next_cursor || !applied.current) return;
    const parameters = new URLSearchParams(applied.current);
    for (const [key, input] of Object.entries(data.next_cursor)) parameters.set(key, input);
    read(parameters, true);
  }
  function cancel() {
    active.current?.abort(); setLoading(false);
    const kind = pending.current?.kind;
    pending.current = null;
    setNotice(kind === "detail"
      ? "已停止本次读取；当前运行已加载的技术记录与用量继续保留"
      : "已停止本次读取；列表保留上一次查询结果，本次筛选未应用");
  }
  function select(record: RuntimeRecord) {
    setSelected(record); setTask(null); setDetails(false); setNotice("");
  }
  function openDetails(record: RuntimeRecord) {
    if (pageId === "A15" && onOpenRunDetails) {onOpenRunDetails(record.run_id); return;}
    select(record);
    detailPanel.current?.scrollIntoView({block: "start", behavior: "smooth"});
    detailPanel.current?.focus();
  }
  async function copyDiagnostics() {
    if (!selected) return;
    const lines = pageId === "F30"
      ? ["run_id=" + selected.run_id, "request_id=" + selected.request_id,
        "配置编号及版本=" + selected.configuration_id + " v" + selected.configuration_version,
        "运行状态=" + selected.status, "终止原因=" + (selected.stop_reason ?? "未记录"),
        "开始时间=" + selected.started_at, "结束时间=" + (selected.finished_at ?? "未记录"),
        "配置摘要=" + selected.runtime.config_sha256]
      : ["run_id=" + selected.run_id, "request_id=" + selected.request_id,
        "Provider=" + selected.runtime.provider, "模型=" + selected.runtime.model_id,
        "配置编号及版本=" + selected.configuration_id + " v" + selected.configuration_version,
        "运行状态=" + selected.status, "终止原因=" + (selected.stop_reason ?? "未记录"),
        "开始时间=" + selected.started_at, "结束时间=" + (selected.finished_at ?? "未记录"),
        "用量覆盖=" + selected.usage_coverage, "计价版本=" + (selected.price_version ?? "未知"),
        "工具配置摘要=" + selected.tool_config_sha256];
    try {
      await navigator.clipboard.writeText(lines.join("\n"));
      setNotice("已复制获准诊断信息；不含凭据、私人正文与内部推理");
    } catch {
      setError("当前环境不允许写入剪贴板，请手动复制运行编号");
    }
  }
  const taskIds = [...new Set([...(selected?.tool_results.flatMap(result => result.task_id ? [result.task_id] : []) ?? []),...(selected?.owner_task_links?.map(link=>link.task_id) ?? [])])];
  const show=(section:typeof tab)=>pageId!=="F30"||tab===section;
  const refreshDetail=()=>{if(selected)read(new URLSearchParams({run_id:selected.run_id}),false,true);};
  const listIncomplete = Boolean(selected && data && !data.runs.some(run => run.run_id === selected.run_id));
  const technicalFields = <details className="boss-runtime-metadata" open={technical} onToggle={event => setTechnical(event.currentTarget.open)}>
    <summary>技术精确条件</summary>
    <div className="boss-v7-filter-bar boss-maintainer-filters">
      {([ ["provider", "Provider"], ["run_id", "run_id"], ["dataset_id", "数据集"],
        ["stop_reason", "错误类型或终止原因"] ] as const).map(([key, label]) =>
        <label key={key}>{label}<input value={filters[key]} maxLength={128}
          onChange={event => setFilters(previous => ({...previous, [key]: event.target.value}))}/></label>)}
    </div>
    <p className="boss-helper">工具与业务对象筛选需要服务端提供对应字段，当前接口没有提供，不能按这两项筛选。</p>
  </details>;
  const filterForm = <form id={formId} onSubmit={query} className="boss-v7-filter-bar boss-maintainer-filters" aria-label="运行记录查询">
    <label>运行状态<select value={filters.status} onChange={event => setFilters(previous => ({...previous, status: event.target.value}))}>
      <option value="">全部状态</option>{STATUSES.map(status => <option key={status}>{status}</option>)}
    </select></label>
    <label>开始时间从（Asia/Shanghai）<input type="datetime-local" step="0.001" value={filters.started_from}
      onChange={event => setFilters(previous => ({...previous, started_from: event.target.value}))}/></label>
    <label>开始时间至（Asia/Shanghai）<input type="datetime-local" step="0.001" value={filters.started_until}
      onChange={event => setFilters(previous => ({...previous, started_until: event.target.value}))}/></label>
    <label>每页数量<select value={filters.limit} onChange={event => setFilters(previous => ({...previous, limit: event.target.value}))}>
      {[10, 20, 50, 100].map(limit => <option key={limit}>{limit}</option>)}
    </select></label>
    <button type="button" className={filters.status==="FAILED"?"boss-btn boss-btn-primary":"boss-btn"} aria-pressed={filters.status==="FAILED"} onClick={quickFailed}>仅看失败</button>
    <button className="boss-btn boss-btn-primary" type="submit" disabled={loading}><FileSearch size={16}/>{pageId==="F30"?"查询":"查询运行"}</button>
    {technicalFields}
  </form>;
  return <div className="boss-maintainer-records boss-runtime-records">
      {pageId==="F30"
        ? <details className="boss-panel" open={!selected}><summary>更换运行</summary>
            {filterForm}
            <p className="boss-helper">从运行列表进入时自动带入该次运行；在这里可以按运行编号或条件更换所选运行。</p>
          </details>
        : <>{filterForm}</>}
    {loading && <div role="status" className="boss-status"><Loader2 size={16} className="boss-spin"/>
      {pending.current?.kind === "detail" ? "正在刷新当前运行的获准明细与用量" : "正在按当前条件读取运行记录；列表在读取完成前保留上一次查询结果"}
      <button type="button" className="boss-btn" onClick={cancel}><Square size={16}/>停止本次读取</button>
    </div>}
    {error && <div role="alert" className="boss-status boss-status-error"><AlertCircle size={16}/>{error}</div>}
    {notice && <div role="status" className="boss-status">{notice}</div>}
    <p className="boss-helper">当前列表筛选：{appliedSummary(applied.current)}。未指定运行编号时默认先读取最近 {RANGE_DAYS} 天的运行记录。</p>
    <div className="boss-maintainer-columns"><div className="boss-column">
      <V7Panel title="执行概览"><div className="boss-runtime-summary"><Detail label="模型请求">{selected?.model_requests.length}</Detail><Detail label="工具结果">{selected?.tool_results.length}</Detail><Detail label="配置版本">{selected?.configuration_version}</Detail><Detail label="业务结果">{selected?"按关联对象核查":"尚未选择运行"}</Detail><Detail label="终止原因">{selected?.stop_reason}</Detail><Detail label="授权状态">{selected?"按原动作授权记录核查":"尚未选择运行"}</Detail></div></V7Panel>
      <section className="boss-panel" aria-label="运行记录列表">
        <div className="boss-panel-head"><h2>已记录的运行</h2><small>{data ? `已读取 ${data.runs.length} / 匹配 ${data.matched_count}` : "记录待查询"}</small></div>
        {data && <><Detail label="当前执行空间">{data.namespace}</Detail><Detail label="实际读取时间">{data.read_at}</Detail></>}
        {!data?.runs.length && <V7Empty title={data?"没有符合当前条件的运行记录":"运行记录待读取"}>未指定运行编号时默认读取最近 {RANGE_DAYS} 天的运行记录，可按状态或时间调整条件。</V7Empty>}
        {!!data?.runs.length && <div className="boss-v7-table-scroll"><table className="boss-v7-table">
          <thead><tr><th scope="col">任务用途 · 开始时间 · 业务状态</th><th scope="col">Provider / 配置版本</th>
            <th scope="col">请求 / 工具返回</th><th scope="col">运行状态 / 终止原因</th><th scope="col">操作</th></tr></thead>
          <tbody>{data.runs.map(record => <tr key={record.run_id} aria-selected={record.run_id === selected?.run_id}>
            <td><button type="button" className="boss-v7-text-button" onClick={() => select(record)}>{runPurpose(record)} · {record.started_at}</button>
              <small>{record.run_id}</small><small>{businessState(record)}</small></td>
            <td>{record.runtime.provider}<br/>v{record.configuration_version}</td>
            <td>{record.model_requests.length} / {record.tool_results.length}</td><td>{record.status}<br/>{value(record.stop_reason)}</td>
            <td><button type="button" className="boss-btn" disabled={loading} onClick={() => openDetails(record)}>查看运行详情与用量</button></td>
          </tr>)}</tbody>
        </table></div>}
        {data?.next_cursor && <button type="button" className="boss-btn" disabled={loading} onClick={more}>读取更多记录</button>}
        {listIncomplete && <p className="boss-helper">当前选中的运行不在本次查询结果中；详情继续显示已选运行，翻页或重新查询不会替换所选对象。</p>}
      </section>
        <div ref={detailPanel} tabIndex={-1}>
        <section className="boss-panel">
          <div className="boss-panel-head"><h2>运行详情与用量</h2><small>获准技术记录</small>
            {selected&&<div className="boss-actions">
              {pageId==="F30"&&<button type="button" className="boss-btn" disabled={loading} onClick={refreshDetail}><RefreshCw size={15}/>刷新明细</button>}
              <button type="button" className="boss-btn" onClick={copyDiagnostics}><ClipboardCopy size={15}/>{pageId==="F30"?"复制诊断编号":"复制诊断信息"}</button>
            </div>}
          </div>
          {pageId==="F30"&&<V7Tabs label="运行详情分类" value={tab} onChange={setTab} items={[{id:"model",title:"模型请求",count:selected?.model_requests.length},{id:"tools",title:"工具输入结果",count:selected?.tool_results.length},{id:"business",title:"授权与业务状态"},{id:"configuration",title:"配置版本"}]}/>}
          {!selected ? <V7Empty title="尚未选择实际运行记录">从上方列表选择一条记录查看请求、工具结果及终止原因。</V7Empty> : <>
            <details className="boss-runtime-metadata"><summary>运行标识与时间</summary>
            <Detail label="run_id">{selected.run_id}</Detail><Detail label="request_id">{selected.request_id}</Detail>
            <Detail label="请求编号来源">{selected.request_id_source}</Detail><Detail label="session_id">{selected.session_id}</Detail>
            <Detail label="数据集及版本">{selected.dataset_id ? `${selected.dataset_id} · v${value(selected.dataset_version)}` : null}</Detail>
            <Detail label="真实开始时间">{selected.started_at}</Detail><Detail label="真实结束时间">{selected.finished_at}</Detail>
            <Detail label="运行状态">{selected.status}</Detail><Detail label="终止原因">{selected.stop_reason}</Detail>
            <Detail label="模型事件来源">{selected.source_type === "SIMULATED" ? "SIMULATED · 未请求真实外部模型" : "原记录没有该字段"}</Detail>
            <Detail label="终止来源">{selected.termination_source}</Detail>
            <Detail label="模型完成已观察">{selected.model_completion_observed ? "已经观察" : "尚未观察"}</Detail>
            <Detail label="业务完成">未通过本投影判定</Detail>
            </details>
            {show("configuration")&&<>
            <h3>本次采用配置</h3>
            <Detail label="配置编号及版本">{selected.configuration_id} · v{selected.configuration_version}</Detail>
            <Detail label="Provider / 模型">{selected.runtime.provider} / {selected.runtime.model_id}</Detail>
            <Detail label="实际工具轮数限制">{selected.runtime.max_tool_rounds}</Detail>
            {selected.prompt_versions.map(prompt => <Detail key={prompt.prompt_id} label={prompt.kind}>
              {prompt.prompt_id} · 内容v{prompt.prompt_version} · 启用v{prompt.active_version}</Detail>)}
            <Detail label="配置摘要">{selected.runtime.config_sha256}</Detail><Detail label="全部工具配置摘要">{selected.tool_config_sha256}</Detail>
            {selected.tool_configuration.map(tool=><div key={tool.tool_id} className="boss-workspace-item"><Detail label="工具编号及实现">{tool.tool_id} · {tool.implementation}</Detail><Detail label="Schema 摘要">{tool.schema_sha256}</Detail><Detail label="实现源码摘要">{tool.implementation_sha256}</Detail></div>)}
            </>}
            {show("tools")&&<><h3>工具返回与结果对象</h3>
            <p className="boss-v7-note">当前投影提供工具调用编号与结果元信息，工具输入正文需要独立访问授权。</p>
            {!selected.tool_results.length && <p>本次运行没有已观察的工具返回</p>}
            {selected.tool_results.map(result => <div key={result.tool_call_id} className="boss-workspace-item">
              <Detail label="工具及调用编号">{result.tool_id} · {result.tool_call_id}</Detail>
              <Detail label="结果对象">{result.query_id ?? result.task_id ?? result.message_id}</Detail>
              <Detail label="业务状态及版本">{value(result.task_status ?? result.status)} · {value(result.task_version ?? result.version)}</Detail>
            </div>)}
            </>}
            {show("business")&&<><h3>授权与业务状态</h3><p>运行状态与业务完成分别核查。当前投影没有提供完整授权判定，关联任务入口读取正式任务状态。</p>
            {selected.owner_task_links?.map(link=><div key={link.task_id+link.request_id} className="boss-workspace-item"><Detail label="任务与版本">{link.task_id} · v{link.task_version}</Detail><Detail label="动作与请求">{link.action} · {link.request_id}</Detail><Detail label="准备记录摘要">{link.preparation_sha256}</Detail></div>)}
            {taskIds.map(taskId => <button key={taskId} type="button" className="boss-btn" disabled={loading}
              onClick={() => openTask(taskId, selected)}>查看关联任务 {taskId}</button>)}
            {!taskIds.length && <p className="boss-helper">本次运行没有关联任务，业务完成需要按其他获准对象核查。</p>}
            </>}
            {show("model")&&<>
              <h3>已记录模型请求</h3><p>记录来源：{selected.source_type??"原记录未提供来源类型"}；请求覆盖：{selected.model_attempts_coverage??"未知"}。</p>
              {!selected.model_requests.length&&<V7Empty title="本次运行没有已记录的 HTTP 模型请求"/>}
              {selected.model_requests.map(request => <div key={request.model_request_id} className="boss-workspace-item">
                <Detail label="模型请求编号">{request.model_request_id}</Detail><Detail label="HTTP 状态">{request.http_status}</Detail>
                <Detail label="服务响应编号">{request.response_ids.join("、")}</Detail><Detail label="模型结束原因">{request.finish_reasons.join("、")}</Detail>
                <Detail label="请求摘要">{request.request_sha256}</Detail><Detail label="实际传输工具摘要">{request.tool_config_sha256}</Detail>
                <UsageFields usage={request.usage}/>
              </div>)}
            </>}
          </>}
        </section>
        </div>
        {task && <section className="boss-panel" aria-label="关联任务技术信息">
          <div className="boss-panel-head"><h2>关联任务技术信息</h2><small>RUNTIME_RECORD · SIMULATED</small></div>
          <Detail label="关联 run_id">{task.run_id}</Detail><Detail label="task_id">{task.task_id}</Detail>
          <Detail label="当前任务状态">{task.task_status}</Detail><Detail label="当前任务版本">{task.task_version}</Detail>
          <Detail label="执行空间">{task.namespace}</Detail>
          <Detail label="数据集及版本">{task.dataset_id} · v{task.dataset_version}</Detail>
          <Detail label="读取时间">{task.read_at}</Detail>
        </section>}
        <V7Panel title="用量与分项计费" description="未知用量及缺少计价依据分别显示"><div className="boss-v7-table-scroll"><table className="boss-v7-table"><thead><tr><th>资源类型</th><th>用量</th><th>缓存</th><th>计价日期或版本</th><th>费用</th></tr></thead><tbody>{selected&&<><tr><td>模型 Token<small>本次已记录请求合计</small></td><td>输入 {value(selected.usage?.prompt_tokens)}<br/>输出 {value(selected.usage?.completion_tokens)}<br/>总计 {value(selected.usage?.total_tokens)}</td><td>命中 {value(selected.usage?.prompt_cache_hit_tokens)}<br/>未命中 {value(selected.usage?.prompt_cache_miss_tokens)}</td><td>{value(selected.price_version)}</td><td>未知</td></tr>{selected.model_requests.map(request=><tr key={request.model_request_id}><td>请求 {request.model_request_id}<small>HTTP {value(request.http_status)}</small></td><td>输入 {value(request.usage?.prompt_tokens)}<br/>输出 {value(request.usage?.completion_tokens)}<br/>总计 {value(request.usage?.total_tokens)}</td><td>命中 {value(request.usage?.prompt_cache_hit_tokens)}<br/>未命中 {value(request.usage?.prompt_cache_miss_tokens)}</td><td>{value(selected.price_version)}</td><td>未知</td></tr>)}<tr><td>检索</td><td>未知</td><td>未知</td><td>未知</td><td>未知</td></tr><tr><td>语音</td><td>未知</td><td>未知</td><td>未知</td><td>未知</td></tr></>}</tbody></table></div>{!selected&&<V7Empty title="尚未选择可核算用量的运行"/>}{selected&&<><div className="boss-runtime-summary"><Detail label="费用覆盖范围">{selected.usage_coverage}</Detail><Detail label="已知费用小计">未知</Detail><Detail label="完整总额">{selected.cost_total===null?"null（未核算）":selected.cost_total}</Detail><Detail label="币种">未知</Detail></div><p className="boss-v7-note">请求行用于解释合计来源，不能与合计再次相加。缓存命中和未命中均属于输入 Token；缺少请求回执或价格时保持未知。用量与明细来自同一次获准读取；重新读取时一起更新，不单独重复请求，也不重新调用模型。</p></>}</V7Panel>
      </div><aside className="boss-column" aria-label="运行依据与状态">
        <V7Panel title="来源与依据"><Detail label="记录来源">{data?.source_type}</Detail><Detail label="当前执行空间">{data?.namespace}</Detail><Detail label="查询读取时间">{data?.read_at}</Detail><Detail label="数据集及版本">{selected?`${selected.dataset_id??"未知"} · v${selected.dataset_version??"未知"}`:null}</Detail><Detail label="Token 与缓存">{selected?.usage_coverage}</Detail><Detail label="语音与检索费用">未知</Detail><Detail label="计价日期或版本">{selected?.price_version}</Detail><Detail label="币种">未知</Detail><p>私人正文、凭据和内部推理不在当前读取范围。</p></V7Panel>
        <V7Panel title="状态与核查"><Detail label="查询状态">{loading?"正在读取":error?"读取失败":data?"已读取获准记录":"记录待读取"}</Detail><Detail label="已应用筛选">{appliedSummary(applied.current)}</Detail><Detail label="当前运行">{selected?.run_id}</Detail><Detail label="运行状态">{selected?.status}</Detail><Detail label="终止原因">{selected?.stop_reason}</Detail><Detail label="明细核查">{selected?details?"已刷新当前运行记录":"使用列表读取版本":"尚未选择运行"}</Detail><Detail label="模型完成观察">{selected?selected.model_completion_observed?"已经观察":"尚未观察":null}</Detail><Detail label="业务状态">{task?.task_status??"需要核查关联对象"}</Detail><Detail label="模型行为评测">{selected?selected.model_behavior_evaluation_passed?"记录标记已通过":"尚未验证通过":null}</Detail></V7Panel>
        {pageId==="F30"&&onBackToList&&<div className="boss-actions"><button type="button" className="boss-btn" onClick={onBackToList}>返回运行列表</button></div>}
      </aside>
    </div>
  </div>;
}
