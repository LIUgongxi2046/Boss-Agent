import {useLayoutEffect,useState} from "react";
import Ajv2020 from "ajv/dist/2020";
import addFormats from "ajv-formats";
import schema from "./agent_artifact_source_history_schema.local.json";
import {historyError} from "./Upgrade2SourceHistory";

export type ArtifactHistoryReference={run_id:string;artifact_id:string;artifact_version:number;artifact_sha256:string;source_id:string;version:string;sha256:string;locator:string};
type ArtifactHistory=ArtifactHistoryReference&{current_version:string;historical:boolean;title:string;content:string;locator_verification:"NOT_VERIFIED"};
const validator=new Ajv2020();
addFormats(validator);
const validate=validator.compile(schema);

export function validateArtifactHistory(value:unknown,reference:ArtifactHistoryReference):ArtifactHistory {
  if(!validate(value))throw new Error("成果来源历史响应不符合 Schema。");
  const data=value as ArtifactHistory;
  if(data.run_id!==reference.run_id||data.artifact_id!==reference.artifact_id||data.artifact_version!==reference.artifact_version||data.artifact_sha256!==reference.artifact_sha256||data.source_id!==reference.source_id||data.version!==reference.version||data.sha256!==reference.sha256||data.locator!==reference.locator||data.historical!==(data.current_version!==data.version))throw new Error("成果来源历史与原引用不一致，正文不可读取。");
  return data;
}

export function ArtifactHistoryContent({data}:{data:ArtifactHistory}) {
  return <><h4>{data.title}</h4><p>引用版本 {data.version} · 当前版本 {data.current_version} · {data.historical?"历史版本":"当前版本"}</p><p>来源摘要 {data.sha256}</p><p>原始位置说明：{data.locator}。原文位置未经核查，无法自动定位。</p><blockquote className="boss-source-text">{data.content}</blockquote></>;
}

export function Upgrade2ArtifactSourceHistory({reference,token,getToken,onClose,onInvalidated}:{reference:ArtifactHistoryReference;token:string;getToken:()=>string;onClose:()=>void;onInvalidated:(status:number)=>void}) {
  const [data,setData]=useState<ArtifactHistory|null>(null),[error,setError]=useState(""),[loading,setLoading]=useState(true),[revision,setRevision]=useState(0);
  useLayoutEffect(()=>{
    const abort=new AbortController();setData(null);setError("");setLoading(true);
    const query=new URLSearchParams({source_id:reference.source_id,version:reference.version,artifact_version:String(reference.artifact_version)});
    const path="/api/v2/runs/"+encodeURIComponent(reference.run_id)+"/artifacts/"+encodeURIComponent(reference.artifact_id)+"/source-history?"+query;
    if(getToken()!==token){setLoading(false);setError("本人认证已变化，来源正文不可读取。");return ()=>abort.abort();}
    void fetch(path,{headers:{Authorization:"Bearer "+token},cache:"no-store",signal:abort.signal}).then(async response=>{
      if(!response.ok){if(response.status===401&&!abort.signal.aborted&&getToken()===token)window.dispatchEvent(new Event("boss-auth-expired"));if([401,403,404,409,410].includes(response.status)&&!abort.signal.aborted&&getToken()===token)onInvalidated(response.status);throw new Error(historyError(response.status));}
      return validateArtifactHistory(await response.json(),reference);
    }).then(value=>{if(!abort.signal.aborted&&getToken()===token){setData(value);setLoading(false);}}).catch(reason=>{if(!abort.signal.aborted&&getToken()===token){setData(null);setLoading(false);setError(reason instanceof Error?reason.message:String(reason));}});
    return ()=>abort.abort();
  },[reference,token,getToken,onInvalidated,revision]);
  const available=getToken()===token;
  return <section className="upgrade2-run-card" aria-label="成果引用的来源历史"><h3>成果引用的来源历史</h3><p>成果 {reference.artifact_id} · 版本 {reference.artifact_version} · 来源 {reference.source_id} · 引用版本 {reference.version}</p>
    <p>原始位置说明：{reference.locator}。原文位置未经核查，无法自动定位。</p>
    {loading&&available&&<p role="status">正在读取来源历史。</p>}{(!available||error)&&<p role="alert">{available?error:"本人认证已变化，来源正文不可读取。"}</p>}{available&&data&&<ArtifactHistoryContent data={data}/>}
    <div className="upgrade2-run-actions"><button type="button" disabled={loading||!available} onClick={()=>setRevision(value=>value+1)}>重新读取</button><button type="button" onClick={onClose}>关闭来源历史</button></div>
  </section>;
}
