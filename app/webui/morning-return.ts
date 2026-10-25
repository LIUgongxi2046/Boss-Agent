/**
 * F01 return-point data contains only technical identifiers and a scroll
 * coordinate. Source IDs and item IDs can contain colons (e.g. task:...).
 * Reject unrelated arbitrary DOM IDs or private text in URL parameters.
 */
export type MorningReturnPoint = { focus: string; scroll: number };
const SAFE_MORNING_FOCUS = /^morning-[A-Za-z0-9_:.-]{1,256}$/;

export function isSafeMorningFocusId(value: unknown): value is string {
  return typeof value === "string" && SAFE_MORNING_FOCUS.test(value);
}

export function readMorningReturnPoint(
  focus: string | null,
  scroll: string | null,
): MorningReturnPoint | null {
  if (!isSafeMorningFocusId(focus) || scroll === null || scroll.trim() === "") return null;
  const coordinate = Number(scroll);
  if (!Number.isFinite(coordinate) || coordinate < 0) return null;
  return { focus, scroll: coordinate };
}
