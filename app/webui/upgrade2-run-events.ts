export type RunEventJson = null | boolean | number | string | RunEventJson[] | {[key: string]: RunEventJson};

export type RunEvent = {
  event_id: string;
  run_id: string;
  seq: number;
  type: string;
  occurred_at: string;
  trace_id: string;
  payload_version: number;
  payload: RunEventJson;
};

export type OrderedRunEvents = {
  events: RunEvent[];
  contiguous: RunEvent[];
  pending: RunEvent[];
  after_seq: number;
  missing_seq: number | null;
};

function sameJson(left: RunEventJson, right: RunEventJson): boolean {
  if (left === right) return true;
  if (left === null || right === null || typeof left !== "object" || typeof right !== "object") return false;
  if (Array.isArray(left) || Array.isArray(right)) {
    return Array.isArray(left) && Array.isArray(right) && left.length === right.length && left.every((value, index) => sameJson(value, right[index]));
  }
  const keys = Object.keys(left);
  return keys.length === Object.keys(right).length && keys.every(key => Object.hasOwn(right, key) && sameJson(left[key], right[key]));
}

function sameEvent(left: RunEvent, right: RunEvent): boolean {
  return left.event_id === right.event_id && left.run_id === right.run_id && left.seq === right.seq &&
    left.type === right.type && left.occurred_at === right.occurred_at && left.trace_id === right.trace_id &&
    left.payload_version === right.payload_version && sameJson(left.payload, right.payload);
}

export function orderRunEvents(runId: string, afterSeq: number, received: readonly RunEvent[]): OrderedRunEvents {
  if (!runId || !Number.isSafeInteger(afterSeq) || afterSeq < 0) throw new Error("运行编号或事件游标无效");
  const bySequence = new Map<number, RunEvent>();
  const byId = new Map<string, RunEvent>();
  for (const event of received) {
    if (event.run_id !== runId || !event.event_id || !event.type || !event.occurred_at || !event.trace_id ||
        !Number.isSafeInteger(event.seq) || event.seq < 1 || !Number.isSafeInteger(event.payload_version) || event.payload_version < 1) {
      throw new Error("运行事件字段无效或不属于当前运行");
    }
    const sequenceMatch = bySequence.get(event.seq);
    const idMatch = byId.get(event.event_id);
    if ((sequenceMatch && !sameEvent(sequenceMatch, event)) || (idMatch && !sameEvent(idMatch, event))) {
      throw new Error("运行事件编号或序号存在冲突");
    }
    bySequence.set(event.seq, event);
    byId.set(event.event_id, event);
  }
  const events = [...bySequence.values()].sort((left, right) => left.seq - right.seq);
  const contiguous: RunEvent[] = [];
  const pending: RunEvent[] = [];
  let cursor = afterSeq;
  for (const event of events) {
    if (event.seq <= afterSeq) continue;
    if (event.seq === cursor + 1 && pending.length === 0) {
      contiguous.push(event);
      cursor = event.seq;
    } else {
      pending.push(event);
    }
  }
  return {events, contiguous, pending, after_seq: cursor, missing_seq: pending.length ? cursor + 1 : null};
}
