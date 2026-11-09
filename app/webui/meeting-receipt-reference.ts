export type MeetingReceiptReference={id:string|null;version:string|null};

export function meetingReceiptStatus(reference:MeetingReceiptReference,meeting:{meeting_id:string;version:string}|null):"NONE"|"WAITING"|"CURRENT"|"CHANGED" {
  if(reference.id===null&&reference.version===null)return "NONE";
  if(!reference.id||!reference.version)return "CHANGED";
  if(!meeting)return "WAITING";
  return reference.id===meeting.meeting_id&&reference.version===meeting.version?"CURRENT":"CHANGED";
}
