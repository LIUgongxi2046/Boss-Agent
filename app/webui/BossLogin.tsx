import { useEffect, useRef, useState, type FormEvent } from "react";
import { ArrowRight, Eye, EyeOff, Loader2, ShieldCheck } from "lucide-react";
import "./boss-v6.css";
import "./boss-login.css";
import { BootstrapAuthRequiredError, clearSavedSecret } from "@/lib/bootstrap";
import type { BootstrapResponse } from "@/lib/types";

let requestedRole: Role | null = null;

export async function bossFetchBootstrap(baseUrl = "", secret = "", timeoutMs = 15000,
  account?: { username: string; password: string; role: Role }) {
  const headers: Record<string, string> = account ? {
    "X-Boss-Username": account.username, "X-Boss-Password": account.password, "X-Boss-Role": account.role,
  } : secret ? { Authorization: "Bearer " + secret } : {};
  const result = await fetch(baseUrl + "/webui/bootstrap", {
    headers, credentials: "same-origin", cache: "no-store", signal: AbortSignal.timeout(timeoutMs),
  });
  if (result.status === 401 || result.status === 403) throw new BootstrapAuthRequiredError("账号或密码无效");
  if (!result.ok) throw new Error("认证服务连接失败");
  const boot = await result.json() as BootstrapResponse;
  if (!boot.ws_path) throw new Error("认证服务没有返回会话路径");
  if (!boot.api_token) throw new Error("认证服务没有返回访问令牌");
  const response = await fetch(baseUrl + "/api/boss/identity", {
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

export function BossLogin({ mode = "auth", failed = false, expired: expiredProp = false, message = "", onSecret }: Props) {
  const expired = expiredProp || failed;
  const [role, setRole] = useState<Role>("BOSS");
  const [username, setUsername] = useState("");
  const [value, setValue] = useState("");
  const [visible, setVisible] = useState(false);
  const [validation, setValidation] = useState("");
  const [assetError, setAssetError] = useState(false);
  const [pending, setPending] = useState(false);
  const [reducedMotion, setReducedMotion] = useState(() => window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  const input = useRef<HTMLInputElement>(null);
  const surface = useRef<HTMLElement>(null);
  const mascot = useRef<HTMLImageElement>(null);
  const submitted = useRef(false);
  const busy = mode === "loading" || pending;
  const error = validation || (failed ? "登录状态已失效，请重新认证。" :
    mode === "error" ? message.includes("身份范围") ? "账号身份与当前入口不符。" : "无法完成认证连接，请检查本机服务后重新尝试。" : "");

  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReducedMotion(media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    const page = surface.current;
    const image = mascot.current;
    if (reducedMotion || !page || !image) return;
    let animation: Animation | null = null;
    let stopped = false;
    let completed = 0;
    const random = (minimum: number, maximum: number) => minimum + Math.random() * (maximum - minimum);
    function fly() {
      if (stopped || !page || !image) return;
      const bounds = page.getBoundingClientRect();
      const current = image.getBoundingClientRect();
      const scale = bounds.width / page.clientWidth;
      const marginX = image.offsetWidth / 2 + 24;
      const marginY = image.offsetHeight / 2 + 24;
      const maximumX = Math.max(marginX, page.clientWidth - marginX);
      const maximumY = Math.max(marginY, page.clientHeight - marginY);
      const clamp = (value: number, minimum: number, maximum: number) => Math.max(minimum, Math.min(maximum, value));
      const startX = completed ? clamp((current.left + current.width / 2 - bounds.left) / scale, marginX, maximumX) : marginX;
      const startY = completed ? clamp((current.top + current.height / 2 - bounds.top) / scale, marginY, maximumY) : (marginY + maximumY) / 2;
      if (animation) { animation.onfinish = null; animation.cancel(); }
      const targetX = random(marginX, maximumX);
      const targetY = random(marginY, maximumY);
      image.style.offsetPath = `path("M ${startX} ${startY} C ${random(marginX, maximumX)} ${random(marginY, maximumY)}, ${random(marginX, maximumX)} ${random(marginY, maximumY)}, ${targetX} ${targetY}")`;
      animation = image.animate([{ offsetDistance: "0%" }, { offsetDistance: "100%" }], {
        duration: random(8000, 14000), easing: "ease-in-out", fill: "forwards",
      });
      image.dataset.flight = "active";
      image.dataset.flightLeg = String(++completed);
      animation.onfinish = fly;
      if (document.hidden) animation.pause();
    }
    function visibility() {
      if (document.hidden) animation?.pause();
      else animation?.play();
    }
    const observer = new ResizeObserver(fly);
    observer.observe(page);
    document.addEventListener("visibilitychange", visibility);
    return () => {
      stopped = true;
      observer.disconnect();
      document.removeEventListener("visibilitychange", visibility);
      if (animation) { animation.onfinish = null; animation.cancel(); }
    };
  }, [reducedMotion]);

  useEffect(() => {
    if (!busy) {
      submitted.current = false;
      if (failed || expired || mode === "error") input.current?.focus();
    }
  }, [busy, failed, expired, mode]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || submitted.current) return;
    if (!username.trim() || !value) {
      setValidation(!username.trim() ? "请输入账号。" : "请输入密码。");
      input.current?.focus();
      return;
    }
    submitted.current = true;
    setValidation("");
    requestedRole = role;
    if (!/^[\x21-\x7e]{1,64}$/.test(username.trim()) || !/^[\x20-\x7e]{1,72}$/.test(value)) {
      submitted.current = false;
      setValidation("请使用本机配置的有效账号和密码。");
      return;
    }
    setPending(true);
    const boot = await bossFetchBootstrap("", "", 15000, { username: username.trim(), password: value, role })
      .then(result => { setValue(""); return result; }, error => {
        setValue(""); setPending(false); submitted.current = false;
        setValidation(error instanceof BootstrapAuthRequiredError ? "账号或密码无效，或者账号身份与当前入口不符。" : "无法完成认证连接，请检查本机服务后重新尝试。");
        input.current?.focus();
        return null;
      });
    if (!boot?.api_token) return;
    setPending(false);
    onSecret(boot.api_token, role);
  }

  return <main ref={surface} className="boss-v6 boss-login" aria-busy={busy}>
    {!reducedMotion && <div className="boss-login-flight" aria-hidden="true">
      <img ref={mascot} src="/boss-brand/boss-idle.webp" data-motion="animated" alt="" onError={() => setAssetError(true)}/>
    </div>}
    <div className="boss-login-content">
    <header className="boss-login-brand">
      <img src="/boss-brand/boss-logo-from-reference.png" alt="Boss Agent 标识" onError={() => setAssetError(true)}/>
      <strong>Boss Agent</strong><span>老板的AI助理</span><span className="boss-login-beta">内测版本</span>
    </header>
    <div className="boss-login-layout">
      <section className="boss-login-welcome" aria-labelledby="boss-login-brand-title">
        <span className="boss-login-accent"/>
        <h1 id="boss-login-brand-title">公司信息了如指掌，<br/>工作推进有条不紊。</h1>
        <div className="boss-login-mascot-space">
          {reducedMotion && <img src="/boss-brand/dapeng-front.png" data-motion="reduced" alt="大鹏吉祥物" onError={() => setAssetError(true)}/>}
        </div>
        <span className="boss-login-local"><ShieldCheck size={18} aria-hidden="true"/>本机桌面 · 身份分别核验</span>
      </section>
      <section className="boss-login-card" aria-labelledby="boss-login-title">
        <p className="boss-login-eyebrow">{expired ? "重新认证" : "欢迎使用"}</p>
        <h2 id="boss-login-title">{expired ? "登录状态已过期" : role === "MAINTAINER" ? "技术维护登录" : "登录 Boss Agent"}</h2>
        <p className="boss-login-description">{expired ? "请重新登录以继续查询已有工作。" : "使用本机账号和密码登录。"}</p>
        <form onSubmit={submit} noValidate>
          <label className="boss-login-label" htmlFor="boss-login-account">账号</label>
          <div className="boss-login-input boss-login-account"><input ref={input} id="boss-login-account" name="username" autoComplete="username"
            autoCapitalize="none" spellCheck={false} value={username} disabled={busy} maxLength={64}
            aria-invalid={!!error} aria-describedby={error ? "boss-login-error" : undefined}
            onChange={event => { setUsername(event.target.value); setValidation(""); }}/></div>
          <label className="boss-login-label" htmlFor="boss-login-secret">密码</label>
          <div className="boss-login-input">
            <input id="boss-login-secret" name="password" type={visible ? "text" : "password"} maxLength={72}
              autoComplete="current-password" autoCapitalize="none" spellCheck={false} value={value} disabled={busy}
              aria-invalid={!!error} aria-describedby={error ? "boss-login-error" : undefined}
              onChange={event => { setValue(event.target.value); setValidation(""); }}
              onKeyDown={event => { if (event.key === "Enter" && event.nativeEvent.isComposing) event.preventDefault(); }}/>
            <button type="button" disabled={busy} aria-controls="boss-login-secret" aria-label={visible ? "隐藏密码" : "显示密码"}
              onClick={() => setVisible(current => !current)}>{visible ? <EyeOff size={19}/> : <Eye size={19}/>}</button>
          </div>
          {error && <p id="boss-login-error" role="alert" className="boss-login-error">{error}</p>}
          <button className="boss-login-submit" type="submit" disabled={busy}>
            {busy ? <Loader2 className="boss-spin" size={19}/> : <ArrowRight size={19}/>}
            {busy ? "正在登录…" : expired ? "重新认证" : "登录"}
          </button>
          <p className="boss-login-status" role="status" aria-live="polite">{busy ? "正在连接本机认证服务，请稍候。" : "通过认证后进入相应工作区域。"}</p>
          {expired && <button className="boss-btn" type="button" onClick={() => window.location.reload()}>返回登录</button>}
        </form>
        <div className="boss-login-footer">
        <button type="button" className="boss-login-maintenance" disabled={busy} onClick={() => {
          setRole(current => current === "BOSS" ? "MAINTAINER" : "BOSS"); requestedRole = null;
          setValue(""); setUsername(""); setValidation(""); setVisible(false); input.current?.focus();
        }}>{role === "BOSS" ? "技术维护" : "返回本人登录"}</button>
        <details className="boss-login-assistance"><summary>认证帮助</summary>
          <p>请使用本机初始化时提供的账号和密码。账号所属身份由服务端核验。</p>
          <p>本机服务需要保持运行。模型与语音服务需要相应网络连接。</p>
        </details>
        </div>
        {assetError && <p role="alert" className="boss-login-error">品牌资源加载失败，请检查本机产品构建。</p>}
      </section>
    </div>
    </div>
  </main>;
}
