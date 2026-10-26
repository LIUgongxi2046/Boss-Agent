import {useEffect,useRef,useState} from "react";
import {useClient} from "@/providers/ClientProvider";

type Target={event_id:string;event_version:string;execution_namespace:string};
type NativeState={supported:boolean;permission:"NOT_REPORTED_BY_SYSTEM"|"DENIED_BY_SYSTEM";state:string;failure_reason?:string|null;external_delivery_verified:false};
type Bridge={invoke:(request:Record<string,unknown>)=>Promise<NativeState>;onNotificationOpen?:(listener:(target:Target)=>void)=>()=>void};
function bridge(){return (window as Window&{bossDesktop?:Bridge}).bossDesktop;}
type NotificationHost={platform:string;notifications_supported:boolean};
export function BossNotificationPermissions(){
  const [host,setHost]=useState<NotificationHost|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState(""),[readAt,setReadAt]=useState("");
  const sequence=useRef(0);
  useEffect(()=>()=>{sequence.current++;},[]);
  const native=(window as Window&{bossDesktop?:{invoke:(request:{action:"status"})=>Promise<NotificationHost>}}).bossDesktop;
  async function read(){
    if(!native||busy)return;
    const current=++sequence.current;setBusy(true);setHost(null);setError("");setReadAt("");
    await native.invoke({action:"status"}).then(value=>{if(current!==sequence.current)return;if(typeof value.notifications_supported!=="boolean"||typeof value.platform!=="string")throw new Error("桌面通知能力状态不完整");setHost(value);setReadAt(new Date().toISOString());}).catch(failure=>{if(current===sequence.current)setError(failure.message);}).finally(()=>{if(current===sequence.current)setBusy(false);});
  }
  return <section className="boss-notification-permissions" aria-label="系统通知许可与能力">
    <div className="boss-kv"><span>当前入口</span><strong>{native?"桌面应用":"浏览器"}</strong></div>
    <div className="boss-kv"><span>系统通知能力</span><strong>{host?host.notifications_supported?"系统支持":"系统不支持":"尚未读取"}</strong></div>
    <div className="boss-kv"><span>全局通知许可</span><strong>当前宿主未提供直接读取结果</strong></div>
    <div className="boss-kv"><span>检查时间</span><strong>{readAt||"尚未检查"}</strong></div>
    <button className="boss-btn" disabled={busy||!native} onClick={()=>void read()}>{busy?"正在读取系统状态":"查看系统通知权限"}</button>
    <p className="boss-v7-note">{native?"当前读取检查系统支持情况。具体事项的显示或拒绝结果可在通知中心核查。":"请在桌面应用中检查系统通知，当前可继续使用应用内通知中心。"}</p>
    {error&&<p role="alert" className="boss-status boss-status-error">{error}</p>}
  </section>;
}
const LABELS:Record<string,string>={NOT_REQUESTED:"尚未请求",REQUESTED:"已经请求，系统结果待核查",SHOWN:"系统报告已经显示",FAILED:"系统报告显示失败",CLICKED:"已经打开通知"};

