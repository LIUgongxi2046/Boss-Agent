import {useCallback,useEffect,useRef,useState} from "react";
import Ajv2020 from "ajv/dist/2020";
import addFormats from "ajv-formats";
import schema from "../../validation/agent_artifact_schema.json";
import {Upgrade2ArtifactSourceHistory,type ArtifactHistoryReference} from "./Upgrade2ArtifactSourceHistory";

type ArtifactSource={source_id:string;revision:string;locator:string;classification:string;sha256:string};
type Artifact={artifact_id:string;run_id:string;series_id:string;previous_artifact_id:string|null;version:number;goal_revision?:number|null;media_type:string;sha256:string;size_bytes:number;verification_status:string;status:string;source_refs:ArtifactSource[]};
export type ListedArtifact=Artifact;
const ajv=new Ajv2020({strictTypes:false,allowUnionTypes:true});
addFormats(ajv);ajv.addSchema(schema);
const validate=ajv.getSchema("urn:boss-agent:artifact-projection:1#/$defs/list");
const validateMetadata=ajv.getSchema("urn:boss-agent:artifact-projection:1#/$defs/metadata");
if(!validate||!validateMetadata)throw new Error("成果 Schema 未找到");
const names:Record<string,string>={"text/markdown":"Markdown","application/pdf":"PDF","application/vnd.openxmlformats-officedocument.wordprocessingml.document":"DOCX","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":"XLSX","application/vnd.openxmlformats-officedocument.presentationml.presentation":"PPTX"};

export function ArtifactSourceReference({source,onOpenSource,onOpenHistory,disabled=false}:{source:ArtifactSource;onOpenSource:(id:string,version:string)=>void;onOpenHistory:()=>void;disabled?:boolean}) {
  return <div><p>来源 {source.source_id} · 引用版本 {source.revision} · 类型 {source.classification}</p><p>来源摘要 {source.sha256}</p><p>原始位置说明：{source.locator}。原文位置未经核查。</p><button className="boss-btn" type="button" disabled={disabled} onClick={onOpenHistory}>查看引用版本</button><button className="boss-btn" type="button" disabled={disabled} onClick={()=>onOpenSource(source.source_id,source.revision)}>查看当前来源</button></div>;
}

export function artifactListError(status:number):string {
  if(status===401)return "本人认证已失效，成果来源不可读取。";
  if(status===403)return "当前身份或会话没有读取权限，成果来源不可读取。";
  if(status===404)return "成果或来源不存在，当前不可读取。";
  if(status===409)return "成果或来源状态发生变化，当前不可读取。";
  if(status===410)return "成果或来源已撤销，当前不可读取。";
  if(status===503)return "成果读取服务尚不可用。";
  return "成果读取失败，HTTP "+status+"。";
}

export function ArtifactAvailability({item,allowOpen,allowExport,hasExport}:{item:ListedArtifact;allowOpen:boolean;allowExport:boolean;hasExport:boolean}) {
  if(item.status!=="PUBLISHED")return <p>成果尚未发布，文件不可打开或导出。</p>;
  return <>{!allowOpen&&<p>当前运行未提供打开此文件的允许动作。</p>}{(!allowExport||!hasExport)&&<p>当前运行或设备未提供导出此文件的条件。</p>}</>;
}

export function ArtifactGoalRevision({item,current}:{item:ListedArtifact;current:number|null}) {
  const revision=item.goal_revision;
  if(current===null)return <p>当前目标版本尚未读取。</p>;
  if(revision==null)return <p>成果所属目标版本未知，无法确认与当前目标的关系。</p>;
  if(revision===current)return <p>成果所属目标版本 {revision} · 当前目标版本。</p>;
  if(revision<current)return <p>成果所属目标版本 {revision} · 历史目标；当前目标版本 {current}。</p>;
  return <p role="alert">成果所属目标版本 {revision} 高于当前目标版本 {current}，请重新读取运行。</p>;
}

