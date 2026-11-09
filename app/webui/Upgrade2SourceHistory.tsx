import {useLayoutEffect,useState} from "react";
import Ajv2020 from "ajv/dist/2020";
import addFormats from "ajv-formats";
import schema from "./agent_source_history_schema.local.json";

export type HistoryReference={run_id:string;event_id:string;source_id:string;version:string;sha256:string;locator:string};
type History={run_id:string;event_id:string;source_id:string;version:string;sha256:string;current_version:string;historical:boolean;title:string;content:string;citations:{locator:string;locator_verification:"NOT_VERIFIED"}[]};
const validator=new Ajv2020();
addFormats(validator);
const validate=validator.compile(schema);

export function validateHistory(value:unknown,reference:HistoryReference):History {
  if(!validate(value))throw new Error("来源历史响应不符合 Schema。");
  const data=value as History;
  if(data.run_id!==reference.run_id||data.event_id!==reference.event_id||data.source_id!==reference.source_id||data.version!==reference.version||data.sha256!==reference.sha256||!data.citations.some(item=>item.locator===reference.locator)||data.historical!==(data.current_version!==data.version))throw new Error("来源历史与原结果引用不一致，正文不可读取。");
  return data;
}

export function historyError(status:number):string {
  if(status===401)return "本人认证已失效，来源正文不可读取。";
  if(status===403)return "当前身份或会话没有读取权限，来源正文不可读取。";
  if(status===404)return "原引用、来源版本或历史正文不可读取。";
  if(status===409)return "来源状态或资料范围发生变化，当前不可读取。";
  if(status===410)return "来源已撤销或正在清理，当前不可读取。";
  return "来源历史读取失败，HTTP "+status+"。";
}

export function HistoryContent({data}:{data:History}) {
  return <><h4>{data.title}</h4><p>引用版本 {data.version} · 当前版本 {data.current_version} · {data.historical?"历史版本":"当前版本"}</p><p>来源摘要 {data.sha256}</p><blockquote className="boss-source-text">{data.content}</blockquote></>;
}

export function Upgrade2SourceHistory({reference,token,getToken,onClose}:{reference:HistoryReference;token:string;getToken:()=>string;onClose:()=>void}) {
  const [data,setData]=useState<History|null>(null),[error,setError]=useState(""),[loading,setLoading]=useState(true),[revision,setRevision]=useState(0);
  useLayoutEffect(()=>{
    const abort=new AbortController();
    setData(null);setError("");setLoading(true);
    const query=new URLSearchParams({source_id:reference.source_id,version:reference.version});
    const path="/api/v2/runs/"+encodeURIComponent(reference.run_id)+"/source-history/"+encodeURIComponent(reference.event_id)+"?"+query;
    if(getToken()!==token){setLoading(false);setError("本人认证已变化，来源正文不可读取。");return ()=>abort.abort();}
    void fetch(path,{headers:{Authorization:"Bearer "+token},cache:"no-store",signal:abort.signal}).then(async response=>{
      if(!response.ok){if(response.status===401&&!abort.signal.aborted&&getToken()===token)window.dispatchEvent(new Event("boss-auth-expired"));throw new Error(historyError(response.status));}
      return validateHistory(await response.json(),reference);
    }).then(value=>{if(!abort.signal.aborted&&getToken()===token){setData(value);setLoading(false);}}).catch(reason=>{if(!abort.signal.aborted&&getToken()===token){setData(null);setLoading(false);setError(reason instanceof Error?reason.message:String(reason));}});
    return ()=>abort.abort();
  },[reference,token,getToken,revision]);
  const available=getToken()===token;
  return <section className="upgrade2-run-card" aria-label="结果引用的来源历史">
    <h3>结果引用的来源历史</h3><p>来源 {reference.source_id} · 引用版本 {reference.version} · 原结果 {reference.event_id}</p>
    <p>原始位置说明：{reference.locator}。原文位置未经核查，无法自动定位。</p>
    {loading&&available&&<p role="status">正在读取来源历史。</p>}
    {(!available||error)&&<p role="alert">{available?error:"本人认证已变化，来源正文不可读取。"}</p>}
    {available&&data&&<HistoryContent data={data}/>}
    <div className="upgrade2-run-actions"><button type="button" disabled={loading||!available} onClick={()=>setRevision(value=>value+1)}>重新读取</button><button type="button" onClick={onClose}>关闭来源历史</button></div>
  </section>;
}
