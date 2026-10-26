import {useEffect,useRef,useState} from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {ChevronRight,LogOut,Power,RefreshCw} from "lucide-react";
import {useClient} from "@/providers/ClientProvider";
import {V7Fact,V7Panel,V7ReadState} from "./BossV7UI";

type Snapshot={
  source_type:"SIMULATED";projection:"owner-goals"|"owner-notice";
  active:{version:string;state:string;content:Record<string,unknown>}|null;
  active_is_effective:boolean;
};
type Host={platform:string;microphone:string;notifications_supported:boolean;auto_start:boolean|null;auto_update:boolean;background_mode:string};
type Bridge={invoke:((request:{action:"status"})=>Promise<Host>)&((request:{action:"quit";token:string})=>Promise<{requested:boolean}>)};
type Props={onNavigate:(page:string)=>void;onLogout:()=>void;refreshVersion?:number};
const MICROPHONE:Record<string,string>={"not-determined":"尚未请求许可",granted:"系统已许可",denied:"系统已拒绝",restricted:"系统限制访问",unknown:"系统未提供许可状态"};
function enabled(value:boolean|null|undefined){return value===true?"已启用":value===false?"未启用":"尚未取得状态";}
function version(value:Snapshot|null){return value?value.active?"v"+value.active.version+(value.active_is_effective?" · 当前有效":" · 当前未生效"):"尚无本人确认版本":"尚未读取";}

export function BossSettingsHub(props:Props){
  const {token}=useClient(),identity=useRef({token,sequence:0});
  if(identity.current.token!==token)identity.current={token,sequence:identity.current.sequence+1};
  return <SettingsHub key={identity.current.sequence} {...props}/>;
}

