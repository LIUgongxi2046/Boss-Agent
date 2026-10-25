/**
 * The owner's saved order is global even when F01 displays one category.
 * Moving in a filtered list must exchange adjacent *visible* items while
 * leaving all hidden categories and their positions untouched.
 */
export type TodayOrderCategory = "DECIDE" | "COORDINATE" | "INFORM";
export type TodayOrderFilter = TodayOrderCategory | "ALL";
export type TodayOrderRow = { item_id: string; category: TodayOrderCategory };
export type TodayOrderReceipt = {
  action: string;
  client_request_id: string;
  outcome: "RECORDED" | "NOT_FOUND_IN_CURRENT_STORE";
  result: {
    source_type: "SIMULATED";
    list_id: string;
    list_version: string;
    date: string;
    timezone: string;
    version: string;
    snapshot_sha256: string;
    item_ids: string[];
    authorization_id: string;
  } | null;
  write_performed_by_lookup: false;
};

export function todayOrderPosition(
  order: readonly string[],
  rows: readonly TodayOrderRow[],
  category: TodayOrderFilter,
  selectedId: string,
): { index: number; total: number } {
  const categories = new Map(rows.map(row => [row.item_id, row.category]));
  const visible = order.filter(id => categories.has(id) && (category === "ALL" || categories.get(id) === category));
  return { index: visible.indexOf(selectedId), total: visible.length };
}

export function moveTodayOrderWithinCategory(
  order: readonly string[],
  rows: readonly TodayOrderRow[],
  category: TodayOrderFilter,
  itemId: string,
  direction: -1 | 1,
): string[] | null {
  const categories = new Map(rows.map(row => [row.item_id, row.category]));
  if (!categories.has(itemId) || (category !== "ALL" && categories.get(itemId) !== category)) return null;
  const visible = order.filter(id => categories.has(id) && (category === "ALL" || categories.get(id) === category));
  const position = visible.indexOf(itemId);
  const nextPosition = position + direction;
  if (position < 0 || nextPosition < 0 || nextPosition >= visible.length) return null;
  const sourceIndex = order.indexOf(itemId);
  const targetIndex = order.indexOf(visible[nextPosition]);
  if (sourceIndex < 0 || targetIndex < 0 || sourceIndex === targetIndex) return null;
  const changed = [...order];
  [changed[sourceIndex], changed[targetIndex]] = [changed[targetIndex], changed[sourceIndex]];
  return changed;
}

/** A failed receipt check must surface as a recoverable UI error, not a success. */
export function validateTodayOrderReceipt(value: unknown, requestId: string): TodayOrderReceipt {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("排序原请求回执格式无效");
  }
  const receipt = value as Record<string, unknown>;
  if (receipt.action !== "boss.today.reorder"
    || receipt.client_request_id !== requestId
    || receipt.write_performed_by_lookup !== false
    || (receipt.outcome !== "RECORDED" && receipt.outcome !== "NOT_FOUND_IN_CURRENT_STORE")) {
    throw new Error("排序原请求回执与当前编号不符");
  }
  if (receipt.outcome === "NOT_FOUND_IN_CURRENT_STORE") {
    if (receipt.result !== null) throw new Error("当前库未找到原请求，但回执携带了不应存在的排序结果");
  } else {
    const result = receipt.result;
    if (!result || typeof result !== "object" || Array.isArray(result)) {
      throw new Error("排序原请求缺少经服务端确认的保存结果");
    }
    const recorded = result as Record<string, unknown>;
    if (recorded.source_type !== "SIMULATED"
      || ["list_id", "list_version", "date", "timezone", "version", "authorization_id"].some(
        field => typeof recorded[field] !== "string" || !recorded[field]
      )
      || typeof recorded.snapshot_sha256 !== "string"
      || !/^[0-9a-f]{64}$/.test(recorded.snapshot_sha256)
      || !Array.isArray(recorded.item_ids)
      || recorded.item_ids.some(value => typeof value !== "string" || !value)
      || new Set(recorded.item_ids).size !== recorded.item_ids.length) {
      throw new Error("排序原请求结果缺少完整的已保存清单、来源版本或授权依据");
    }
  }
  return receipt as TodayOrderReceipt;
}

/**
 * Clear an acknowledged original request only if this window still points
 * to that exact identifier. Keep date, selected item and other navigation
 * coordinates unchanged. Unknown responses retain their original URL.
 */
export function withoutTodayOrderRequest(href: string, requestId: string): string | null {
  if (!requestId) return null;
  const address = new URL(href);
  if (address.searchParams.get("todayOrderRequest") !== requestId) return null;
  address.searchParams.delete("todayOrderRequest");
  return address.href;
}

/**
 * The original request can be dismissed only after a server-side read has
 * confirmed it is absent in the current store. Network failure or an invalid
 * response must NEVER unlock a new write silently.
 */
export function isConfirmedMissingTodayOrderReceipt(
  receipt: TodayOrderReceipt | null,
  requestId: string,
): boolean {
  return Boolean(requestId && receipt?.action === "boss.today.reorder"
    && receipt?.client_request_id === requestId
    && receipt?.write_performed_by_lookup === false
    && receipt?.outcome === "NOT_FOUND_IN_CURRENT_STORE"
    && receipt?.result === null);
}
