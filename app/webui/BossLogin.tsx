import {useEffect,useRef,useState,type FormEvent} from "react";
import {ArrowRight,Eye,EyeOff,Loader2,Settings,UserRound} from "lucide-react";
import {BootstrapAuthRequiredError,clearSavedSecret} from "@/lib/bootstrap";
import type {BootstrapResponse} from "@/lib/types";
import {deliveredPage} from "./delivered-navigation";
import "./boss-login.css";

type Role="BOSS"|"MAINTAINER";
let requestedRole:Role|null=null;

export async function bossFetchBootstrap(baseUrl="",secret="",timeoutMs=15000,account?:{username:string;password:string;role:Role}){
  const headers:Record<string,string>=account?{"X-Boss-Username":account.username,"X-Boss-Password":account.password,"X-Boss-Role":account.role}:secret?{Authorization:"Bearer "+secret}:{};
  const response=await fetch(baseUrl+"/webui/bootstrap",{headers,credentials:"same-origin",cache:"no-store",signal:AbortSignal.timeout(timeoutMs)});
  if(response.status===401||response.status===403)throw new BootstrapAuthRequiredError("账号或密码无效");
  if(!response.ok)throw new Error("认证服务连接失败");
  const boot=await response.json() as BootstrapResponse;
  if(!boot.ws_path)throw new Error("认证服务没有返回会话路径");
  if(!boot.api_token)throw new Error("认证服务没有返回访问令牌");
  const identityResponse=await fetch(baseUrl+"/api/boss/identity",{headers:{Authorization:"Bearer "+boot.api_token},cache:"no-store",signal:AbortSignal.timeout(timeoutMs)});
  if(!identityResponse.ok)throw new BootstrapAuthRequiredError("身份认证已失效");
  const identity=await identityResponse.json() as {role:Role|null};
  if(identity.role!=="BOSS"&&identity.role!=="MAINTAINER")throw new BootstrapAuthRequiredError("身份范围无效");
  if(requestedRole&&requestedRole!==identity.role)throw new Error("身份范围与所选入口不符");
  return boot;
}

export function bossClearSavedSecret(){requestedRole=null;clearSavedSecret();}

type Props={mode?:"auth"|"loading"|"error";failed?:boolean;expired?:boolean;message?:string;onSecret:(secret:string,expectedRole:Role)=>void};