function SettingsHub({onNavigate,onLogout,refreshVersion}:Props){
  const {getToken}=useClient();
  const [goals,setGoals]=useState<Snapshot|null>(null),[notice,setNotice]=useState<Snapshot|null>(null);
  const [loading,setLoading]=useState(true),[error,setError]=useState(""),[revision,setRevision]=useState(0);
  const [host,setHost]=useState<Host|null>(null),[hostBusy,setHostBusy]=useState(false),[hostError,setHostError]=useState(""),[hostReadAt,setHostReadAt]=useState("");
  const [quitOpen,setQuitOpen]=useState(false),[quitBusy,setQuitBusy]=useState(false),[quitError,setQuitError]=useState(""),[quitRequested,setQuitRequested]=useState(false);
  const hostSequence=useRef(0),quitSequence=useRef(0);
  const native=(window as Window&{bossDesktop?:Bridge}).bossDesktop;
  useEffect(()=>()=>{hostSequence.current++;quitSequence.current++;},[]);
  useEffect(()=>{
    const controller=new AbortController();setLoading(true);setError("");setGoals(null);setNotice(null);
    const token=getToken();
    if(!token){setError("当前会话已失效");setLoading(false);return;}
    void Promise.all((["owner-goals","owner-notice"] as const).map(async key=>{
      const response=await fetch("/api/boss/ui/workspace/"+key,{headers:{Authorization:"Bearer "+token},cache:"no-store",signal:controller.signal});
      if(response.status===401)window.dispatchEvent(new Event("boss-auth-expired"));
      if(!response.ok)throw new Error("设置读取失败，HTTP "+response.status);
      const value=await response.json() as Snapshot;
      if(value.source_type!=="SIMULATED"||value.projection!==key||typeof value.active_is_effective!=="boolean")throw new Error("设置来源或页面范围不匹配");
      if(value.active_is_effective&&!value.active)throw new Error("有效设置缺少本人确认版本");
      return value;
    })).then(([a,b])=>{if(!controller.signal.aborted){setGoals(a);setNotice(b);setLoading(false);}}).catch(failure=>{if(!controller.signal.aborted){setError(failure.message);setLoading(false);}});
    return()=>controller.abort();
  },[getToken,revision,refreshVersion]);
  async function readHost(){
    if(!native||hostBusy)return;
    const sequence=++hostSequence.current;setHostBusy(true);setHost(null);setHostError("");setHostReadAt("");
    await native.invoke({action:"status"}).then(value=>{
      if(sequence!==hostSequence.current)return;
      if(typeof value.platform!=="string"||typeof value.microphone!=="string"||typeof value.notifications_supported!=="boolean"||typeof value.background_mode!=="string"||(value.auto_start!==null&&typeof value.auto_start!=="boolean")||typeof value.auto_update!=="boolean")throw new Error("桌面设置状态不完整");
      setHost(value);setHostReadAt(new Date().toISOString());
    }).catch(failure=>{if(sequence===hostSequence.current)setHostError(failure.message);}).finally(()=>{if(sequence===hostSequence.current)setHostBusy(false);});
  }
  async function requestQuit(){
    if(!native||quitBusy)return;
    const sequence=++quitSequence.current;setQuitBusy(true);setQuitError("");setQuitRequested(false);
    const token=getToken();
    if(!token){setQuitError("当前会话已失效，请重新认证后操作。");setQuitBusy(false);return;}
    await native.invoke({action:"quit",token}).then(value=>{
      if(sequence!==quitSequence.current)return;
      if(value.requested!==true)throw new Error("宿主未确认退出请求，请核查当前窗口状态。");
      setQuitRequested(true);setQuitOpen(false);
    }).catch(failure=>{if(sequence===quitSequence.current)setQuitError(failure.message);}).finally(()=>{if(sequence===quitSequence.current)setQuitBusy(false);});
  }
  const notificationSetting=notice?.active_is_effective?typeof notice.active?.content.notifications_enabled==="boolean"?notice.active.content.notifications_enabled?"本人要求允许提醒":"本人要求暂停提醒":"当前版本未提供通知开关":notice?"尚无有效本人通知要求":"尚未读取本人通知要求";
  const entries=[
    {page:"N07",title:"本人目标与关注要求",detail:"目标、关注事项、阅读要求及适用范围",state:version(goals)},
    {page:"N08",title:"通知要求与可见范围",detail:"提醒时段、免打扰及系统通知预览",state:version(notice)},
    {page:"F13",title:"个人长期记忆",detail:"本人确认、修改和删除个人要求",state:"查看有效版本及后续采用"},
    {page:"N09",title:"本人计划",detail:"安排时间、事项复查及执行结果",state:"查看当前计划与实际执行"},
    {page:"N10",title:"本人授权记录",detail:"当前动作、授权范围及撤销",state:"查看当前有效授权"},
    {page:"F12",title:"私人安排",detail:"私人正文与仅含busy的分享范围",state:"查看逐对象分享授权"},
    {page:"N11",title:"历史决定",detail:"本人原决定、原版本和当前事项",state:"查看原始记录与后续结果"},
  ];
  return <div className="boss-settings-view">
    <V7ReadState loading={loading} error={error} onReload={()=>setRevision(value=>value+1)}/>
    <div className="boss-settings-columns"><div className="boss-column">
      <V7Panel title="桌面与权限"><div className="boss-form-grid boss-settings-fields">
        <label>应用内通知<input readOnly value={notificationSetting}/></label>
        <label>系统通知许可<input readOnly value={native?"宿主尚未提供全局许可结果":"需要桌面应用读取"}/></label>
        <label>麦克风许可<input readOnly value={host?MICROPHONE[host.microphone]??host.microphone:native?"尚未读取":"需要桌面应用读取"}/></label>
        <label>后台运行<input readOnly value={host?host.background_mode==="QUIT_WITH_LAST_WINDOW"?"关闭最后窗口时请求完整退出":host.background_mode:"尚未读取"}/></label>
        <label>开机自启动<input readOnly value={enabled(host?.auto_start)}/></label>
        <label>自动更新<input readOnly value={enabled(host?.auto_update)}/></label>
      </div><div className="boss-actions"><button className="boss-btn boss-btn-primary" onClick={()=>onNavigate("N08")}>通知隐私设置</button><button className="boss-btn" disabled title="当前桌面宿主尚未提供平台权限管理入口">打开系统权限管理</button><button className="boss-btn" disabled={!native||hostBusy} onClick={()=>void readHost()}><RefreshCw size={15}/>{hostBusy?"正在读取":"读取桌面状态"}</button></div>
        <p className="boss-v7-note">应用内通知中心可以查看获准事项。系统通知的支持情况、全局许可和具体显示结果分别核查。语音服务当前暂停。</p>
        <V7ReadState loading={hostBusy} error={hostError} onReload={()=>void readHost()}/>
      </V7Panel>
      <V7Panel title="会话退出与完整退出"><V7Fact label="退出登录">清除受限界面，保留应用窗口</V7Fact><V7Fact label="完整退出应用">请求停止本地服务、调度及未执行动作</V7Fact><V7Fact label="已确认内容">继续保留，未知结果重新核查</V7Fact><div className="boss-actions"><button className="boss-btn" onClick={onLogout}><LogOut size={16}/>退出登录</button><button className="boss-btn boss-btn-danger" disabled={!native||quitBusy} onClick={()=>{setQuitError("");setQuitOpen(true);}}><Power size={16}/>完整退出应用</button></div>
        {!native&&<p className="boss-v7-note">浏览器入口可以退出登录。完整退出由桌面应用处理。</p>}
        {quitRequested&&<p role="status">宿主已接收退出请求；请完成窗口中的未保存内容确认。当前业务结果仍以正式记录为准。</p>}
      </V7Panel>
    </div><aside className="boss-column"><V7Panel title="设置应用状态"><V7Fact label="当前身份">本人</V7Fact><V7Fact label="目标有效版本">{version(goals)}</V7Fact><V7Fact label="通知有效版本">{version(notice)}</V7Fact><V7Fact label="当前入口">{native?"桌面应用":"浏览器"}</V7Fact><V7Fact label="系统通知能力">{host?host.notifications_supported?"系统支持":"系统不支持":"尚未读取"}</V7Fact><V7Fact label="系统权限检查时间">{hostReadAt?new Intl.DateTimeFormat("zh-CN",{timeZone:"Asia/Shanghai",dateStyle:"short",timeStyle:"medium"}).format(new Date(hostReadAt))+" · Asia/Shanghai":"尚未检查"}</V7Fact><p className="boss-v7-note">当前检查仅包含宿主已返回的状态。本人要求的保存、确认及后续任务采用分别查看。本地运行与交接需要技术维护身份访问。</p><div className="boss-actions"><button className="boss-btn" disabled={loading} onClick={()=>setRevision(value=>value+1)}>重读有效设置</button><button className="boss-btn" disabled title="需要技术维护身份">本地运行与交接</button><button className="boss-btn" onClick={()=>onNavigate("F01")}>返回今日</button></div></V7Panel></aside></div>
    <V7Panel title="本人设置入口" description="查看本人要求、资料范围、当前事项及后续结果。"><div className="boss-settings-links">{entries.map(entry=><button key={entry.page} className="boss-settings-link" onClick={()=>onNavigate(entry.page)}><span><strong>{entry.title}</strong><span>{entry.detail}</span><small>{entry.state}</small></span><ChevronRight size={17}/></button>)}</div></V7Panel>
    <Dialog.Root open={quitOpen} onOpenChange={open=>{if(!quitBusy)setQuitOpen(open);}}><Dialog.Portal><Dialog.Overlay className="boss-v7-dialog-overlay"/><Dialog.Content className="boss-v7-dialog" onEscapeKeyDown={event=>{if(quitBusy)event.preventDefault();}} onPointerDownOutside={event=>{if(quitBusy)event.preventDefault();}}><Dialog.Title>确认完整退出应用</Dialog.Title><Dialog.Description>完整退出将请求停止本地服务。已经确认的业务记录继续保留，尚未确定的执行结果需要在下次进入时重新核查。</Dialog.Description><V7Fact label="本地调度">将停止</V7Fact><V7Fact label="录音采集">随应用退出停止；语音服务当前暂停</V7Fact><V7Fact label="未执行动作">将停止</V7Fact><V7Fact label="已保存记录">继续保留</V7Fact><p>未保存的编辑由当前窗口继续确认。取消退出保留当前页面。</p>{quitError&&<p role="alert" className="boss-status boss-status-error">{quitError}</p>}<div className="boss-actions"><Dialog.Close asChild><button className="boss-btn" disabled={quitBusy}>取消退出</button></Dialog.Close><button className="boss-btn boss-btn-danger" disabled={quitBusy||!native} onClick={()=>void requestQuit()}>{quitBusy?"正在请求退出":"确认完整退出"}</button></div></Dialog.Content></Dialog.Portal></Dialog.Root>
  </div>;
}
