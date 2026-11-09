import type {ReactNode} from "react";

export function OpenLinkedAssignment({taskId,version,disabled,onOpenTask,children,className="boss-btn"}:{taskId:string;version:string;disabled:boolean;onOpenTask:(id:string,version:string)=>void;children:ReactNode;className?:string}) {
  return <button type="button" className={className} disabled={disabled} onClick={()=>onOpenTask(taskId,version)}>{children}</button>;
}
