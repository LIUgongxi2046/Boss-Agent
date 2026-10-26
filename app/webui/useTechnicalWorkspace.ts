import {useCallback, useEffect, useRef, useState} from "react";
import {useClient} from "@/providers/ClientProvider";

export type TechnicalReceipt = {request_id:string; action:string; state:"RECORDED"; result:Record<string,unknown>};
type Pending = {request_id:string;action:string;payload:Record<string,unknown>};
function restore(key:string):Pending|null{
  const saved=sessionStorage.getItem(key);
  if(saved===null)return null;
  const value=JSON.parse(saved) as {request_id?:unknown;action?:unknown};
  if(typeof value.request_id!=="string"||typeof value.action!=="string")throw new Error("原请求索引格式无效");
  return{request_id:value.request_id,action:value.action,payload:{}};
}

export function useTechnicalWorkspace<T extends {projection:string;private_body_available_here:false}>(domain:string){return useWorkspace<T>(domain,"technical");}
export function useOwnerWorkspace<T extends {projection:string;private_body_available_here?:boolean}>(domain:string){return useWorkspace<T>(domain,"owner");}

function useWorkspace<T extends {projection:string;private_body_available_here?:boolean}>(domain:string,access:"technical"|"owner"){
  const {client,getToken,token}=useClient();
  const storageKey="boss:v7:"+access+"-request:"+domain;
  const [data,setData]=useState<T|null>(null);
  const [loading,setLoading]=useState(true);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [receipt,setReceipt]=useState<TechnicalReceipt|null>(null);
  const [pending,setPending]=useState<Pending|null>(()=>restore(storageKey));
  const controller=useRef<AbortController|null>(null);
  const active=useRef(true);
  const lock=useRef(false);
  const identity=useRef({token,client,domain});
  const loadedIdentity=useRef(identity.current);
  if(identity.current.token!==token||identity.current.client!==client||identity.current.domain!==domain)identity.current={token,client,domain};
  const endpoint=(access==="technical"?"/api/boss/ui/admin/technical/":"/api/boss/ui/owner/")+encodeURIComponent(domain);
  function remember(request:Pending|null){
    if(request)sessionStorage.setItem(storageKey,JSON.stringify({request_id:request.request_id,action:request.action}));
    else sessionStorage.removeItem(storageKey);
    setPending(request);
  }
  const read=useCallback(async()=>{
    const origin=identity.current;
    controller.current?.abort();
    const abort=new AbortController();controller.current=abort;setLoading(true);setError("");
    const response=await fetch(endpoint,{headers:{Authorization:"Bearer "+getToken()},signal:abort.signal,cache:"no-store"});
    if(response.status===401)window.dispatchEvent(new Event("boss-auth-expired"));
    if(!response.ok)throw new Error("读取失败（HTTP "+response.status+"）");
    const value=await response.json() as T;
    if(value.projection!==domain||access==="technical"&&value.private_body_available_here!==false)throw new Error("资料范围不符合当前页面要求");
    if(abort.signal.aborted||!active.current||origin!==identity.current)return;
    loadedIdentity.current=origin;
    setData(value);setLoading(false);
  },[domain,endpoint,getToken,access]);
  const reload=useCallback(()=>{void read().then(undefined,reason=>{
    if(active.current&&reason.name!=="AbortError"){setLoading(false);setError(reason.message);}
  });},[read]);
  useEffect(()=>{active.current=true;setData(null);setReceipt(null);setPending(restore(storageKey));reload();return()=>{active.current=false;controller.current?.abort();};},[reload,storageKey,token]);
  const send=async(request:Pending)=>{
    if(lock.current)return false;
    const origin=identity.current;
    let recorded=false;
    remember(request);lock.current=true;setBusy(true);setError("");
    return client.requestMutation<TechnicalReceipt>((access==="technical"?"boss.technical.":"boss.owner_workspace.")+domain+"."+request.action,{client_request_id:request.request_id,...request.payload}).then(async value=>{
      if(value.state!=="RECORDED"||value.request_id!==request.request_id||value.action!==request.action)throw new Error("操作回执与原请求不一致，请核查原请求");
      if(!active.current||origin!==identity.current)return;
      recorded=true;
      setReceipt(value);remember(null);await read();
    }).then(()=>{lock.current=false;if(active.current&&origin===identity.current)setBusy(false);return active.current&&origin===identity.current;},reason=>{
      if(!active.current||origin!==identity.current){lock.current=false;return false;}
      const status=reason instanceof Error&&"status" in reason?reason.status:null;
      if(typeof status==="number"&&[400,401,403,404,409,410,413,422].includes(status))remember(null);
      if(status===401)window.dispatchEvent(new Event("boss-auth-expired"));
      lock.current=false;if(active.current){setBusy(false);setLoading(false);setError(recorded?"操作已经记录，重新读取失败："+reason.message:reason.message);}return recorded;
    });
  };
  const execute=(action:string,payload:Record<string,unknown>)=>{
    if(pending||lock.current)throw new Error("原请求尚未确定，请先核查原请求");
    return send({action,payload,request_id:crypto.randomUUID()});
  };
  const reconcile=async()=>{
    if(!pending||lock.current)return;
    const origin=identity.current;
    lock.current=true;setBusy(true);setError("");
    await fetch(endpoint+"/requests/"+encodeURIComponent(pending.request_id),{headers:{Authorization:"Bearer "+getToken()},cache:"no-store"}).then(async response=>{
      if(!response.ok)throw new Error(response.status===404?"尚未找到原请求记录，请继续核查。":"请求核查失败（HTTP "+response.status+"）");
      const value=await response.json() as TechnicalReceipt;
      if(value.state!=="RECORDED"||value.request_id!==pending.request_id||value.action!==pending.action)throw new Error("原请求回执无效");
      if(!active.current||origin!==identity.current)return;
      setReceipt(value);remember(null);await read();
    }).then(()=>{lock.current=false;if(active.current&&origin===identity.current)setBusy(false);},reason=>{
      lock.current=false;if(active.current&&origin===identity.current){setBusy(false);setLoading(false);setError(reason.message);}
    });
  };
  return {data:loadedIdentity.current===identity.current?data:null,loading,busy,error,receipt:loadedIdentity.current===identity.current?receipt:null,pending,reload,execute,reconcile};
}