export function BossLogin({mode="auth",failed=false,expired:expiredProp=false,message="",onSecret}:Props){
  const [returnedToLogin,setReturnedToLogin]=useState(false);
  const expired=(expiredProp||failed)&&!returnedToLogin;
  const [role,setRole]=useState<Role>("BOSS");
  const [username,setUsername]=useState("");
  const [password,setPassword]=useState("");
  const [visible,setVisible]=useState(false);
  const [validation,setValidation]=useState("");
  const [pending,setPending]=useState(false);
  const [helpOpen,setHelpOpen]=useState(false);
  const [assetError,setAssetError]=useState(false);
  const input=useRef<HTMLInputElement>(null);
  const submitted=useRef(false);
  const busy=pending||mode==="loading";
  const error=validation||(failed&&!returnedToLogin?"登录已过期，请重新登录。":mode==="error"?message.includes("身份范围")?"当前账号不能进入所选工作区。":"暂时无法登录，请稍后重试。":"");
  useEffect(()=>{setReturnedToLogin(false);},[expiredProp,failed]);
  function returnLogin(){
    if(busy)return;
    setReturnedToLogin(true);setUsername("");setPassword("");setVisible(false);setValidation("");requestedRole=null;
    const url=new URL(window.location.href);
    if(url.searchParams.get("bossPage")==="D08"){url.searchParams.delete("bossPage");window.history.replaceState(window.history.state,"",url);}
    requestAnimationFrame(()=>input.current?.focus());
  }
  useEffect(()=>{if(!busy){submitted.current=false;if(failed||expired||mode==="error")input.current?.focus();}},[busy,failed,expired,mode]);
  function choose(next:Role){
    if(busy||next===role)return;
    const url=new URL(window.location.href),page=url.searchParams.get("bossPage");
    if(page&&deliveredPage(page,role)&&!deliveredPage(page,next)){url.searchParams.delete("bossPage");window.history.replaceState(window.history.state,"",url);}
    setRole(next);requestedRole=null;setUsername("");setPassword("");setVisible(false);setValidation("");
  }
  async function submit(event:FormEvent){
    event.preventDefault();if(busy||submitted.current)return;
    if(!username.trim()||!password){setValidation(!username.trim()?"请输入账号。":"请输入密码。");input.current?.focus();return;}
    if(!/^[\x21-\x7e]{1,64}$/.test(username.trim())||!/^[\x20-\x7e]{1,72}$/.test(password)){setValidation("请输入有效的账号和密码。");return;}
    submitted.current=true;setPending(true);setValidation("");requestedRole=role;
    await bossFetchBootstrap("","",15000,{username:username.trim(),password,role}).then(boot=>{
      setPassword("");setPending(false);onSecret(boot.api_token!,role);
    },reason=>{
      setPassword("");setPending(false);submitted.current=false;
      setValidation(reason instanceof BootstrapAuthRequiredError?"账号、密码或所选工作区无效。":"暂时无法登录，请稍后重试。");input.current?.focus();
    });
  }
  return <main className="boss-login" data-design="v7" aria-busy={busy}>
    <header className="boss-login-brand"><img src="/boss-brand/boss-logo-from-reference.png" alt="" onError={()=>setAssetError(true)}/><strong>Boss Agent</strong><span>老板的 AI 助理</span><span className="boss-login-service">安全登录</span></header>
    <div className="boss-login-layout"><section className="boss-login-welcome" aria-labelledby="boss-login-brand-title"><img className="boss-login-mascot" src="/boss-brand/dapeng-front.png" alt="大鹏吉祥物" onError={()=>setAssetError(true)}/><h1 id="boss-login-brand-title">Boss Agent</h1><p>让重要的事，推进得更确定。</p><span className="boss-login-accent"/><p className="boss-login-welcome-note">日常工作、经营关注与本人决定</p></section>
      <section className="boss-login-card" aria-labelledby="boss-login-title"><h2 id="boss-login-title">{expired?"登录状态已过期":"欢迎使用 Boss Agent"}</h2><p className="boss-login-description">{expired?"请重新验证身份后继续。":"请使用账号和密码登录。"}</p>
        <fieldset className="boss-login-roles" disabled={busy}><legend>选择身份入口</legend>{([{id:"BOSS",title:"老板本人",note:"授权决策与日常工作",icon:<UserRound size={24}/>},{id:"MAINTAINER",title:"技术维护",note:"配置、模拟与评测",icon:<Settings size={24}/>} ] as const).map(item=><label key={item.id} className={role===item.id?"selected":""}><input type="radio" name="boss-login-role" value={item.id} checked={role===item.id} onChange={()=>choose(item.id)}/>{item.icon}<strong>{item.title}</strong><small>{item.note}</small></label>)}</fieldset>
        <form onSubmit={submit} noValidate><label className="boss-login-field" htmlFor="boss-login-account"><span>账号</span><input ref={input} id="boss-login-account" name="username" autoComplete="username" autoCapitalize="none" spellCheck={false} maxLength={64} disabled={busy} value={username} aria-invalid={!!error} aria-describedby={error?"boss-login-error":undefined} onChange={event=>{setUsername(event.target.value);setValidation("");}}/></label>
          <label className="boss-login-field" htmlFor="boss-login-secret"><span>密码</span><div className="boss-login-input"><input id="boss-login-secret" name="password" type={visible?"text":"password"} autoComplete="current-password" autoCapitalize="none" spellCheck={false} maxLength={72} disabled={busy} value={password} aria-invalid={!!error} aria-describedby={error?"boss-login-error":undefined} onChange={event=>{setPassword(event.target.value);setValidation("");}} onKeyDown={event=>{if(event.key==="Enter"&&event.nativeEvent.isComposing)event.preventDefault();}}/><button type="button" disabled={busy} aria-controls="boss-login-secret" aria-label={visible?"隐藏密码":"显示密码"} onClick={()=>setVisible(value=>!value)}>{visible?<EyeOff size={19}/>:<Eye size={19}/>}</button></div></label>
          {error&&<p id="boss-login-error" className="boss-login-error" role="alert">{error}</p>}
          <button className="boss-login-submit" type="submit" disabled={busy}>{busy?<Loader2 size={18} className="boss-login-spin"/>:<ArrowRight size={18}/>} {busy?"正在认证…":expired?"重新认证":"继续认证"}</button>
          {expired&&<button className="boss-login-secondary" type="button" disabled={busy} onClick={returnLogin}>返回登录</button>}
          <p className="boss-login-status" role="status">{busy?"正在登录…":"登录后进入工作区。"}</p>
        </form>
        <div className="boss-login-footer"><button className="boss-login-secondary" type="button" aria-expanded={helpOpen} aria-controls="boss-login-assistance" onClick={()=>setHelpOpen(value=>!value)}>登录帮助</button></div>
        {helpOpen&&<section id="boss-login-assistance" className="boss-login-assistance"><p>使用分配给你的账号和密码登录。忘记密码请联系管理员。</p></section>}
        {assetError&&<p className="boss-login-error" role="alert">页面资源加载失败，请稍后重试。</p>}
      </section>
    </div>
  </main>;
}
