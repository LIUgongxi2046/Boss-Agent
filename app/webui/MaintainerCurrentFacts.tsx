import {useState} from "react";
import {V7Fact,V7Panel,V7Pagination} from "./BossV7UI";

export type EffectiveRuntime={configuration_version:string;provider:string;model_id:string;api_type:string;enabled:boolean;max_tool_rounds:number;max_output_tokens:number|null;timeout:number;workspace_read_mode:string|null;tool_scope:string[];workspace_projections:string[];custom_prompt_count:number;configuration_mutated:false};
export type CurrentBusinessRecord={kind:string;id:string;version:string;title:string|null;state:string;at:string;author_name:string|null;related_object_id:string|null;source_refs:{source_id:string;version:string}[]};
export type ObservedRun={run_id:string;state:string;started_at:string;finished_at:string|null;model_id:string;configuration_version:string;dataset_id:string|null;dataset_version:string|null;model_requests:number;tool_results:number;external_model_invoked:boolean;formal_evaluation_passed:boolean};

export function CurrentRuntimeConfiguration({value}:{value:EffectiveRuntime}){
  return <V7Panel title="当前实际运行配置" description="读取Boss Agent当前配置；查看不会保存或启用配置。">
    <div className="boss-form-grid"><V7Fact label="Provider / 模型">{value.provider} / {value.model_id}</V7Fact><V7Fact label="配置版本">{value.configuration_version}</V7Fact><V7Fact label="模型调用轮次 / 输出token">{value.max_tool_rounds} / {value.max_output_tokens??"当前配置未记录"}</V7Fact><V7Fact label="运行时限">{value.timeout} 秒</V7Fact><V7Fact label="当前工具范围">{value.tool_scope.length} 项</V7Fact><V7Fact label="自定义Prompt">{value.custom_prompt_count} 项已启用</V7Fact></div>
    {value.custom_prompt_count===0&&<p className="boss-v7-note">当前没有启用自定义Prompt版本，Boss Agent继续采用内置运行规则。新增草稿需要单独保存和启用。</p>}
    <details><summary>查看当前工具及资料范围</summary><p>{value.tool_scope.join("、")}</p><p>资料投影：{value.workspace_projections.length?value.workspace_projections.join("、"):"当前配置未记录额外投影"}</p></details>
  </V7Panel>;
}

export function CurrentBusinessRecords({records,title="当前业务对象与反馈"}:{records:CurrentBusinessRecord[];title?:string}){
  const [page,setPage]=useState(1);
  const currentPage=Math.min(page,Math.max(1,Math.ceil(records.length/10)));
  const labels:Record<string,string>={task:"交办",feedback:"业务反馈",event:"业务事件"};
  return <V7Panel title={title} description="直接读取Boss端当前业务空间，编号、状态、期限与来源采用已保存记录。">
    <div className="boss-v7-table-scroll"><table className="boss-v7-table"><thead><tr><th>类别与事项</th><th>当前状态</th><th>责任人或作者</th><th>业务时间</th><th>对象与来源</th></tr></thead><tbody>{records.slice((currentPage-1)*10,currentPage*10).map(row=><tr key={row.kind+":"+row.id}><td>{labels[row.kind]??row.kind} · {row.title??"当前记录未提供事项说明"}</td><td>{row.state}</td><td>{row.author_name??"当前记录未提供"}</td><td>{row.at}</td><td>{row.id} · v{row.version}{row.related_object_id&&<p>关联对象：{row.related_object_id}</p>}{row.source_refs.map(source=><p key={source.source_id}>{source.source_id} · v{source.version}</p>)}</td></tr>)}</tbody></table></div>
    <V7Pagination page={currentPage} total={records.length} pageSize={10} onChange={setPage}/>
  </V7Panel>;
}

export function ObservedAgentRuns({records,onOpenRun}:{records:ObservedRun[];onOpenRun:(id:string)=>void}){
  const [page,setPage]=useState(1);
  const currentPage=Math.min(page,Math.max(1,Math.ceil(records.length/10)));
  return <V7Panel title="已有实际运行记录" description="展示Boss端已保存的运行与工具调用；正式评测结果继续按实际评测记录显示。">
    <div className="boss-v7-table-scroll"><table className="boss-v7-table"><thead><tr><th>运行与状态</th><th>模型与配置</th><th>数据集</th><th>实际调用</th><th>时间</th></tr></thead><tbody>{records.slice((currentPage-1)*10,currentPage*10).map(row=><tr key={row.run_id}><td><button className="boss-btn" onClick={()=>onOpenRun(row.run_id)}>{row.run_id}</button><p>{row.state}</p></td><td>{row.model_id} · 配置v{row.configuration_version}</td><td>{row.dataset_id??"原记录未保存"} · {row.dataset_version??"原记录未保存"}</td><td>{row.external_model_invoked?"真实模型":"未记录实际外部调用"}<p>{row.model_requests}次请求 / {row.tool_results}项工具结果</p></td><td>{row.started_at}<p>{row.finished_at??"运行尚未结束"}</p></td></tr>)}</tbody></table></div>
    <V7Pagination page={currentPage} total={records.length} pageSize={10} onChange={setPage}/>
  </V7Panel>;
}
