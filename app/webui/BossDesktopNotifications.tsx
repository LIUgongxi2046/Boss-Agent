import {useEffect,useRef,useState} from "react";
import {useClient} from "@/providers/ClientProvider";

type Target={event_id:string;event_version:string};
type NativeState={supported:boolean;permission:"NOT_REPORTED_BY_SYSTEM"|"DENIED_BY_SYSTEM";state:string;failure_reason?:string|null;external_delivery_verified:false};
type Bridge={invoke:(request:Record<string,unknown>)=>Promise<NativeState>;onNotificationOpen?:(listener:(target:Target)=>void)=>()=>void};
function bridge(){return (window as Window&{bossDesktop?:Bridge}).bossDesktop;}
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

export function BossNotificationReturn({role,onOpen}:{role:"BOSS"|"MAINTAINER"|null;onOpen:(target:Target)=>void}){
  const {getToken,token}=useClient(),callback=useRef(onOpen);
  callback.current=onOpen;
  const [error,setError]=useState("");
  useEffect(()=>{
    const native=bridge();if(!native?.onNotificationOpen)return;
    const controllers=new Set<AbortController>();let active=true;setError("");
    const unsubscribe=native.onNotificationOpen(target=>{
      if(role!=="BOSS"){setError("当前身份不能读取本人通知，请重新认证。");return;}
      if(!target||typeof target.event_id!=="string"||typeof target.event_version!=="string"){setError("系统通知没有有效对象编号。");return;}
      const controller=new AbortController();controllers.add(controller);
      void fetch("/api/boss/ui/notification-target?"+new URLSearchParams(target),{headers:{Authorization:"Bearer "+getToken()},cache:"no-store",signal:controller.signal}).then(async response=>{
        if(response.status===401)window.dispatchEvent(new Event("boss-auth-expired"));
        if(!response.ok)throw new Error("当前通知无法打开，HTTP "+response.status);
        const value=await response.json();
        if(active&&!controller.signal.aborted){if(value.event_id!==target.event_id||value.event_version!==target.event_version||value.page_id!=="F02")throw new Error("通知返回对象与当前请求不符");callback.current(target);setError("");}
      }).catch(failure=>{if(active&&!controller.signal.aborted)setError(failure.message);}).finally(()=>controllers.delete(controller));
    });
    return()=>{active=false;unsubscribe();for(const controller of controllers)controller.abort();};
  },[role,token,getToken]);
  return error?<p role="alert" className="boss-status boss-status-error">{error}</p>:null;
}
