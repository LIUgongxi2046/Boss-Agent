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
  return receipt as TodayOrderReceipt;
}
