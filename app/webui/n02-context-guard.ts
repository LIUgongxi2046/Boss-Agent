/**
 * N02 only displays privileged *current* task references when the same
 * authenticated conversation is connected and its last actual read passed.
 * Old references remain available through explicit read-only audit paths,
 * never as current actionable context after a source/auth/read failure.
 */
export type N02Scope = {
  client:unknown; token:string; chatId:string|null;
  role:"BOSS"|"MAINTAINER"; visible:boolean; connectionStatus:string;
};
export type N02ContextRead = {
  current_use_verified:boolean;
  binding_state:string;
  entry:{current_use_verified:boolean}|null;
};
export function isActiveN02Scope(scope:N02Scope):boolean {
  return scope.role==="BOSS" && scope.visible
    && typeof scope.chatId==="string" && scope.chatId.length>0
    && scope.connectionStatus==="open";
}
export function sameActiveN02Scope(request:N02Scope,latest:N02Scope):boolean {
  return isActiveN02Scope(request)&&isActiveN02Scope(latest)
    && request.client===latest.client
    && request.token===latest.token
    && request.chatId===latest.chatId
    && request.role===latest.role;
}
export function mayDisplayCurrentTaskReference(
  context:N02ContextRead|null,
  scope:N02Scope,
  checking:boolean,
  error:string,
):boolean {
  return isActiveN02Scope(scope)
    && !checking && !error
    && context?.binding_state==="BOUND"
    && context.current_use_verified===true
    && context.entry?.current_use_verified===true;
}