export function Upgrade2ArtifactList({runId,goalRevision,token,getToken,connected,onOpenSource,allowOpen,allowExport,onExport}:{runId:string;goalRevision:number|null;token:string;getToken:()=>string;connected:boolean;onOpenSource:(id:string,version:string)=>void;allowOpen:boolean;allowExport:boolean;onExport?:(item:ListedArtifact)=>void}){
  const [items,setItems]=useState<Artifact[]|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState("");
  const [itemsScope,setItemsScope]=useState<string|null>(null);
  const [opened,setOpened]=useState<{id:string;url:string}|null>(null);
  const [history,setHistory]=useState<ArtifactHistoryReference|null>(null);
  const epoch=useRef(0);
  const scope=JSON.stringify([runId,goalRevision,token]);
  const currentScope=useRef(scope);currentScope.current=scope;
  const visible=goalRevision!==null&&itemsScope===scope;
  const invalidate=useCallback((status:number)=>{epoch.current++;setItems(null);setItemsScope(null);setOpened(null);setHistory(null);setBusy(false);setError(artifactListError(status));},[]);
  useEffect(()=>{epoch.current++;setItems(null);setItemsScope(null);setBusy(false);setError("");setOpened(null);setHistory(null);return()=>{epoch.current++;};},[runId,goalRevision,token,connected,allowOpen]);
  useEffect(()=>()=>{if(opened)URL.revokeObjectURL(opened.url);},[opened]);
  async function read(){
    if(busy||!connected||goalRevision===null||!token||getToken()!==token)return;
    const current=epoch.current;setItems(null);setOpened(null);setHistory(null);setBusy(true);setError("");
    try{
      const response=await fetch("/api/v2/runs/"+encodeURIComponent(runId)+"/artifacts",{headers:{Authorization:"Bearer "+token},credentials:"same-origin",cache:"no-store",redirect:"error"});
      if(!response.ok){if(response.status===401&&current===epoch.current&&getToken()===token&&currentScope.current===scope)window.dispatchEvent(new Event("boss-auth-expired"));throw new Error(artifactListError(response.status));}
      const value:unknown=await response.json();
      if(!validate!(value))throw new Error("成果列表响应不符合 Schema");
      const result=value as {run_id:string;artifacts:Artifact[]};
      if(result.run_id!==runId||result.artifacts.some(item=>item.run_id!==runId||!Number.isSafeInteger(item.version)))throw new Error("成果列表与当前运行不一致");
      if(current===epoch.current&&getToken()===token&&currentScope.current===scope){setItems(result.artifacts);setItemsScope(scope);}
    }catch(failure){if(current===epoch.current&&getToken()===token&&currentScope.current===scope){setItems(null);setItemsScope(null);setOpened(null);setHistory(null);setError(failure instanceof Error?failure.message:String(failure));}}
    finally{if(current===epoch.current&&currentScope.current===scope)setBusy(false);}
  }
  async function prepareOpen(item:Artifact){
    if(busy||!connected||!allowOpen||item.status!=="PUBLISHED"||getToken()!==token)return;
    const current=epoch.current;setOpened(null);setBusy(true);setError("");
    try{
      const path="/api/v2/artifacts/"+encodeURIComponent(item.artifact_id),query="?"+new URLSearchParams({version:String(item.version)});
      const options={headers:{Authorization:"Bearer "+token},credentials:"same-origin" as const,cache:"no-store" as const,redirect:"error" as const};
      const metadataResponse=await fetch(path+query,options);
      if(!metadataResponse.ok){if([401,403,404,409,410].includes(metadataResponse.status)){if(metadataResponse.status===401&&current===epoch.current&&getToken()===token&&currentScope.current===scope)window.dispatchEvent(new Event("boss-auth-expired"));if(current===epoch.current&&getToken()===token&&currentScope.current===scope)invalidate(metadataResponse.status);}throw new Error("成果核查失败（HTTP "+metadataResponse.status+"）："+await metadataResponse.text());}
      const metadata:unknown=await metadataResponse.json();
      if(!validateMetadata!(metadata))throw new Error("成果信息不符合 Schema");
      const verified=metadata as Artifact;
      if(verified.artifact_id!==item.artifact_id||verified.run_id!==runId||verified.version!==item.version||(verified.goal_revision??null)!==(item.goal_revision??null)||verified.sha256!==item.sha256||verified.media_type!==item.media_type||verified.status!=="PUBLISHED")throw new Error("成果版本或内容已经变化");
      const file=await fetch(path+"/file"+query,options);
      if(!file.ok){if([401,403,404,409,410].includes(file.status)){if(file.status===401&&current===epoch.current&&getToken()===token&&currentScope.current===scope)window.dispatchEvent(new Event("boss-auth-expired"));if(current===epoch.current&&getToken()===token&&currentScope.current===scope)invalidate(file.status);}throw new Error("成果读取失败（HTTP "+file.status+"）："+await file.text());}
      if(file.headers.get("content-type")?.split(";")[0]!==verified.media_type||file.headers.get("etag")!=='"'+verified.sha256+'"')throw new Error("成果文件标识不一致");
      const bytes=await file.arrayBuffer();
      const hash=Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",bytes)),byte=>byte.toString(16).padStart(2,"0")).join("");
      if(bytes.byteLength!==verified.size_bytes||hash!==verified.sha256)throw new Error("成果文件内容已经变化");
      if(current===epoch.current&&getToken()===token&&currentScope.current===scope)setOpened({id:item.artifact_id,url:URL.createObjectURL(new Blob([bytes],{type:verified.media_type}))});
    }catch(failure){if(current===epoch.current&&getToken()===token&&currentScope.current===scope){setItems(null);setItemsScope(null);setOpened(null);setHistory(null);setError(failure instanceof Error?failure.message:String(failure));}}
    finally{if(current===epoch.current&&currentScope.current===scope)setBusy(false);}
  }
  async function openPrepared(item:Artifact){
    if(!opened||opened.id!==item.artifact_id||busy||!connected||!allowOpen||getToken()!==token)return;
    const current=epoch.current;setBusy(true);setError("");
    try{
      const response=await fetch("/api/v2/artifacts/"+encodeURIComponent(item.artifact_id)+"?"+new URLSearchParams({version:String(item.version)}),{headers:{Authorization:"Bearer "+token},credentials:"same-origin",cache:"no-store",redirect:"error"});
      if(!response.ok){if([401,403,404,409,410].includes(response.status)){if(response.status===401&&current===epoch.current&&getToken()===token&&currentScope.current===scope)window.dispatchEvent(new Event("boss-auth-expired"));if(current===epoch.current&&getToken()===token&&currentScope.current===scope)invalidate(response.status);}throw new Error("成果重新核查失败（HTTP "+response.status+"）："+await response.text());}
      const value:unknown=await response.json();if(!validateMetadata!(value))throw new Error("成果信息不符合 Schema");
      const metadata=value as Artifact;
      if(metadata.artifact_id!==item.artifact_id||metadata.run_id!==runId||metadata.version!==item.version||(metadata.goal_revision??null)!==(item.goal_revision??null)||metadata.sha256!==item.sha256||metadata.status!=="PUBLISHED")throw new Error("成果版本或内容已经变化");
      if(current!==epoch.current||getToken()!==token||currentScope.current!==scope)return;
      const windowHandle=window.open(opened.url,"_blank");
      if(!windowHandle)throw new Error("浏览器没有打开文件，请检查窗口设置");
      windowHandle.opener=null;
    }catch(failure){if(current===epoch.current&&getToken()===token&&currentScope.current===scope){setItems(null);setItemsScope(null);setOpened(null);setHistory(null);setError(failure instanceof Error?failure.message:String(failure));}}
    finally{if(current===epoch.current&&currentScope.current===scope)setBusy(false);}
  }
  return <section className="upgrade2-run-card" aria-label="当前运行成果列表"><h3>当前运行成果</h3>
    <p>成果列表按运行展示；所属目标版本依据服务核查结果显示。</p>
    <button className="boss-btn" type="button" disabled={busy||!connected||goalRevision===null||!token} onClick={()=>void read()}>读取成果列表</button>
    {busy&&<p role="status">正在核查成果与来源。</p>}{error&&<p role="alert">{error}</p>}
    {visible&&items&&connected&&getToken()===token&&(!items.length?<p>当前运行没有可读取的成果。</p>:<ul>{items.map(item=><li key={item.artifact_id}><strong>{names[item.media_type]} · 版本 {item.version}</strong><p>成果编号：{item.artifact_id}</p><p>版本系列：{item.series_id} · 上一版本：{item.previous_artifact_id??"没有"}</p><ArtifactGoalRevision item={item} current={goalRevision}/><p>状态：{item.status} · {item.verification_status} · {item.size_bytes} 字节</p><p>摘要：{item.sha256}</p>{item.source_refs.map(source=><ArtifactSourceReference key={source.source_id+source.revision+source.locator} source={source} disabled={busy} onOpenSource={onOpenSource} onOpenHistory={()=>setHistory({run_id:runId,artifact_id:item.artifact_id,artifact_version:item.version,artifact_sha256:item.sha256,source_id:source.source_id,version:source.revision,sha256:source.sha256,locator:source.locator})}/>)}<ArtifactAvailability item={item} allowOpen={allowOpen} allowExport={allowExport} hasExport={!!onExport}/><div className="boss-actions"><button className="boss-btn" type="button" disabled={busy||!connected||!allowOpen||item.status!=="PUBLISHED"} onClick={()=>void prepareOpen(item)}>核查并准备打开</button><button className="boss-btn" type="button" disabled={busy||!connected||!allowExport||!onExport||item.status!=="PUBLISHED"} onClick={()=>onExport?.(item)}>导出成果</button></div>{opened?.id===item.artifact_id&&<button className="boss-btn" type="button" disabled={busy||!connected||!allowOpen} onClick={()=>void openPrepared(item)}>打开已核查文件</button>}</li>)}</ul>)}
    {visible&&history&&items&&!busy&&!error&&connected&&getToken()===token&&<Upgrade2ArtifactSourceHistory key={JSON.stringify(history)} reference={history} token={token} getToken={getToken} onClose={()=>setHistory(null)} onInvalidated={invalidate}/>}
    <p>打开和导出需要服务返回当前允许动作及成果接口；桌面导出需要本人选择保存位置。</p>
  </section>;
}
