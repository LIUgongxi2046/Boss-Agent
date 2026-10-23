import { useCallback, useEffect, useRef, useState } from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { useClient } from "@/providers/ClientProvider";

type Method = {
  sop_id: string; name: string; requirement_id: string; version: string; content_sha256: string;
  enabled: boolean; native_available: boolean; missing_tools: string[]; context_eligible: boolean;
  missing_projections:string[];projection_references_resolved:boolean;
  read_operations: string[]; command_operations: string[]; human_only_operations: string[];
};
type Projection = {
  projection: "sop-technical-status"; items: Method[]; native_configuration_sha256: string;
  runtime_admission_ready: boolean; private_body_available_here: false; business_authorization_granted: false;
  pending_activations: {sop_id: string; client_request_id: string}[];
};

export function MaintainerSkills() {
  const {client, getToken, token} = useClient();
  const [data, setData] = useState<Projection | null>(null);
  const [pending, setPending] = useState<Method | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const active = useRef<AbortController | null>(null);
  const surface = useRef<HTMLDivElement | null>(null);
  const epoch = useRef(0);
  const locked = useRef(false);
  const read = useCallback(async () => {
    active.current?.abort();
    const abort = new AbortController(); active.current = abort;
    const identity = epoch.current;
    setData(null); setLoading(true); setError("");
    await fetch("/api/boss/ui/admin/skills", {
      headers: {Authorization: "Bearer " + getToken()}, cache: "no-store", signal: abort.signal,
    }).then(async response => {
      if (!response.ok) throw Error("方法技术状态读取失败（HTTP " + response.status + "）");
      const result = await response.json() as Projection;
      if (result.projection !== "sop-technical-status" || result.items.length !== 13 ||
        result.private_body_available_here !== false || result.business_authorization_granted !== false)
        throw Error("方法技术投影范围无效");
      return result;
    }).then(result => {
      if (abort.signal.aborted || epoch.current !== identity) return;
      setData(result); setLoading(false);
    }).then(undefined, failure => {
      if (abort.signal.aborted || epoch.current !== identity) return;
      setData(null); setLoading(false); setPending(null); setConfirmed(false);
      setError(failure instanceof Error ? failure.message : String(failure));
    });
  }, [getToken]);
  useEffect(() => {
    epoch.current += 1; locked.current = false;
    setData(null); setPending(null); setConfirmed(false); setBusy(false); setNotice(""); setError("");
    void read();
    return () => {epoch.current += 1; active.current?.abort();};
  }, [client, token, read]);

  async function update() {
    if (!pending || !confirmed || locked.current) return;
    const identity = epoch.current;
    locked.current = true; setBusy(true); setError(""); setNotice("");
    try {
      const result = await client.requestMutation<{name: string; enabled: boolean; content_sha256: string}>("skill.update", {
        name: pending.name, enabled: !pending.enabled, expected_content_sha256: pending.content_sha256,
      });
      if (identity !== epoch.current) return;
      if (result.name !== pending.name || result.enabled !== !pending.enabled || result.content_sha256 !== pending.content_sha256)
        throw Error("方法状态回执与本次操作不一致");
      setPending(null); setConfirmed(false);
      setNotice("原生方法状态已保存，后续上下文按当前状态读取。");
      await read();
    } catch (failure) {
      if (identity !== epoch.current) return;
      setPending(null); setConfirmed(false);
      setError((failure instanceof Error ? failure.message : String(failure)) + "。请读取当前状态核查结果。");
      setData(null);
    } finally {
      if (identity === epoch.current) {locked.current = false; setBusy(false);}
    }
  }
  return <div ref={surface}>
    <section className="boss-panel" aria-label="秘书方法技术维护">
      <div className="boss-panel-head"><h2>SOP 与 Skills</h2><small>A06 · 原生方法文件与配置</small></div>
      <p>十三项方法读取当前文件、版本和实际工具目录。启停使用同一原生配置，不授予老板业务权限。</p>
      <button type="button" className="boss-btn" disabled={loading || busy} onClick={() => {void read();}}>读取当前方法状态</button>
      <div className="boss-kv"><span>当前 Runtime 可接收任务</span><strong>{data ? data.runtime_admission_ready ? "可以接收" : "需要检查当前运行配置" : "尚未读取"}</strong></div>
      <p>方法正文编辑、草稿及历史恢复继续由版本管理功能负责。当前状态读取和本地上下文检查没有验证模型质量。</p>
      {!!data?.pending_activations.length && <p role="status">存在待恢复的方法启用操作，请在方法版本页面明确继续或取消。</p>}
    </section>
    {loading && <div role="status" className="boss-status">正在读取当前方法</div>}
    {error && <div role="alert" className="boss-status boss-status-error">{error}</div>}
    {notice && <div role="status" className="boss-status">{notice}</div>}
    {data && <div className="boss-columns"><div className="boss-column">
      {data.items.map(item => <section key={item.sop_id} className="boss-panel" aria-label={"方法 " + item.sop_id}>
        <div className="boss-panel-head"><h2>{item.sop_id} · {item.name}</h2><small>{item.requirement_id} · v{item.version}</small></div>
        <div className="boss-kv"><span>当前状态</span><strong>{item.enabled ? "已经启用" : "已经停用"}</strong></div>
        <div className="boss-kv"><span>后续上下文采用条件</span><strong>{item.context_eligible ? "符合当前条件" : "当前不能采用"}</strong></div>
        <div className="boss-kv"><span>内容 SHA256</span><strong>{item.content_sha256}</strong></div>
        <div className="boss-kv"><span>读取工具</span><strong>{item.read_operations.join("、") || "没有读取工具"}</strong></div>
        <div className="boss-kv"><span>动作工具</span><strong>{item.command_operations.join("、") || "没有动作工具"}</strong></div>
        <div className="boss-kv"><span>需要本人独立确认</span><strong>{item.human_only_operations.join("、") || "根据对应业务动作核查"}</strong></div>
        <div className="boss-kv"><span>尚未注册的工具</span><strong>{item.missing_tools.join("、") || "当前引用已经注册"}</strong></div>
        <div className="boss-kv"><span>尚未获准的工作投影</span><strong>{item.missing_projections.join("、") || "当前投影引用完整"}</strong></div>
        <button type="button" className="boss-btn" disabled={busy || data.pending_activations.length > 0 || (!item.enabled && (item.missing_tools.length > 0||item.missing_projections.length>0))}
          aria-label={(item.enabled ? "停用方法 " : "启用方法 ") + item.sop_id}
          onClick={() => {setPending(item); setConfirmed(false); setError("");}}>{item.enabled ? "停用方法" : "启用方法"}</button>
      </section>)}
    </div></div>}
    <DialogPrimitive.Root open={pending !== null} onOpenChange={open => {if (!open && !busy) {setPending(null); setConfirmed(false);}}}>
      <DialogPrimitive.Portal container={surface.current}><DialogPrimitive.Overlay className="boss-confirm-backdrop"/>
        <DialogPrimitive.Content className="boss-confirm boss-navigation-confirm">
          <DialogPrimitive.Title asChild><h3>{pending?.enabled ? "确认停用方法" : "确认启用方法"}</h3></DialogPrimitive.Title>
          <DialogPrimitive.Description asChild><p>{pending?.sop_id} · v{pending?.version}。本次只修改后续上下文的方法采用状态，业务授权继续独立核查。</p></DialogPrimitive.Description>
          <label className="boss-confirm-check"><input type="checkbox" checked={confirmed} disabled={busy} onChange={event => setConfirmed(event.target.checked)}/>我确认本次方法状态变更。</label>
          <div className="boss-actions"><button type="button" className="boss-btn" disabled={busy} onClick={() => setPending(null)}>取消变更</button>
            <button type="button" className="boss-btn boss-btn-primary" disabled={!confirmed || busy} onClick={() => {void update();}}>确认变更</button></div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  </div>;
}
