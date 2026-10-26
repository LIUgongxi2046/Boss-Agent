export type LibraryKind = "meeting" | "document" | "approval" | "research" | "people";

export type LibraryContext = {
  id: string;
  kind: LibraryKind;
  version: string;
  namespace: string;
};

const KINDS: LibraryKind[] = ["meeting", "document", "approval", "research", "people"];

export function readLibraryContext(): LibraryContext | null {
  const raw = new URLSearchParams(window.location.search).get("bossLibraryContext");
  if (!raw) return null;
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!value || typeof value !== "object") return null;
  const candidate = value as Record<string, unknown>;
  if (typeof candidate.id !== "string" || !candidate.id) return null;
  if (typeof candidate.kind !== "string" || !KINDS.includes(candidate.kind as LibraryKind)) return null;
  if (typeof candidate.version !== "string" || typeof candidate.namespace !== "string") return null;
  return { id: candidate.id, kind: candidate.kind as LibraryKind, version: candidate.version, namespace: candidate.namespace };
}

export function readLibraryAction(): string {
  return new URLSearchParams(window.location.search).get("bossLibraryAction") ?? "";
}
