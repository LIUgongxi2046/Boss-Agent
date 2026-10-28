/**
 * F01 reads the native nanobot binding only by the original request ID.
 * A definitive absence is different from a network/authorization failure;
 * only the former may be explicitly acknowledged by the owner.
 */
export type MorningBinding = {
  binding_id:string; chat_id:string; session_id:string;
  date:string; timezone:string; snapshot_sha256:string; order_version:string;
  list_id:string|null; item_id:string|null; last_request_id:string|null;
};

export type MorningBindingReceipt = {
  client_request_id:string;
  outcome:"RECORDED"|"NOT_FOUND_IN_CURRENT_STORE";
  result:MorningBinding|null;
  write_performed_by_lookup:false;
  source_type?:"SIMULATED";
  adoption_state?:string;
  business_authority_granted?:false;
};

export function validateMorningBindingReceipt(value:unknown,requestId:string):MorningBindingReceipt {
  if (!value || typeof value!=="object" || Array.isArray(value)) {
    throw new Error("晨间原会话绑定回执格式无效");
  }
  const receipt=value as Record<string,unknown>;
  if (receipt.client_request_id!==requestId
      ||receipt.source_type!=="SIMULATED"
      ||receipt.write_performed_by_lookup!==false
      ||receipt.business_authority_granted!==false
      ||receipt.adoption_state!=="NOT_REVALIDATED_BY_LOOKUP"
      ||!["RECORDED","NOT_FOUND_IN_CURRENT_STORE"].includes(String(receipt.outcome))) {
    throw new Error("晨间原会话绑定回执与编号、来源或授权范围不符");
  }
  if (receipt.outcome==="NOT_FOUND_IN_CURRENT_STORE") {
    if (receipt.result!==null)throw new Error("晨间原会话未找到记录但包含绑定结果");
  } else {
    if (!receipt.result || typeof receipt.result!=="object" || Array.isArray(receipt.result)) {
      throw new Error("晨间原会话绑定缺少原始结果");
    }
    const bound=receipt.result as Record<string,unknown>;
    if (bound.binding_id!==requestId
        ||["chat_id","session_id","date","timezone","order_version"].some(
          field=>typeof bound[field]!=="string"||!bound[field]
        )
        ||typeof bound.snapshot_sha256!=="string"
        ||!/^[0-9a-f]{64}$/.test(bound.snapshot_sha256)
        ||["list_id","item_id","last_request_id"].some(field=>
          bound[field]!==null&&(typeof bound[field]!=="string"||!bound[field]))
        ||(bound.item_id!==null&&bound.list_id===null)
        ||(bound.item_id===null&&bound.list_id!==null&&bound.last_request_id===null)) {
      throw new Error("晨间原会话绑定与当前真实会话、事项或快照不一致");
    }
  }
  return receipt as MorningBindingReceipt;
}

export function canAcknowledgeMissingMorningBinding(
  confirmed:MorningBindingReceipt|null,
  requestId:string,
):boolean {
  return Boolean(requestId && confirmed?.client_request_id===requestId
    &&confirmed?.write_performed_by_lookup===false
    &&confirmed?.outcome==="NOT_FOUND_IN_CURRENT_STORE"
    &&confirmed?.result===null);
}
