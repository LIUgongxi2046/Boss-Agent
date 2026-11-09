import type {LibraryContext} from "./library-context";

export type MinutesReceiptReference={id:string|null;version:string|null};

export function minutesReceiptStatus(reference:MinutesReceiptReference,minute:{minute_id:string;version:string}|null,loading:boolean):"NONE"|"WAITING"|"CURRENT"|"CHANGED" {
  if(reference.id===null&&reference.version===null)return "NONE";
  if(!reference.id||!reference.version)return "CHANGED";
  if(loading)return "WAITING";
  return minute&&reference.id===minute.minute_id&&reference.version===minute.version?"CURRENT":"CHANGED";
}

export function minutesLibraryMismatch(reference:LibraryContext|null,projection:{namespace:string;meeting:{meeting_id:string;version:string}}|null):boolean {
  return Boolean(reference?.kind==="meeting"&&projection&&(reference.id!==projection.meeting.meeting_id||reference.version!==projection.meeting.version||reference.namespace!==projection.namespace));
}
