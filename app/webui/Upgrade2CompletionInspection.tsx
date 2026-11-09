import {useEffect,useState} from "react";
import {completionInspectionSchemaError,Upgrade2RunClient,type CompletionInspection} from "./upgrade2-run-client";

const blockerLabels:Record<string,string>={
  PROCESS_GROUP_EXIT_UNVERIFIED:"进程组退出未核查",
  RESULT_SEMANTICS_UNVERIFIED:"结果语义未核查",
  BRIEF_SECTION_AUDIT_UNVERIFIED:"会议简报章节核查未通过",
  ACCEPTANCE_REQUIREMENTS_UNAVAILABLE:"必要成果要求不可核查",
  REQUIRED_OUTPUT_MISSING:"缺少必要成果",
  REQUIRED_OUTPUT_UNVERIFIED:"必要成果未核查",
  ARTIFACT_FILES_UNVERIFIED:"成果文件未核查",
  ARTIFACT_STATE_UNAVAILABLE:"成果状态不可核查",
  FILE_RESERVATIONS_PENDING:"文件预留尚未完成",
  INTENT_STATE_UNAVAILABLE:"本人决定状态不可核查",
  INTENTS_PENDING:"仍有待处理本人决定",
};
const outputLabels:Record<string,string>={TEXT:"文字",BRIEF:"简报",SOURCE_LIST:"来源清单",ACTION_DRAFT:"动作草稿",MARKDOWN:"Markdown",PDF:"PDF",DOCX:"DOCX",XLSX:"XLSX",PPTX:"PPTX",BUSINESS_RECEIPT:"业务回执"};
const outputStateLabels:Record<string,string>={RECORD_PRESENT:"有记录",FILE_VERIFIED:"文件已核查",NOT_VERIFIED:"未核查",MISSING:"缺少"};
const sectionLabels:Record<string,string>={AGENDA:"议题",CONSENSUS:"共识",CONFLICT:"冲突",DECISION:"决定",COMMITMENT:"承诺",FACT:"事实",MISSING:"缺失事项"};
const auditStateLabels:Record<string,string>={PASS:"通过",UNVERIFIED:"未核查",BLOCKED:"受阻",SUPPORTED:"有依据",UNVERIFIED_CONTENT:"内容未核查",MISSING_DOMAIN_FIELD:"领域资料缺少字段"};
const gapLabels:Record<string,string>={MISSING_REQUIRED_CATEGORY:"缺少必要类别",SOURCE_NOT_IN_DOMAIN_BRIEF:"来源不在领域简报中",SOURCE_VERSION_OR_DIGEST_MISSING:"来源版本或摘要缺失",CONTENT_NOT_COMPARABLE_TO_DOMAIN_FIELD:"内容无法与领域字段比较"};

export function briefAuditLabel(value:string):string {
  return sectionLabels[value]??auditStateLabels[value]??gapLabels[value]??value;
}

export function completionBlockerLabel(value:string):string {
  return blockerLabels[value]??value;
}

export function completionVersionNotice(data:CompletionInspection):string|null {
  if(!data.stale)return null;
  return "该完成核查产生于运行版本 "+data.inspection_revision+"，当前运行版本 "+data.run_revision+"，目标版本 "+data.goal_revision+"，当前目标版本 "+data.current_goal_revision+"；属于历史核查，不能作为当前完成结果。";
}

export function completionStateLine(data:CompletionInspection):string {
  if(data.stale)return "历史核查记录，不作为当前完成结果。";
  return "完成状态 "+data.completion_state;
}

export function completionInspectionMatches(data:CompletionInspection,runId:string,goalRevision:number,finishEventId?:string):boolean {
  if(data.run_id!==runId)return false;
  if(data.current_goal_revision!==goalRevision)return false;
  if(finishEventId!==undefined&&data.finish_event_id!==finishEventId)return false;
  return true;
}

type View={scope:string;data:CompletionInspection|null;message:string};

