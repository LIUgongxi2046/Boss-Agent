/**
 * N02 attachments are native SessionManager metadata, not runtime artifacts.
 * Their status can change while the latest run ID and run status stay identical:
 * upload, external file removal or content replacement must all be reread.
 */
export type N02Attachment = {
  attachment_id:string;
  stored_name:string|null;
  original_name:string|null;
  mime_type:string|null;
  size_bytes:number|null;
  content_sha256:string|null;
  recorded_size_bytes:number|null;
  recorded_content_sha256:string|null;
  user_message_index:number|null;
  processing_state:"STORED"|"MISSING"|"CHANGED"|"REFERENCE_UNAVAILABLE";
};

export type N02AttachmentReadMarker={runMarker:string;checkedAt:number};
const ALLOWED_STATES=new Set(["STORED","MISSING","CHANGED","REFERENCE_UNAVAILABLE"]);
const SHA256=/^[a-f0-9]{64}$/;

export function shouldRefreshN02Attachments(
  last:N02AttachmentReadMarker|null,
  runMarker:string,
  now:number,
  intervalMs=5000,
):boolean {
  if(!Number.isFinite(now)||now<0||!Number.isFinite(intervalMs)||intervalMs<=0)
    throw new Error("附件核查时间无效");
  return last===null || last.runMarker!==runMarker
    || now<last.checkedAt || now-last.checkedAt>=intervalMs;
}

function object(value:unknown):value is Record<string,unknown> {
  return value!==null&&typeof value==="object"&&!Array.isArray(value);
}
function nullableString(value:unknown):boolean {
  return value===null||typeof value==="string";
}
function sha(value:unknown):boolean {
  return value===null||(typeof value==="string"&&SHA256.test(value));
}
function size(value:unknown):boolean {
  return value===null||(typeof value==="number"&&Number.isSafeInteger(value)&&value>=0);
}
function fileName(value:unknown):boolean {
  return value===null||(typeof value==="string"&&value.length>0&&!/[\\/\x00]/.test(value));
}

/** Reject a misrouted/forged response rather than display another chat's files. */
export function validateN02AttachmentRead(value:unknown,chatId:string):N02Attachment[] {
  if(!chatId||!object(value)
    ||value.source_type!=="RUNTIME_RECORD"
    ||value.chat_id!==chatId
    ||value.session_id!=="websocket:"+chatId
    ||value.business_authorization_granted!==false
    ||(value.session_state!=="SAVED"&&value.session_state!=="NO_SAVED_SESSION")
    ||!Array.isArray(value.attachments))
    throw new Error("当前附件读取不属于本人会话或原生保存范围");
  if(value.session_state==="NO_SAVED_SESSION"&&value.attachments.length)
    throw new Error("不存在原生会话却返回了附件");
  const ids=new Set<string>();
  for(const file of value.attachments) {
    if(!object(file)
      ||typeof file.attachment_id!=="string"||!file.attachment_id.startsWith("attachment-")
      ||ids.has(file.attachment_id)
      ||!fileName(file.stored_name)
      ||!fileName(file.original_name)
      ||!nullableString(file.mime_type)
      ||!size(file.size_bytes)
      ||!size(file.recorded_size_bytes)
      ||!sha(file.content_sha256)
      ||!sha(file.recorded_content_sha256)
      ||(file.user_message_index!==null
        &&(!Number.isSafeInteger(file.user_message_index)||Number(file.user_message_index)<0))
      ||!ALLOWED_STATES.has(String(file.processing_state)))
      throw new Error("当前会话附件元信息、版本或保存状态无效");
    ids.add(file.attachment_id);
  }
  return value.attachments as N02Attachment[];
}
