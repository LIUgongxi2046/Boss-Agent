/**
 * The date preview is not a persisted morning list. Only a CURRENT list with
 * the same stable list ID as the displayed projection can open privileged
 * item details or permit item-specific business handoffs.
 */
export type MorningListScope = {
  adoption_state: string;
  result: {list_id: string | null};
} | null;
export type MorningProjectionScope = {list_id: string | null} | null;

export function currentMorningDetailScope(
  list: MorningListScope,
  view: MorningProjectionScope,
): view is {list_id: string} {
  const listId = list?.result?.list_id;
  return list?.adoption_state === "CURRENT"
    && typeof listId === "string"
    && listId.length > 0
    && view?.list_id === listId;
}

export type MorningItemCategory = "DECIDE" | "COORDINATE" | "INFORM";
export type MorningCategoryFilter = MorningItemCategory | "ALL";

/** A hidden or removed item must not remain the source of a visible action. */
export function shouldClearMorningSelectionOnFilter(
  nextCategory: MorningCategoryFilter,
  selectedId: string,
  items: readonly {item_id: string; category: MorningItemCategory}[],
): boolean {
  if (!selectedId) return false;
  const selected = items.find(item => item.item_id === selectedId);
  return !selected || (nextCategory !== "ALL" && selected.category !== nextCategory);
}