export function Upgrade2CompletionInspection({client,runId,runRevision,goalRevision,token,getToken,finishEventId,onAccessDenied,timeoutMs=15000}:{client:Upgrade2RunClient;runId:string;runRevision:number;goalRevision:number;token:string;getToken:()=>string;finishEventId?:string;onAccessDenied?:(status:number)=>void;timeoutMs?:number}) {
  const scope=JSON.stringify([runId,runRevision,goalRevision,token,finishEventId??""]);
  const [view,setView]=useState<View|null>(null);
  const [attempt,setAttempt]=useState(0);
  useEffect(()=>{
    let active=true;
    const xhr=new XMLHttpRequest();
    xhr.open("GET",client.completionInspectionPath(runId,finishEventId));
    xhr.responseType="json";
    xhr.timeout=timeoutMs;
    if(token)xhr.setRequestHeader("Authorization","Bearer "+token);
    const same=()=>active&&getToken()===token;
    const timer=window.setTimeout(()=>{
      if(!same())return;
      active=false;
      xhr.abort();
      setView({scope,data:null,message:"完成核查读取超时，请检查网络后重新读取。"});
    },timeoutMs);
    const finish=()=>{active=false;window.clearTimeout(timer);};
    xhr.onload=()=>{
      if(!same())return;
      finish();
      if(xhr.status<200||xhr.status>=300){
        if(xhr.status===401)window.dispatchEvent(new Event("boss-auth-expired"));
        if([401,403].includes(xhr.status))onAccessDenied?.(xhr.status);
        if(xhr.status===404){setView({scope,data:null,message:"当前运行没有已保存的完成核查记录。"});return;}
        setView({scope,data:null,message:"完成核查读取失败，HTTP "+xhr.status+"。"});
        return;
      }
      const value:unknown=xhr.response;
      const schemaError=completionInspectionSchemaError(value);
      if(schemaError){setView({scope,data:null,message:schemaError});return;}
      const data=value as CompletionInspection;
      if(!completionInspectionMatches(data,runId,goalRevision,finishEventId)){setView({scope,data:null,message:"完成核查与当前运行、目标版本或完成事件不一致，请重新读取运行。"});return;}
      if(data.run_revision!==runRevision){setView({scope,data:null,message:"页面运行版本与完成核查当前版本不一致，请重新读取运行。"});return;}
      setView({scope,data,message:""});
    };
    xhr.onerror=()=>{if(!same())return;finish();setView({scope,data:null,message:"完成核查读取失败：无法连接服务，请检查网络后重新读取。"});};
    xhr.ontimeout=()=>{if(!same())return;finish();setView({scope,data:null,message:"完成核查读取超时，请检查网络后重新读取。"});};
    xhr.send();
    return()=>{active=false;window.clearTimeout(timer);xhr.abort();};
  },[attempt,client,finishEventId,getToken,goalRevision,onAccessDenied,runId,runRevision,scope,token,timeoutMs]);
  const current=view?.scope===scope?view:null;
  return <section className="upgrade2-run-card" aria-label="完成核查">
    <h3>完成核查</h3>
    {!current?<p role="status">正在读取完成核查。</p>:current.message?<><p role="alert">{current.message}</p><button type="button" className="boss-btn" onClick={()=>{setView(null);setAttempt(value=>value+1);}}>重新读取完成核查</button></>:current.data?<>
      <p>{completionStateLine(current.data)} · 核查版本 {current.data.inspection_revision} · 当前运行版本 {current.data.run_revision} · 目标版本 {current.data.goal_revision}</p>
      {completionVersionNotice(current.data)&&<p role="status">{completionVersionNotice(current.data)}</p>}
      <h4>{current.data.stale?"历史核查阻断项":"阻断项"}</h4>
      {current.data.blockers.length?<ul>{current.data.blockers.map(value=><li key={value}>{completionBlockerLabel(value)}（{value}）</li>)}</ul>:<p>当前没有阻断项。</p>}
      <h4>输出核查</h4>
      {current.data.output_checks.length?<ul>{current.data.output_checks.map(item=><li key={item.type}>{outputLabels[item.type]??item.type} · {outputStateLabels[item.state]??item.state}</li>)}</ul>:<p>当前没有输出核查记录。</p>}
      {current.data.brief_section_audits.map(item=><div key={item.artifact_id}>
        <h4>会议简报 {item.artifact_id} · 版本 {item.version}</h4>
        {item.section_audit?<><p>章节核查状态 {briefAuditLabel(item.section_audit.completion_state)}</p><ul>{item.section_audit.sections.map((section,index)=><li key={index}>{briefAuditLabel(section.kind)} · {briefAuditLabel(section.status)} · {briefAuditLabel(section.reason)}</li>)}</ul>{item.section_audit.gaps.length>0&&<ul>{item.section_audit.gaps.map((gap,index)=><li key={index}>{briefAuditLabel(gap.kind)} · {briefAuditLabel(gap.reason)}{gap.source_id?" · "+gap.source_id:""}</li>)}</ul>}</>:<p>章节核查不可用。</p>}
      </div>)}
      <h4>必要成果</h4>
      <p>目标版本 {current.data.requirements.goal_revision} · {current.data.requirements.state==="CONFIRMED"&&current.data.requirements.required_outputs?"已确认 "+current.data.requirements.required_outputs.map(value=>outputLabels[value]??value).join("、"):current.data.requirements.state==="UNAVAILABLE"?"成果要求不可核查":"等待本人确认"}</p>
      <button type="button" className="boss-btn" onClick={()=>{setView(null);setAttempt(value=>value+1);}}>重新读取完成核查</button>
    </>:null}
  </section>;
}
