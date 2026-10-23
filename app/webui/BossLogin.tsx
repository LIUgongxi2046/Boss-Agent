import { useEffect, useRef, useState, type FormEvent } from "react";
import { ArrowRight, Eye, EyeOff, Loader2, ShieldCheck } from "lucide-react";
import "./boss-v6.css";
import { fetchBootstrap, BootstrapAuthRequiredError, clearSavedSecret } from "@/lib/bootstrap";

let requestedRole: Role | null = null;

export async function bossFetchBootstrap(baseUrl = "", secret = "", timeoutMs = 15000) {
  const boot = await fetchBootstrap(baseUrl, secret, timeoutMs);
  if (!boot.api_token) throw new Error("认证服务没有返回访问令牌");
  const response = await fetch("/api/boss/identity", {
    headers: { Authorization: "Bearer " + boot.api_token }, cache: "no-store", signal: AbortSignal.timeout(timeoutMs),
  });
  if (!response.ok) throw new BootstrapAuthRequiredError("身份认证已失效");
  const identity = await response.json() as { role: Role | null };
  if (identity.role !== "BOSS" && identity.role !== "MAINTAINER") throw new BootstrapAuthRequiredError("身份范围无效");
  if (requestedRole && requestedRole !== identity.role) throw new Error("身份范围与所选入口不符");
  return boot;
}

export function bossClearSavedSecret() {
  requestedRole = null;
  clearSavedSecret();
}

type Role = "BOSS" | "MAINTAINER";
type Props = {
  mode?: "auth" | "loading" | "error";
  failed?: boolean; expired?: boolean; message?: string;
  onSecret: (secret: string, expectedRole: Role) => void;
};

export function BossLogin({ mode = "auth", failed = false, expired = false, message = "", onSecret }: Props) {
  const [role, setRole] = useState<Role>("BOSS");
  const [value, setValue] = useState("");
  const [visible, setVisible] = useState(false);
  const [validation, setValidation] = useState("");
  const [assetError, setAssetError] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const submitted = useRef(false);
  const busy = mode === "loading";
  const error = validation || (failed ? "访问凭据无效或已失效，请重新输入。" :
    mode === "error" ? message.includes("身份范围") ? "凭据身份与所选入口不符，请核查入口与访问凭据。" : "无法完成认证连接，请检查本机服务后重新尝试。" : "");

  useEffect(() => {
    if (!busy) {
      submitted.current = false;
      if (failed || expired || mode === "error") input.current?.focus();
    }
  }, [busy, failed, expired, mode]);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || submitted.current) return;
    if (!value.trim()) {
      setValidation("请输入本机访问凭据。");
      input.current?.focus();
      return;
    }
    submitted.current = true;
    setValidation("");
    requestedRole = role;
    onSecret(value.trim(), role);
  }

  return <main className="boss-v6 boss-login" aria-busy={busy}>
    <div className="boss-login-content">
    <header className="boss-login-brand">
      <img src="/boss-brand/boss-logo-from-reference.png" alt="Boss Agent 标识" onError={() => setAssetError(true)}/>
      <strong>Boss Agent</strong><span>大鹏 · 个人秘书</span>
    </header>
    <div className="boss-login-layout">
      <section className="boss-login-welcome" aria-labelledby="boss-login-brand-title">
        <span className="boss-login-accent"/>
        <h1 id="boss-login-brand-title">让重要的事，<br/>推进得更确定。</h1>
        <p>在本人授权的范围内，持续处理安排、资料与待办。</p>
        <img src="/boss-brand/dapeng-front.png" alt="大鹏吉祥物" onError={() => setAssetError(true)}/>
        <span className="boss-login-local"><ShieldCheck size={18} aria-hidden="true"/>本机桌面 · 身份分别核验</span>
      </section>
      <section className="boss-login-card" aria-labelledby="boss-login-title">
        <p className="boss-login-eyebrow">{expired ? "重新认证 · D08" : "欢迎使用 · N01"}</p>
        <h2 id="boss-login-title">{expired ? "登录状态已过期" : "登录 Boss Agent"}</h2>
        <p className="boss-login-description">{expired ? "重新核验当前权限后，可以查询已有运行结果。未完成的业务动作不会自动重新发送。" : "请选择访问入口，使用本机配置的访问凭据认证。"}</p>
        <form onSubmit={submit} noValidate>
          <fieldset disabled={busy} className="boss-login-choices">
            <legend>访问入口</legend>
            {([["BOSS", "老板本人", "本人决定与日常工作"], ["MAINTAINER", "技术维护", "配置、模拟与运行检查"]] as const).map(([id, title, note]) =>
              <label key={id} className={"boss-login-choice " + (role === id ? "selected" : "")}>
                <input type="radio" name="boss-login-role" value={id} checked={role === id} onChange={() => setRole(id)}/>
                <span><strong>{title}</strong><small>{note}</small></span>
              </label>)}
          </fieldset>
          <label className="boss-login-label" htmlFor="boss-login-secret">本机访问凭据</label>
          <div className="boss-login-input">
            <input ref={input} id="boss-login-secret" name="boss-login-secret" type={visible ? "text" : "password"}
              autoComplete="current-password" autoCapitalize="none" spellCheck={false} value={value} disabled={busy}
              aria-invalid={!!error} aria-describedby={error ? "boss-login-help boss-login-error" : "boss-login-help"}
              onChange={event => { setValue(event.target.value); setValidation(""); }}
              onKeyDown={event => { if (event.key === "Enter" && event.nativeEvent.isComposing) event.preventDefault(); }}/>
            <button type="button" disabled={busy} aria-controls="boss-login-secret" aria-label={visible ? "隐藏访问凭据" : "显示访问凭据"}
              onClick={() => setVisible(current => !current)}>{visible ? <EyeOff size={19}/> : <Eye size={19}/>}</button>
          </div>
          <p id="boss-login-help" className="boss-login-help">身份与访问范围由服务端确认，入口选择不授予权限。</p>
          {error && <p id="boss-login-error" role="alert" className="boss-login-error">{error}</p>}
          <button className="boss-login-submit" type="submit" disabled={busy}>
            {busy ? <Loader2 className="boss-spin" size={19}/> : <ArrowRight size={19}/>}
            {busy ? "正在核验身份…" : expired ? "重新认证" : "继续认证"}
          </button>
          <p className="boss-login-status" role="status" aria-live="polite">{busy ? "正在连接本机认证服务，请稍候。" : "通过认证后进入相应工作区域。"}</p>
          {expired && <button className="boss-btn" type="button" onClick={() => window.location.reload()}>返回登录</button>}
        </form>
        <details className="boss-login-assistance"><summary>认证帮助</summary>
          <p>访问凭据由本机服务配置提供。请使用所属身份的有效凭据；外部联系人没有登录权限。</p>
          <p>本机服务需要保持运行。模型与语音服务需要相应网络连接。</p>
        </details>
        {assetError && <p role="alert" className="boss-login-error">品牌资源加载失败，请检查本机产品构建。</p>}
      </section>
    </div>
    </div>
  </main>;
}
