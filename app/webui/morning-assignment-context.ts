/**
 * F01 -> F06 uses the existing server-validated morning detail, not a
 * hand-written allowlist of dataset names. The BOSS still confirms creation
 * separately; these references do not grant authority.
 */
export type MorningAssignmentReference = {
  list_id:string; list_version:string; item_id:string; snapshot_sha256:string;
};
export type MorningPreparationContext = {
  source_ids:string[]; meeting_id:string|null; event_ids:string[];
};
type ItemReference = {kind:string; id:string; version:string|null};
export type MorningAssignmentDetail = {
  source_type:"SIMULATED";
  list_id:string; list_version:string; snapshot_sha256:string;
  business_authorization_granted:false;
  item:{
    item_id:string;
    source_refs:ItemReference[];
    related_meetings?:ItemReference[];
  };
  documents:{source_id:string;version:string;source_type?:string}[];
};

export function prepareMorningAssignmentContext(
  selection:MorningAssignmentReference,
  detail:MorningAssignmentDetail,
):MorningPreparationContext {
  if(detail.source_type!=="SIMULATED" || detail.business_authorization_granted!==false
      ||detail.list_id!==selection.list_id
      ||detail.list_version!==selection.list_version
      ||detail.snapshot_sha256!==selection.snapshot_sha256
      ||detail.item.item_id!==selection.item_id)
    throw new Error("晨间清单或选中事项与准备交办引用不符，请重新查询");

  const references=detail.item.source_refs.filter(ref=>ref.kind==="document");
  const supplied=new Map<string, {source_id:string;version:string;source_type?:string}>();
  for(const document of detail.documents){
    if(!document.source_id||!document.version
        ||(document.source_type!==undefined&&document.source_type!=="SIMULATED")
        ||supplied.has(document.source_id))
      throw new Error("当前事项原文来源不完整或存在重复，不能用于交办");
    supplied.set(document.source_id,document);
  }
  if(supplied.size!==references.length)
    throw new Error("晨间事项的来源引用与正式原文不一致，请重新核查");

  const source_ids:string[]=[];
  for(const ref of references){
    const document=supplied.get(ref.id);
    if(!ref.id||!ref.version||!document||document.version!==ref.version
        ||source_ids.includes(ref.id))
      throw new Error("晨间事项来源版本不匹配，请重新核查后交办");
    source_ids.push(ref.id);
  }

  const meetings=detail.item.related_meetings??[];
  if(meetings.some(meeting=>meeting.kind!=="meeting"||!meeting.id||!meeting.version))
    throw new Error("晨间事项关联会议的版本不完整");
  const event_ids:string[]=[];
  for(const ref of detail.item.source_refs.filter(ref=>ref.kind==="event")){
    if(!ref.id||!ref.version||event_ids.includes(ref.id))
      throw new Error("晨间事项关联事件的版本不完整");
    event_ids.push(ref.id);
  }
  return {
    source_ids,
    meeting_id:meetings[0]?.id??null,
    event_ids,
  };
}
