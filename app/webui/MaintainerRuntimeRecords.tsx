import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { AlertCircle, FileSearch, Loader2, Square } from "lucide-react";

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
type Props = {getToken: () => string; onOpenTask?: (taskId: string, runId: string) => void; initialRunId?: string};
type TaskReference = {
  projection: "runtime-task-reference"; source_type: "RUNTIME_RECORD"; task_source_type: "SIMULATED";
  namespace: string; run_id: string; dataset_id: string; dataset_version: string;
  task_id: string; task_version: string; task_status: string; read_at: string;
  private_body_available_here: false; business_mutation_performed: false;
};
type Filters = {provider: string; run_id: string; dataset_id: string; status: string;
  stop_reason: string; started_from: string; started_until: string; limit: string};
const INITIAL: Filters = {provider: "", run_id: "", dataset_id: "", status: "", stop_reason: "",
  started_from: "", started_until: "", limit: "50"};
const STATUSES = ["QUEUED", "RUNNING", "WAITING_INPUT", "SUCCEEDED", "FAILED", "CANCELED", "TIMED_OUT"];
const value = (item: ReactNode) => item === null || item === undefined || item === "" ? "未知" : item;
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

export function MaintainerRuntimeRecords({getToken, onOpenTask, initialRunId}: Props) {
  const [filters, setFilters] = useState<Filters>({...INITIAL, run_id: initialRunId ?? ""});
  const [data, setData] = useState<Projection | null>(null);
  const [selected, setSelected] = useState<RuntimeRecord | null>(null);
  const [task, setTask] = useState<TaskReference | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [details, setDetails] = useState(false);
  const active = useRef<AbortController | null>(null);
  const applied = useRef<URLSearchParams | null>(null);
  useEffect(() => {
    setData(null); setSelected(null); setTask(null); setDetails(false); setError(""); setNotice(""); setLoading(false);
    applied.current = null;
    return () => active.current?.abort();
  }, [getToken]);

  function read(parameters: URLSearchParams, append = false, detail = false) {
    active.current?.abort();
    const abort = new AbortController(); active.current = abort;
    setError(""); setNotice(""); setTask(null); setLoading(true);
    if (!append && !detail) {setData(null); setSelected(null); setDetails(false);}
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
      if (detail) {
        if (result.runs.length !== 1 || result.runs[0].run_id !== parameters.get("run_id"))
          throw Error("运行记录编号与详情响应不一致");
        setSelected(result.runs[0]); setDetails(true); setNotice("已重新读取获准技术记录");
      } else {
        setData(previous => append && previous ? {...result, runs: [...previous.runs, ...result.runs]} : result);
      }
      setLoading(false);
    }).then(undefined, failure => {
      if (abort.signal.aborted) return;
      setError(failure instanceof Error ? failure.message : String(failure));
      setData(null); setSelected(null); setDetails(false); setLoading(false);
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
      setTask(null); setData(null); setSelected(null); setDetails(false); setLoading(false);
    });
  }
  function query(event: FormEvent) {
    event.preventDefault();
    const parameters = new URLSearchParams();
    for (const [key, input] of Object.entries(filters)) {
      if (!input.trim()) continue;
      parameters.set(key, key.startsWith("started_") ? new Date(input).toISOString() : input.trim());
    }
    if (parameters.has("started_from") && parameters.has("started_until") &&
      parameters.get("started_from")! > parameters.get("started_until")!) {
      setError("真实时间范围无效"); return;
    }
    applied.current = parameters; read(parameters);
  }
  function more() {
    if (!data?.next_cursor || !applied.current) return;
    const parameters = new URLSearchParams(applied.current);
    for (const [key, input] of Object.entries(data.next_cursor)) parameters.set(key, input);
    read(parameters, true);
  }
  function cancel() {
    active.current?.abort(); setLoading(false); setNotice("已取消本次读取，业务任务继续保持原有状态");
  }
  const taskIds = [...new Set(selected?.tool_results.flatMap(result => result.task_id ? [result.task_id] : []) ?? [])];
  return <>
    <section className="boss-panel" aria-label="运行记录查询">
      <div className="boss-panel-head"><h2>运行记录</h2><small>RUNTIME_RECORD · 获准技术元信息</small></div>
      <form onSubmit={query}>
        <div className="boss-form-grid">
          {([ ["provider", "Provider"], ["run_id", "run_id"], ["dataset_id", "数据集"],
            ["stop_reason", "错误类型或终止原因"] ] as const).map(([key, label]) =>
            <label key={key}>{label}<input value={filters[key]} maxLength={128}
              onChange={event => setFilters(previous => ({...previous, [key]: event.target.value}))}/></label>)}
          <label>运行状态<select value={filters.status} onChange={event => setFilters(previous => ({...previous, status: event.target.value}))}>
            <option value="">全部状态</option>{STATUSES.map(status => <option key={status}>{status}</option>)}
          </select></label>
          <label>每页数量<select value={filters.limit} onChange={event => setFilters(previous => ({...previous, limit: event.target.value}))}>
            {[1, 20, 50, 100].map(limit => <option key={limit}>{limit}</option>)}
          </select></label>
          <label>真实开始时间从<input type="datetime-local" step="0.001" value={filters.started_from}
            onChange={event => setFilters(previous => ({...previous, started_from: event.target.value}))}/></label>
          <label>真实开始时间至<input type="datetime-local" step="0.001" value={filters.started_until}
            onChange={event => setFilters(previous => ({...previous, started_until: event.target.value}))}/></label>
        </div>
        <div className="boss-actions">
          <button className="boss-btn boss-btn-primary" type="submit" disabled={loading}><FileSearch size={16}/>查询记录</button>
          <button className="boss-btn" type="button" disabled={!loading} onClick={cancel}><Square size={16}/>取消读取</button>
        </div>
      </form>
    </section>
    {loading && <div role="status" className="boss-status"><Loader2 size={16} className="boss-spin"/>正在读取运行记录</div>}
    {error && <div role="alert" className="boss-status boss-status-error"><AlertCircle size={16}/>{error}</div>}
    {notice && <div role="status" className="boss-status">{notice}</div>}
    <div className="boss-columns">
      <section className="boss-panel" aria-label="运行记录列表">
        <div className="boss-panel-head"><h2>已记录的运行</h2><small>{data ? `已读取 ${data.runs.length} / 匹配 ${data.matched_count}` : "记录待查询"}</small></div>
        {data && <><Detail label="当前执行空间">{data.namespace}</Detail><Detail label="实际读取时间">{data.read_at}</Detail></>}
        {data?.runs.length === 0 && <p role="status">没有符合当前条件的运行记录</p>}
        {!!data?.runs.length && <div className="boss-table-scroll"><table className="boss-table">
          <thead><tr><th scope="col">运行编号 / 真实时间</th><th scope="col">Provider / 配置版本</th>
            <th scope="col">请求 / 工具返回</th><th scope="col">运行状态 / 终止原因</th><th scope="col">操作</th></tr></thead>
          <tbody>{data.runs.map(record => <tr key={record.run_id} aria-selected={record.run_id === selected?.run_id}>
            <td>{record.run_id}<br/>{record.started_at}</td><td>{record.runtime.provider}<br/>v{record.configuration_version}</td>
            <td>{record.model_requests.length} / {record.tool_results.length}</td><td>{record.status}<br/>{value(record.stop_reason)}</td>
            <td><button type="button" className="boss-btn" disabled={loading} aria-label={"打开记录 " + record.run_id}
              onClick={() => {setSelected(record); setTask(null); setDetails(false); setNotice("");}}>打开记录</button></td>
          </tr>)}</tbody>
        </table></div>}
        {data?.next_cursor && <button type="button" className="boss-btn" disabled={loading} onClick={more}>读取更多记录</button>}
      </section>
      <aside className="boss-column" aria-label="运行记录详情">
        <section className="boss-panel">
          <div className="boss-panel-head"><h2>获准记录详情</h2><small>私人正文、凭据和内部推理不在读取范围</small></div>
          {!selected ? <p>选择已有运行记录查看详情</p> : <>
            <Detail label="run_id">{selected.run_id}</Detail><Detail label="request_id">{selected.request_id}</Detail>
            <Detail label="请求编号来源">{selected.request_id_source}</Detail><Detail label="session_id">{selected.session_id}</Detail>
            <Detail label="数据集及版本">{selected.dataset_id ? `${selected.dataset_id} · v${value(selected.dataset_version)}` : null}</Detail>
            <Detail label="真实开始时间">{selected.started_at}</Detail><Detail label="真实结束时间">{selected.finished_at}</Detail>
            <Detail label="运行状态">{selected.status}</Detail><Detail label="终止原因">{selected.stop_reason}</Detail>
            <Detail label="终止来源">{selected.termination_source}</Detail>
            <Detail label="模型完成已观察">{selected.model_completion_observed ? "已经观察" : "尚未观察"}</Detail>
            <Detail label="业务完成">未通过本投影判定</Detail>
            <Detail label="配置编号及版本">{selected.configuration_id} · v{selected.configuration_version}</Detail>
            <Detail label="Provider / 模型">{selected.runtime.provider} / {selected.runtime.model_id}</Detail>
            <Detail label="实际工具轮数限制">{selected.runtime.max_tool_rounds}</Detail>
            {selected.prompt_versions.map(prompt => <Detail key={prompt.prompt_id} label={prompt.kind}>
              {prompt.prompt_id} · 内容v{prompt.prompt_version} · 启用v{prompt.active_version}</Detail>)}
            <div className="boss-actions"><button type="button" className="boss-btn" disabled={loading}
              onClick={() => read(new URLSearchParams({run_id: selected.run_id}), false, true)}>核查明细</button></div>
            <h3>业务结果关联</h3>
            {!selected.tool_results.length && <p>本次运行没有已观察的工具返回或关联任务</p>}
            {selected.tool_results.map(result => <div key={result.tool_call_id} className="boss-workspace-item">
              <Detail label="工具及调用编号">{result.tool_id} · {result.tool_call_id}</Detail>
              <Detail label="结果对象">{result.query_id ?? result.task_id ?? result.message_id}</Detail>
              <Detail label="业务状态及版本">{value(result.task_status ?? result.status)} · {value(result.task_version ?? result.version)}</Detail>
            </div>)}
            {taskIds.map(taskId => <button key={taskId} type="button" className="boss-btn" disabled={loading}
              onClick={() => openTask(taskId, selected)}>查看关联任务 {taskId}</button>)}
            {!taskIds.length && <button type="button" className="boss-btn" disabled>查看关联任务（没有关联任务）</button>}
            {details && <>
              <h3>实际请求与工具配置</h3><Detail label="配置摘要">{selected.runtime.config_sha256}</Detail>
              <Detail label="全部工具配置摘要">{selected.tool_config_sha256}</Detail>
              {selected.model_requests.map(request => <div key={request.model_request_id} className="boss-workspace-item">
                <Detail label="模型请求编号">{request.model_request_id}</Detail><Detail label="HTTP 状态">{request.http_status}</Detail>
                <Detail label="服务响应编号">{request.response_ids.join("、")}</Detail><Detail label="模型结束原因">{request.finish_reasons.join("、")}</Detail>
                <Detail label="请求摘要">{request.request_sha256}</Detail><Detail label="实际传输工具摘要">{request.tool_config_sha256}</Detail>
                <UsageFields usage={request.usage}/>
              </div>)}
              {selected.tool_configuration.map(tool => <div key={tool.tool_id} className="boss-workspace-item">
                <Detail label="工具编号及实现">{tool.tool_id} · {tool.implementation}</Detail>
                <Detail label="Schema 摘要">{tool.schema_sha256}</Detail><Detail label="实现源码摘要">{tool.implementation_sha256}</Detail>
              </div>)}
            </>}
          </>}
        </section>
        {task && <section className="boss-panel" aria-label="关联任务技术信息">
          <div className="boss-panel-head"><h2>关联任务技术信息</h2><small>RUNTIME_RECORD · SIMULATED</small></div>
          <Detail label="关联 run_id">{task.run_id}</Detail><Detail label="task_id">{task.task_id}</Detail>
          <Detail label="当前任务状态">{task.task_status}</Detail><Detail label="当前任务版本">{task.task_version}</Detail>
          <Detail label="执行空间">{task.namespace}</Detail>
          <Detail label="数据集及版本">{task.dataset_id} · v{task.dataset_version}</Detail>
          <Detail label="读取时间">{task.read_at}</Detail>
        </section>}
        {selected && <section className="boss-panel" aria-label="费用与覆盖范围">
          <div className="boss-panel-head"><h2>用量与费用</h2><small>缺少用量保持未知</small></div>
          <UsageFields usage={selected.usage}/>
          <Detail label="语音用量">未知</Detail><Detail label="检索用量">未知</Detail>
          <Detail label="计价日期或版本">{selected.price_version}</Detail><Detail label="币种">未知</Detail>
          <Detail label="费用覆盖范围">{selected.usage_coverage}</Detail>
          <Detail label="请求覆盖范围">{selected.model_attempts_coverage}</Detail>
          <Detail label="已知费用小计">未知</Detail><Detail label="完整总额">{selected.cost_total === null ? "null（未核算）" : selected.cost_total}</Detail>
        </section>}
      </aside>
    </div>
  </>;
}