export function BossNativeNotification({eventId,eventVersion}:{eventId:string;eventVersion:string}){
  const {getToken,token}=useClient();
  const [approved,setApproved]=useState(false),[busy,setBusy]=useState(false),[state,setState]=useState<NativeState|null>(null),[error,setError]=useState("");
  const epoch=useRef(0);
  useEffect(()=>{epoch.current++;setApproved(false);setState(null);setError("");setBusy(false);return()=>{epoch.current++;};},[eventId,eventVersion,token]);
  async function invoke(action:"notify_event"|"retry_notification"|"notification_status"){
    if(busy||action!=="notification_status"&&!approved)return;
    const native=bridge();if(!native){setError("当前入口没有桌面通知能力，请在已启动的桌面应用中检查。");return;}
    const current=epoch.current;setBusy(true);setError("");
    await native.invoke({action,token:getToken(),event_id:eventId,event_version:eventVersion}).then(value=>{
      if(current===epoch.current){setState(value);setApproved(false);}
    }).catch(failure=>{if(current===epoch.current)setError(failure instanceof Error?failure.message:String(failure));});
    if(current===epoch.current)setBusy(false);
  }
  return <section className="boss-native-notification" aria-label="当前事项的系统通知">
    <p>系统通知只显示应用名称、经营提醒类别和返回入口。通知中心记录与系统显示分别核查。</p>
    <label className="boss-confirm-check"><input type="checkbox" checked={approved} disabled={busy} onChange={event=>setApproved(event.target.checked)}/>本人请求显示当前事项的系统通知</label>
    <div className="boss-actions"><button type="button" className="boss-btn" disabled={busy||!approved} onClick={()=>void invoke("notify_event")}>请求系统通知</button><button type="button" className="boss-btn" disabled={busy} onClick={()=>void invoke("notification_status")}>检查系统通知状态</button></div>
    {state?.state==="FAILED"&&<button type="button" className="boss-btn" disabled={busy||!approved} onClick={()=>void invoke("retry_notification")}>本人重新请求失败的通知</button>}
    {state&&<p role="status">当前系统{state.supported?"支持":"不支持"}通知 · {LABELS[state.state]??state.state}。{state.permission==="DENIED_BY_SYSTEM"?"系统已经拒绝当前应用显示通知。":"系统权限未提供直接读取结果。"}请在应用内核查并处理当前事项。</p>}
    {state?.failure_reason&&<p role="alert" className="boss-status boss-status-error">系统报告：{state.failure_reason}</p>}
    {error&&<p role="alert" className="boss-status boss-status-error">{error}</p>}
  </section>;
}

export function BossNotificationReturn({role,onOpen}:{role:"BOSS"|"MAINTAINER"|null;onOpen:(target:Target&{page_id:"F02"|"D09";record_id?:string})=>void}){
  const {getToken,token}=useClient(),callback=useRef(onOpen);
  callback.current=onOpen;
  const [error,setError]=useState("");
  useEffect(()=>{
    const native=bridge();if(!native?.onNotificationOpen)return;
    const controllers=new Set<AbortController>();let active=true;setError("");
    const unsubscribe=native.onNotificationOpen(target=>{
      if(role!=="BOSS"){setError("当前身份不能读取本人通知，请重新认证。");return;}
      if(!target||typeof target.event_id!=="string"||typeof target.event_version!=="string"||typeof target.execution_namespace!=="string"||!target.execution_namespace){setError("系统通知没有有效对象编号与原执行空间。");return;}
      const controller=new AbortController();controllers.add(controller);
      void fetch("/api/boss/ui/notification-target?"+new URLSearchParams(target),{headers:{Authorization:"Bearer "+getToken()},cache:"no-store",signal:controller.signal}).then(async response=>{
        if(response.status===401)window.dispatchEvent(new Event("boss-auth-expired"));
        if(!response.ok)throw new Error("当前通知无法打开，HTTP "+response.status);
        const value=await response.json();
        if(active&&!controller.signal.aborted){if(value.event_id!==target.event_id||value.event_version!==target.event_version||value.execution_namespace!==target.execution_namespace||!["F02","D09"].includes(value.page_id)||value.page_id==="D09"&&typeof value.record_id!=="string")throw new Error("通知返回对象与当前请求不符");callback.current({...target,page_id:value.page_id,record_id:value.record_id});setError("");}
      }).catch(failure=>{if(active&&!controller.signal.aborted)setError(failure.message);}).finally(()=>controllers.delete(controller));
    });
    return()=>{active=false;unsubscribe();for(const controller of controllers)controller.abort();};
  },[role,token,getToken]);
  return error?<p role="alert" className="boss-status boss-status-error">{error}</p>:null;
}
