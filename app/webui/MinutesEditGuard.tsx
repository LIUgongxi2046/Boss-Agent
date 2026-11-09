import type {ReactNode} from "react";

type MinuteReference={source_id:string;source_version:string;source_reference_state?:string};
type SourceReference={source_id:string;version:string};

export function minutesEditAvailable({minute,source,loading,stale,referenceBlocked,basis}:{minute:MinuteReference|null;source:SourceReference|null;loading:boolean;stale:boolean;referenceBlocked:boolean;basis:string}):boolean {
  return !loading&&!stale&&!referenceBlocked&&Boolean(basis)&&Boolean(source)&&(!minute||Boolean(source&&minute.source_reference_state==="CURRENT"&&minute.source_id===source.source_id&&minute.source_version===source.version));
}

export function MinutesEditGuard({available,edited,onReload,children}:{available:boolean;edited:boolean;onReload?:()=>void;children:ReactNode}) {
  if(!available)return <div><p role="status">纪要来源或读取权限尚未核查，编辑内容暂不可显示或提交。{edited?"未保存内容仍保留在当前页面。":""}</p>{onReload&&<button type="button" className="boss-btn" onClick={onReload}>重新核查来源与版本</button>}</div>;
  return <>{children}</>;
}
