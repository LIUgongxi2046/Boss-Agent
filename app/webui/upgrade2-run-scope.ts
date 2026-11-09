export type Upgrade2RunScopeInput = {
  identityKey: string;
  pendingScopeKey: string;
  conversationId: string;
  runId: string | null;
  authToken: string;
};

export function upgrade2RunScopeKey(input: Upgrade2RunScopeInput): string {
  if (!input.identityKey.trim() || !input.pendingScopeKey.trim() || !input.conversationId.trim())
    throw new Error("身份、会话或认证范围标识无效");
  return JSON.stringify([input.identityKey, input.pendingScopeKey, input.conversationId, input.runId, input.authToken]);
}
