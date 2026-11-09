import test from "node:test";
import assert from "node:assert/strict";
import {orderRunEvents} from "../webui/upgrade2-run-events.ts";

const event = (seq, payload = {}) => ({
  event_id: `event-${seq}`, run_id: "run-1", seq, type: "RUN_STARTED",
  occurred_at: "2026-10-30T00:00:00Z", trace_id: "trace-1", payload_version: 1, payload,
});

test("按序重排，等待缺号并在补齐后继续", () => {
  const first = orderRunEvents("run-1", 0, [event(3), event(1), event(3)]);
  assert.deepEqual(first.contiguous.map(item => item.seq), [1]);
  assert.deepEqual(first.pending.map(item => item.seq), [3]);
  assert.equal(first.after_seq, 1);
  assert.equal(first.missing_seq, 2);
  const replay = orderRunEvents("run-1", first.after_seq, [...first.events, event(2), event(3)]);
  assert.deepEqual(replay.contiguous.map(item => item.seq), [2, 3]);
  assert.deepEqual(replay.pending, []);
  assert.equal(replay.after_seq, 3);
  assert.equal(replay.missing_seq, null);
});

test("快照游标之后开始，空输入不推断缺号", () => {
  assert.deepEqual(orderRunEvents("run-1", 7, []).after_seq, 7);
  const result = orderRunEvents("run-1", 7, [event(9), event(8), event(6)]);
  assert.deepEqual(result.contiguous.map(item => item.seq), [8, 9]);
  assert.equal(result.missing_seq, null);
});

test("相同事件的对象字段顺序不影响去重", () => {
  const a = event(1, {first: 1, second: {x: [1, 2], y: true}});
  const b = event(1, {second: {y: true, x: [1, 2]}, first: 1});
  assert.equal(orderRunEvents("run-1", 0, [a, b]).events.length, 1);
});

test("冲突事件、跨运行事件及无效游标被拒绝", () => {
  assert.throws(() => orderRunEvents("run-1", 0, [event(1), {...event(1), payload: {value: 1}}]), /冲突/);
  assert.throws(() => orderRunEvents("run-1", 0, [event(1), {...event(2), event_id: "event-1"}]), /冲突/);
  assert.throws(() => orderRunEvents("run-1", 0, [{...event(1), run_id: "run-2"}]), /无效/);
  assert.throws(() => orderRunEvents("run-1", 0, [{...event(1), trace_id: ""}]), /无效/);
  assert.throws(() => orderRunEvents("run-1", 0, [{...event(1), seq: 0}]), /无效/);
  assert.throws(() => orderRunEvents("run-1", -1, []), /无效/);
  assert.throws(() => orderRunEvents("run-1", Number.MAX_SAFE_INTEGER + 1, []), /无效/);
});
