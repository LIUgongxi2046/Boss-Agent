import {useId, type ReactNode} from "react";
import {FolderOpen, Loader2, AlertCircle, ChevronLeft, ChevronRight} from "lucide-react";

export function V7Panel({title,description,action,children,className=""}:{title:string;description?:string;action?:ReactNode;children:ReactNode;className?:string}){
  const id=useId();
  return <section className={"boss-panel boss-v7-panel "+className} aria-labelledby={id}><header className="boss-panel-head"><div><h2 id={id}>{title}</h2>{description&&<p className="boss-v7-description">{description}</p>}</div>{action}</header>{children}</section>;
}

export function V7Empty({title="当前范围没有记录",children}:{title?:string;children?:ReactNode}){
  return <div className="boss-v7-empty"><FolderOpen size={25} aria-hidden="true"/><strong>{title}</strong>{children&&<p>{children}</p>}</div>;
}

export function V7ReadState({loading,error,onReload}:{loading:boolean;error?:string;onReload?:()=>void}){
  if(error)return <div className="boss-status boss-status-error" role="alert"><AlertCircle size={18}/><div><p>{error}</p>{onReload&&<button className="boss-btn" onClick={onReload}>刷新</button>}</div></div>;
  if(loading)return <div className="boss-status" role="status"><Loader2 size={18} className="boss-spin"/>正在读取当前资料与状态</div>;
  return null;
}

export function V7Fact({label,children}:{label:string;children:ReactNode}){
  return <div className="boss-kv"><span>{label}</span><strong>{children}</strong></div>;
}

export function V7Tabs<T extends string>({label,items,value,onChange}:{label:string;items:readonly {id:T;title:string;count?:number}[];value:T;onChange:(value:T)=>void}){
  const prefix=useId();
  return <div className="boss-v7-tabs" role="tablist" aria-label={label}>{items.map((item,index)=><button type="button" key={item.id} id={prefix+item.id} role="tab" aria-selected={item.id===value} tabIndex={item.id===value?0:-1} onClick={()=>onChange(item.id)} onKeyDown={event=>{
    const next=event.key==="ArrowRight"?(index+1)%items.length:event.key==="ArrowLeft"?(index+items.length-1)%items.length:event.key==="Home"?0:event.key==="End"?items.length-1:null;
    if(next===null)return;event.preventDefault();onChange(items[next].id);document.getElementById(prefix+items[next].id)?.focus();
  }}>{item.title}{item.count!==undefined&&<span>{item.count}</span>}</button>)}</div>;
}

export function V7Pagination({page,total,pageSize,onChange}:{page:number;total:number;pageSize:number;onChange:(page:number)=>void}){
  const pages=Math.max(1,Math.ceil(total/pageSize));
  return <nav className="boss-v7-pagination" aria-label="记录分页"><span>共 {total} 条 · 每页 {pageSize} 条</span><div><button type="button" aria-label="上一页" disabled={page<=1} onClick={()=>onChange(page-1)}><ChevronLeft size={16}/></button><span>{page} / {pages}</span><button type="button" aria-label="下一页" disabled={page>=pages} onClick={()=>onChange(page+1)}><ChevronRight size={16}/></button></div></nav>;
}

export function V7Steps({steps}:{steps:readonly {title:string;description:string;state:"complete"|"current"|"waiting"|"failed"}[]}){
  return <ol className="boss-v7-steps">{steps.map((step,index)=><li key={step.title} data-state={step.state}><span className="boss-v7-step-number">{String(index+1).padStart(2,"0")}</span><div><strong>{step.title}</strong><p>{step.description}</p></div><span className="boss-tag">{{complete:"已记录",current:"当前状态",waiting:"等待处理",failed:"需要核查"}[step.state]}</span></li>)}</ol>;
}

export function V7Metric({label,value,note}:{label:string;value:ReactNode;note?:string}){
  return <div className="boss-v7-metric"><span>{label}</span><strong>{value}</strong>{note&&<small>{note}</small>}</div>;
}
