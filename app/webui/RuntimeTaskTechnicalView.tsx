import { useEffect, useState } from "react";

type Props = {getToken: () => string; taskId: string; runId: string; onClose: () => void};
type Task = {task_id: string; status: string; version: string; coordinator_id: string};
type Runs = {projection: string; runs: {run_id: string; tool_results: {task_id?: string}[]}[]};

export function RuntimeTaskTechnicalView({getToken, taskId, runId, onClose}: Props) {
  const [task, setTask] = useState<Task | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    const abort = new AbortController();
    setTask(null); setError(""); setLoading(true);
    const token = getToken();
    if (!token) {setError("技术维护身份已失效，请重新认证"); setLoading(false); return;}
    async function read<T>(path: string): Promise<T> {
      const response = await fetch(path, {headers: {Authorization: "Bearer " + token},
        cache: "no-store", signal: abort.signal});
      if (response.status === 401) window.dispatchEvent(new Event("boss-auth-expired"));
      if (!response.ok) throw new Error("交办技术状态读取失败（HTTP " + response.status + "）");
      return response.json() as Promise<T>;
    }
    void Promise.all([
      read<Runs>("/api/boss/ui/runtime-records?run_id=" + encodeURIComponent(runId)),
      read<{task_refs: Task[]}>("/api/boss/ui/maintenance"),
    ]).then(([runs, current]) => {
      if (abort.signal.aborted) return;
      if (runs.projection !== "runtime-records" || runs.runs.length !== 1 ||
          runs.runs[0].run_id !== runId || !runs.runs[0].tool_results.some(result => result.task_id === taskId))
        throw new Error("当前运行没有关联指定交办");
      const selected = current.task_refs.find(item => item.task_id === taskId);
      if (!selected) throw new Error("当前交办技术记录不可用，请重新查询");
      setTask(selected); setLoading(false);
    }).catch((failure: unknown) => {
      if (abort.signal.aborted) return;
      setTask(null); setLoading(false); setError(failure instanceof Error ? failure.message : String(failure));
    });
    return () => abort.abort();
  }, [getToken, taskId, runId]);
  return <section className="boss-panel" aria-label="关联交办技术状态">
    <div className="boss-panel-head"><h2>关联交办技术状态</h2><small>当前获准元信息</small></div>
    <button type="button" className="boss-btn" onClick={onClose}>关闭交办技术状态</button>
    {loading && <p role="status">正在核查运行关联与当前交办</p>}
    {error && <p className="boss-status boss-status-error" role="alert">{error}</p>}
    {task && <>
      <div className="boss-kv"><span>运行标识</span><strong>{runId}</strong></div>
      <div className="boss-kv"><span>交办标识</span><strong>{task.task_id}</strong></div>
      <div className="boss-kv"><span>当前业务状态</span><strong>{task.status}</strong></div>
      <div className="boss-kv"><span>当前对象版本</span><strong>{task.version}</strong></div>
      <div className="boss-kv"><span>负责人技术标识</span><strong>{task.coordinator_id}</strong></div>
      <p className="boss-helper">运行完成观察与当前交办状态分别核查。本页面仅展示技术元信息。</p>
    </>}
  </section>;
}
