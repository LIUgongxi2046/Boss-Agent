export function brandMessages<T>(value:T):T{
  if(typeof value==="string")return value.replace(/(?<![.\w/-])nanobot(?![\w/-]|\s+(?:gateway|onboard|status|agent)\b)/gi,"Boss Agent").replaceAll("大鹏","Boss Agent") as T;
  if(Array.isArray(value))return value.map(brandMessages) as T;
  if(value!==null&&typeof value==="object")return Object.fromEntries(Object.entries(value).map(([key,item])=>[key,brandMessages(item)])) as T;
  return value;
}
