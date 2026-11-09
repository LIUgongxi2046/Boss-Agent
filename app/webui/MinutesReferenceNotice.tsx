import {minutesReceiptStatus,type MinutesReceiptReference} from "./minutes-reference";

export function MinutesReferenceNotice({reference,minute,loading}:{reference:MinutesReceiptReference;minute:{minute_id:string;version:string}|null;loading:boolean}) {
  const status=minutesReceiptStatus(reference,minute,loading);
  if(status==="NONE")return null;
  return <div role={status==="CHANGED"?"alert":"status"} className="boss-status boss-status-warn">本人决定回执：纪要 {reference.id??"编号缺失"} · 版本 {reference.version??"版本缺失"}。{status==="CURRENT"?"当前纪要版本已经核查。":status==="WAITING"?"正在读取当前纪要。":"当前纪要与回执不同，相关操作不可用。"}</div>;
}
