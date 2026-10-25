import { useEffect, useRef, useState, type FormEvent } from "react";
import { ArrowRight, Eye, EyeOff, Loader2 } from "lucide-react";
import "./boss-v6.css";
import "./boss-login.css";
import { BootstrapAuthRequiredError, clearSavedSecret } from "@/lib/bootstrap";
import type { BootstrapResponse } from "@/lib/types";
import {deliveredPage} from "./delivered-navigation";

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
type DesktopBridge={invoke:(request:Record<string,unknown>)=>Promise<Record<string,unknown>>};
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
  const [helpOpen,setHelpOpen]=useState(false),[demoEnabled,setDemoEnabled]=useState(false),[injecting,setInjecting]=useState(false);
  const accountEpoch=useRef(0);
  const [reducedMotion, setReducedMotion] = useState(() => window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  const input = useRef<HTMLInputElement>(null);
  const surface = useRef<HTMLElement>(null);
  const mascot = useRef<HTMLDivElement>(null);
  const submitted = useRef(false);
  const busy = mode === "loading" || pending || injecting;
  const error = validation || (failed ? "登录状态已失效，请重新认证。" :
    mode === "error" ? message.includes("身份范围") ? "账号身份与当前入口不符。" : "无法完成认证连接，请检查本机服务后重新尝试。" : "");

  useEffect(()=>{const epoch=++accountEpoch.current;const desktop=(window as Window&{bossDesktop?:DesktopBridge}).bossDesktop;if(desktop)void desktop.invoke({action:"status"}).then(status=>{if(epoch===accountEpoch.current)setDemoEnabled(status.demo_account_injection_supported===true);}).catch(()=>{if(epoch===accountEpoch.current)setValidation("无法核查本机测试入口，请使用手动输入。");});return()=>{accountEpoch.current++;};},[role]);
  async function injectAccount(){
    if(!demoEnabled||busy)return;const desktop=(window as Window&{bossDesktop?:DesktopBridge}).bossDesktop;
    if(!desktop){setValidation("当前入口没有本机账号填充能力。");return;}
    const epoch=accountEpoch.current;setInjecting(true);setValidation("");
    await desktop.invoke({action:"test_account",role}).then(account=>{if(epoch!==accountEpoch.current)return;if(account.role!==role||typeof account.username!=="string"||typeof account.password!=="string"||!account.username||!account.password)throw new Error("测试账号返回范围无效");setUsername(account.username);setValue(account.password);setVisible(false);input.current?.focus();}).catch(failure=>{if(epoch===accountEpoch.current)setValidation(failure.message);});
    if(epoch===accountEpoch.current)setInjecting(false);
  }

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
    const facing = image.querySelector<HTMLElement>(".boss-login-bird-facing");
    if (!facing) throw new Error("飞行方向容器缺失");
    const depth = image.querySelector<HTMLElement>(".boss-login-bird-depth");
    if (!depth) throw new Error("飞行远近容器缺失");
    const turn = image.querySelector<HTMLElement>(".boss-login-bird-turn");
    if (!turn) throw new Error("飞行转弯容器缺失");
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    let animation: Animation | null = null;
    let frame = 0;
    let stopped = false;
    let completed = 0;
    let pathLength = 0;
    let nearScale = 0.9;
    let pitch = 0;
    let previousFrame = 0;
    const random = (minimum: number, maximum: number) => minimum + Math.random() * (maximum - minimum);
    const speed = random(70, 84);
    const clamp = (value: number, minimum: number, maximum: number) => Math.max(minimum, Math.min(maximum, value));
    function orient(now: number) {
      frame = 0;
      if (stopped || !image || !facing || !depth || !turn || !animation || document.hidden) return;
      const progress = animation.effect?.getComputedTiming().progress;
      if (progress === null || progress === undefined) throw new Error("飞行动画进度缺失");
      const distance = progress * pathLength;
      const before = path.getPointAtLength(Math.max(0, distance - 1));
      const after = path.getPointAtLength(Math.min(pathLength, distance + 1));
      const dx = after.x - before.x;
      const dy = after.y - before.y;
      const heading = Math.atan2(dy, dx);
      const direction = dx >= 0 ? 1 : -1;
      const targetPitch = clamp(Math.atan2(dy, Math.abs(dx)) * direction, -0.3, 0.3);
      const elapsed = previousFrame ? Math.min((now - previousFrame) / 1000, 0.1) : 0;
      pitch = previousFrame ? pitch + clamp(targetPitch - pitch, -elapsed * Math.PI / 4, elapsed * Math.PI / 4) : targetPitch;
      previousFrame = now;
      const yaw = Math.acos(clamp(dx / Math.hypot(dx, dy), -1, 1));
      const turnBlend = Math.sin(yaw) ** 2;
      const bank = Math.sin(heading) * Math.cos(heading) * 0.3;
      facing.style.transform = `rotate(${pitch}rad) rotateY(${yaw}rad)`;
      facing.style.opacity = String(1 - turnBlend);
      turn.style.transform = `rotate(${bank}rad)`;
      turn.style.opacity = String(turnBlend);
      // 透视距离连续变化，接近与远离的连接位置保持平滑。
      const approach = (1 - Math.cos(progress * Math.PI * 2)) / 2;
      const distanceToCamera = 1 / 0.62 + (1 / nearScale - 1 / 0.62) * approach;
      depth.style.scale = String(1 / distanceToCamera);
      image.dataset.heading = String(heading);
      frame = requestAnimationFrame(orient);
    }
    function fly() {
      if (stopped || !page || !image || !depth) return;
      const left = image.offsetWidth / Math.SQRT2 + 24;
      const top = image.offsetHeight / Math.SQRT2 + 24;
      const right = Math.max(left + 1, page.clientWidth - left);
      const bottom = Math.max(top + 1, page.clientHeight - top);
      const middleY = (top + bottom) / 2;
      const upperX = random(left + (right - left) * 0.35, left + (right - left) * 0.65);
      const lowerX = random(left + (right - left) * 0.35, left + (right - left) * 0.65);
      const rightY = random(top + (bottom - top) * 0.35, top + (bottom - top) * 0.65);
      const curve = 0.5522847498;
      // 连续曲线在连接处保持相同切线，路径动画保持匀速。
      const route = `M ${left} ${middleY} C ${left} ${middleY - (middleY - top) * curve}, ${upperX - (upperX - left) * curve} ${top}, ${upperX} ${top} C ${upperX + (right - upperX) * curve} ${top}, ${right} ${rightY - (rightY - top) * curve}, ${right} ${rightY} C ${right} ${rightY + (bottom - rightY) * curve}, ${lowerX + (right - lowerX) * curve} ${bottom}, ${lowerX} ${bottom} C ${lowerX - (lowerX - left) * curve} ${bottom}, ${left} ${middleY + (bottom - middleY) * curve}, ${left} ${middleY}`;
      path.setAttribute("d", route);
      pathLength = path.getTotalLength();
      const duration = pathLength / speed * 1000;
      nearScale = random(0.86, 0.94);
      if (animation) { animation.onfinish = null; animation.cancel(); }
      image.style.offsetPath = `path("${route}")`;
      animation = image.animate([{ offsetDistance: "0%" }, { offsetDistance: "100%" }], { duration, easing: "linear", fill: "forwards" });
      image.dataset.flight = "active";
      image.dataset.flightLeg = String(++completed);
      image.dataset.depthTarget = String(nearScale);
      animation.onfinish = fly;
      image.style.setProperty("--boss-wing-play-state", document.hidden ? "paused" : "running");
      if (document.hidden) animation.pause();
      else if (!frame) frame = requestAnimationFrame(orient);
    }
    function visibility() {
      image?.style.setProperty("--boss-wing-play-state", document.hidden ? "paused" : "running");
      if (document.hidden) {
        animation?.pause(); cancelAnimationFrame(frame); frame = 0; previousFrame = 0;
      } else {
        animation?.play();
        if (!frame) frame = requestAnimationFrame(orient);
      }
    }
    const observer = new ResizeObserver(fly);
    observer.observe(page);
    document.addEventListener("visibilitychange", visibility);
    return () => {
      stopped = true;
      observer.disconnect();
      document.removeEventListener("visibilitychange", visibility);
      cancelAnimationFrame(frame);
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
      <div ref={mascot} className="boss-login-flying-bird" data-motion="animated">
        <div className="boss-login-bird-depth">
          <div className="boss-login-bird-facing"><div className="boss-login-bird-frame"><img src="/boss-brand/boss-flight-sprite.png" data-flap="eight-frame" alt="" onError={() => setAssetError(true)}/></div></div>
          <div className="boss-login-bird-turn"><div className="boss-login-bird-frame"><img src="/boss-brand/boss-flight-sprite.png" data-flap="turn-frame" alt="" onError={() => setAssetError(true)}/></div></div>
        </div>
      </div>
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
      </section>
      <section className="boss-login-card" aria-labelledby="boss-login-title">
        <p className="boss-login-eyebrow">{expired ? "重新认证" : "欢迎使用"}</p>
        <h2 id="boss-login-title">{expired ? "登录状态已过期" : role === "MAINTAINER" ? "技术维护登录" : "登录 Boss Agent"}</h2>
        <p className="boss-login-description">{expired ? "请重新登录以继续查询已有工作。" : "使用本机账号和密码登录。"}</p>
        <form onSubmit={submit} noValidate>
          <div className="boss-login-field">
          <label className="boss-login-label" htmlFor="boss-login-account">账号</label>
          <div className="boss-login-input boss-login-account"><input ref={input} id="boss-login-account" name="username" autoComplete="username"
            autoCapitalize="none" spellCheck={false} value={username} disabled={busy} maxLength={64}
            aria-invalid={!!error} aria-describedby={error ? "boss-login-error" : undefined}
            onChange={event => { setUsername(event.target.value); setValidation(""); }}/></div>
          </div>
          <div className="boss-login-field">
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
          </div>
          {error && <p id="boss-login-error" role="alert" className="boss-login-error">{error}</p>}
          {demoEnabled&&<button className="boss-login-secondary boss-login-test" type="button" disabled={busy} onClick={()=>void injectAccount()}>测试账号注入</button>}
          <button className="boss-login-submit" type="submit" disabled={busy}>
            {busy ? <Loader2 className="boss-spin" size={19}/> : <ArrowRight size={19}/>}
            {busy ? "正在登录…" : expired ? "重新认证" : "登录"}
          </button>
          <p className="boss-login-status" role="status" aria-live="polite">{busy ? "正在连接本机认证服务，请稍候。" : "通过认证后进入相应工作区域。"}</p>
          {expired && <button className="boss-btn" type="button" onClick={() => window.location.reload()}>返回登录</button>}
        </form>
        <div className="boss-login-footer">
        <button type="button" className="boss-login-secondary boss-login-maintenance" disabled={busy} onClick={() => {
          const nextRole=role==="BOSS"?"MAINTAINER":"BOSS";setRole(nextRole);requestedRole=null;
          const url=new URL(window.location.href),selected=url.searchParams.get("bossPage");if(selected&&deliveredPage(selected,role)&&!deliveredPage(selected,nextRole)){url.searchParams.delete("bossPage");window.history.replaceState(window.history.state,"",url);}
          setValue(""); setUsername(""); setValidation(""); setVisible(false); input.current?.focus();
        }}>{role === "BOSS" ? "技术维护" : "返回本人登录"}</button>
        <button type="button" className="boss-login-secondary" disabled={busy} aria-expanded={helpOpen} aria-controls="boss-login-assistance" onClick={()=>setHelpOpen(current=>!current)}>认证帮助</button>
        </div>
        {helpOpen&&<section id="boss-login-assistance" className="boss-login-assistance" aria-label="认证帮助内容">
          <p>请使用本机初始化时提供的账号和密码。账号所属身份由服务端核验。</p>
          <p>本机服务需要保持运行。模型与语音服务需要相应网络连接。</p>
        </section>}
        {assetError && <p role="alert" className="boss-login-error">品牌资源加载失败，请检查本机产品构建。</p>}
      </section>
    </div>
    </div>
  </main>;
}
