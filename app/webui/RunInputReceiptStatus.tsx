import type {RunInputReceipt} from "./upgrade2-run-client";

export type InputReceiptVersionState = "CURRENT" | "HISTORY" | "AHEAD" | "UNKNOWN";

export function inputReceiptVersionState(receipt: RunInputReceipt, current: number | null): InputReceiptVersionState {
  if (current === null) return "UNKNOWN";
  if (receipt.goal_revision === current) return "CURRENT";
  if (receipt.goal_revision < current) return "HISTORY";
  return "AHEAD";
}

export function RunInputReceiptStatus({receipt, currentGoalRevision}: {receipt: RunInputReceipt; currentGoalRevision: number | null}) {
  const state = inputReceiptVersionState(receipt, currentGoalRevision);
  const base = "输入编号 " + receipt.input_id + " · 输入序号 " + receipt.input_seq + " · 目标版本 " + receipt.goal_revision;
  if (state === "UNKNOWN") return <p role="status">{base + "；当前目标版本尚未读取。"}</p>;
  if (state === "HISTORY") return <p role="status">{base + " · 历史目标版本；当前目标版本 " + currentGoalRevision + "，请以当前版本为准。"}</p>;
  if (state === "AHEAD") return <p role="alert">{base + " 高于当前目标版本 " + currentGoalRevision + "，请重新读取运行。"}</p>;
  return <p role="status">{base + " · 当前目标版本。"}</p>;
}
