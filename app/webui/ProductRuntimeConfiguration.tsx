import { useCallback, useEffect, useRef, useState } from "react";

type Values = {max_tool_rounds: number; max_output_tokens: number; tool_scope: string[]};
type Draft = {version: string; values: Values; content_sha256: string; validation_status: string};
type Projection = {
  projection: "runtime-configuration";
  current: {version: string; enabled: boolean; provider: string; model_id: string; tool_scope: string[]; max_tool_rounds: number};
  draft: Draft | null; effective: Values & {config_sha256: string};
  available_tools: string[]; admission_ready: boolean; active_run_count: number;
  native_config_sha256: string; private_body_available_here: false; business_authority_granted: false;
};
type Props = {getToken: () => string; onCommand: (action: string, payload: Record<string, unknown>) => Promise<void>;
  onDirtyChange: (dirty: boolean) => void; onReload: () => void};

export function ProductRuntimeConfiguration({getToken, onCommand, onDirtyChange, onReload}: Props) {
  const [data, setData] = useState<Projection | null>(null);
  const [values, setValues] = useState<Values | null>(null);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const active = useRef<AbortController | null>(null);
  const locked = useRef(false);
  const requests = useRef(new Map<string, string>());
  const read = useCallback(async () => {
    active.current?.abort();
    const abort = new AbortController(); active.current = abort;
    const response = await fetch("/api/boss/ui/admin/runtime-configuration", {
      headers: {Authorization: "Bearer " + getToken()}, cache: "no-store", signal: abort.signal,
    });
    if (!response.ok) throw Error("运行配置读取失败（HTTP " + response.status + "）");
    const next = await response.json() as Projection;
    if (next.projection !== "runtime-configuration" || next.private_body_available_here !== false ||
        next.business_authority_granted !== false) throw Error("运行配置来源无效");
    if (abort.signal.aborted) return;
    setData(next);
    setValues(next.draft?.values ?? {max_tool_rounds: next.current.max_tool_rounds,
      max_output_tokens: next.effective.max_output_tokens, tool_scope: next.current.tool_scope});
    setDirty(false);
    onDirtyChange(false);
  }, [getToken, onDirtyChange]);
  useEffect(() => {
    setError("");
    void read().catch((reason: unknown) => {if (!active.current?.signal.aborted) setError(String(reason));});
    return () => active.current?.abort();
  }, [read]);
  function edit(next: Values) {setValues(next); setDirty(true); onDirtyChange(true); setNotice("");}
  async function mutate(action: string, payload: Record<string, unknown>) {
    if (locked.current) return;
    locked.current = true; setBusy(true); setError(""); setNotice("");
    try {
      const signature = JSON.stringify({action, payload});
      const requestId = requests.current.get(signature) ?? crypto.randomUUID();
      requests.current.set(signature, requestId);
      await onCommand(action, {client_request_id: requestId, ...payload});
      await read();
      onReload();
      setNotice(action === "boss.runtime.activate" ? "已启用当前配置，下一任务使用该版本。" :
        action === "boss.runtime.validate" ? "配置静态校验通过，模型行为尚未验证。" :
        action === "boss.runtime.deactivate" ? "已停止新模型任务，进行中的任务保留原配置。" : "配置草稿已保存。请校验并明确启用。");
    } catch (reason: unknown) {setError(String(reason instanceof Error ? reason.message : reason));}
    finally {locked.current = false; setBusy(false);}
  }
  return <section className="boss-panel" aria-label="公共模型运行配置">
    <header className="boss-panel-head"><h3>公共模型运行配置</h3></header>
    {error && <div className="boss-error" role="alert">{error}</div>}
    {notice && <p role="status">{notice}</p>}
    {!data || !values ? <p role="status">正在读取当前运行配置…</p> : <>
      <p>DeepSeek · deepseek-flash · 当前版本 {data.current.version} · {data.current.enabled ? "已启用" : "已停用"}</p>
      <p role="status">{data.admission_ready ? "当前Runtime可以接收新任务" : "当前Runtime需要校验并启用配置"} · 进行中 {data.active_run_count} 项</p>
      <form onSubmit={event => {event.preventDefault(); void mutate("boss.runtime.save", {expected_version: data.draft?.version ?? "0", values});}}>
        <fieldset disabled={busy} className="boss-runtime-fields">
          <legend>下一任务的配置</legend>
          <label>最大工具轮数<input type="number" min={1} max={12} required value={values.max_tool_rounds}
            onChange={event => edit({...values, max_tool_rounds: event.currentTarget.valueAsNumber})}/></label>
          <label>最大输出 Token<input type="number" min={128} max={8192} required value={values.max_output_tokens}
            onChange={event => edit({...values, max_output_tokens: event.currentTarget.valueAsNumber})}/></label>
          <fieldset><legend>允许的工具范围</legend>{data.available_tools.map(name => <label key={name}>
            <input type="checkbox" checked={values.tool_scope.includes(name)} onChange={event => edit({...values,
              tool_scope: event.currentTarget.checked ? [...values.tool_scope, name].sort() : values.tool_scope.filter(item => item !== name)})}/>{name}</label>)}</fieldset>
          <p>工具启用不授予老板业务权限。交办和发送继续核查本人的当前授权。配置启用需要等待进行中的任务结束。</p>
          <div className="boss-actions">
            <button className="boss-btn" type="submit" disabled={!dirty}>保存配置草稿</button>
            <button className="boss-btn" type="button" disabled={dirty || !data.draft || data.draft.validation_status !== "DRAFT_UNVALIDATED"}
              onClick={() => {if (data.draft) void mutate("boss.runtime.validate", {expected_version: data.draft.version, expected_content_sha256: data.draft.content_sha256});}}>校验配置</button>
            <button className="boss-btn boss-btn-primary" type="button" disabled={dirty || !data.draft || data.draft.validation_status !== "VALIDATED_STATIC_ONLY" || data.active_run_count > 0}
              onClick={() => {if (data.draft) void mutate("boss.runtime.activate", {expected_version: data.draft.version,
                expected_content_sha256: data.draft.content_sha256, expected_active_version: data.current.version});}}>启用下一任务配置</button>
            <button className="boss-btn" type="button" disabled={!data.current.enabled}
              onClick={() => void mutate("boss.runtime.deactivate", {expected_active_version: data.current.version})}>停止新模型任务</button>
          </div>
        </fieldset>
      </form>
      <p>草稿状态：{data.draft?.validation_status ?? "尚未保存"}。费用与模型行为评测分别记录。</p>
      <button type="button" className="boss-btn" disabled={busy || dirty} onClick={() => {
        setError(""); void read().catch((reason: unknown) => setError(String(reason)));
      }}>重新读取运行配置</button>
    </>}
  </section>;
}
