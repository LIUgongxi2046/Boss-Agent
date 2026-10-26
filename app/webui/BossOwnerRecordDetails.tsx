import {V7Empty,V7Fact} from "./BossV7UI";

export type OwnerRecord={id:string;title:string;kind:string;target_id:string|null;task_id:string|null;version:string;state:string;effective_state:string;
  authorization_version:string|null;action:string|null;authorization_id:string|null;valid_until:string|null;created_at:string;namespace:string;dataset_id:string;source_ids:string[];
  scope:string[];values:{label:string;value:string|null}[];missing:string[];changed_conditions:string[];
  timeline:{id:string;title:string;at:string;state:string;description:string;version:string|null;source_ids:string[]}[];
  can_revoke:boolean;can_continue:boolean;current_target_id:string|null;current_page:string|null;request_id:string|null;
  historical:boolean;archived_at:string|null;current_evidence_eligible:boolean;
  sources:{source_id:string;version:string|null;namespace:string;state:string;current_source_state:string;content:string|null;author:string|null;published_at:string|null}[];
  original_records:{kind:string;id:string;version:string;content:string;decision:string}[]};

const STATE_NAMES:Record<string,string>={CURRENT:"当前有效",EXPIRED:"已到期",REVOKED:"已撤销",EXECUTED:"已执行",READ_ONLY_HISTORY:"历史只读",SUPERSEDED:"已有新版本",NOT_EFFECTIVE:"当前未生效",CURRENT_OBJECT_CHECK_REQUIRED:"需要核查当前对象",RECORDED:"已记录",CONFIRMED:"已确认"};
export function ownerState(state:string){return STATE_NAMES[state]??state;}

export function OwnerConditions({record}:{record:OwnerRecord}){
  return <>
    {record.missing.length>0&&<div className="boss-status boss-status-warn"><h3>缺少条件</h3><ul>{record.missing.map(value=><li key={value}>{value}</li>)}</ul></div>}
    {record.changed_conditions.length>0&&<div className="boss-v7-note"><h3>已变化条件</h3><ul>{record.changed_conditions.map(value=><li key={value}>{value}</li>)}</ul></div>}
  </>;
}

export function OwnerRecordFacts({record}:{record:OwnerRecord}){
  return <>
    <div className="boss-owner-facts">{record.values.map(value=><V7Fact key={value.label} label={value.label}>{value.value??"尚未记录"}</V7Fact>)}</div>
    <V7Fact label="内容版本">{record.version||"尚未记录"}</V7Fact>
    <V7Fact label="有效期">{record.valid_until??"尚未记录"}</V7Fact>
    <V7Fact label="可见范围">{record.scope.join("、")||"尚未记录"}</V7Fact>
    <V7Fact label="记录状态">{ownerState(record.effective_state)}</V7Fact>
    <OwnerConditions record={record}/>
  </>;
}

export function OwnerOriginalRecords({record}:{record:OwnerRecord}){
  return <>{record.original_records.map(row=><article className="boss-workspace-item" key={row.kind+row.id}>
    <strong>{row.kind} · {row.id} · v{row.version}</strong><p>{ownerState(row.decision)}</p><blockquote className="boss-source">{row.content}</blockquote>
  </article>)}{!record.original_records.length&&<V7Empty title="当前权限内没有已保存的原始正文"/>}</>;
}

export function OwnerSources({record,onViewSource}:{record:OwnerRecord;onViewSource:(id:string)=>void}){
  return <>{record.sources.map(source=><article className="boss-workspace-item" key={source.namespace+":"+source.source_id+":"+source.version}>
    <strong>{source.source_id} · {source.version?"v"+source.version:"当时版本未记录"}</strong>
    <p>{source.namespace} · {source.state}</p>
    <V7Fact label="来源当前有效性">{source.current_source_state}</V7Fact>
    <V7Fact label="原作者">{source.author??"未记录"}</V7Fact>
    <V7Fact label="原发布时间">{source.published_at??"未记录"}</V7Fact>
    {source.content!==null?<blockquote className="boss-source">{source.content}</blockquote>:<p>当前权限内没有可读取的当时版本正文。</p>}
    {!record.historical&&<button className="boss-btn" onClick={()=>onViewSource(source.source_id)}>查看当前来源状态</button>}
  </article>)}{!record.sources.length&&<V7Empty title="尚无获准的来源引用"/>}</>;
}

export function OwnerEventTimeline({record}:{record:OwnerRecord}){
  return <><div className="boss-v7-timeline">{record.timeline.map(row=><article key={row.id}>
    <time dateTime={row.at}>{row.at||"未记录时间"}</time><strong>{row.title} · {ownerState(row.state)}</strong><p>{row.description}</p>
    <small>{row.version?"版本 "+row.version:"未记录版本"}</small><p>{row.source_ids.join("、")}</p>
  </article>)}</div>{!record.timeline.length&&<V7Empty title="当前记录没有时间线条目"/>}</>;
}

export function OwnerRecordIdentity({record}:{record:OwnerRecord}){
  return <><V7Fact label="记录编号">{record.id}</V7Fact><V7Fact label="目标对象">{record.target_id??"未关联"}</V7Fact>
    <V7Fact label="内容版本">{record.version||"尚未记录"}</V7Fact><V7Fact label="原执行空间">{record.namespace}</V7Fact>
    <V7Fact label="原数据集">{record.dataset_id}</V7Fact><V7Fact label="授权引用">{record.authorization_id??"未关联"}</V7Fact>
    <V7Fact label="当前对应事项">{record.current_target_id??"没有可访问的对应事项"}</V7Fact>
  </>;
}
