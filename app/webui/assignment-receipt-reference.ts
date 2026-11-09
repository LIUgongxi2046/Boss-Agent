export type AssignmentReceiptReference={id:string|null;version:string|null};

export function assignmentReceiptStatus(reference:AssignmentReceiptReference,task:{task_id:string;version?:string}|null,loading:boolean):"NONE"|"WAITING"|"CURRENT"|"CHANGED" {
  if(reference.id===null&&reference.version===null)return "NONE";
  if(!reference.id||!reference.version)return "CHANGED";
  if(loading)return "WAITING";
  return task&&reference.id===task.task_id&&reference.version===task.version?"CURRENT":"CHANGED";
}
