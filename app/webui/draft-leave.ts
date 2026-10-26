export type DraftLeaveHandle={
  object:string;
  version:string;
  changedFields:string[];
  canSave:boolean;
  unavailableReason:string;
  beginSave:(onSaved:()=>void)=>boolean;
};
export type DraftLeaveRegistration=(handle:DraftLeaveHandle|null)=>void;
