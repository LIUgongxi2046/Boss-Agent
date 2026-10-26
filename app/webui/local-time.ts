import {DateTime,Info} from "luxon";

type TimeFields={date:string;time:string;occurrence:string;issue:string};
type TimeChoice={value:string;label:string};
type TimeCheck={issue:string;choices:TimeChoice[];value?:string;local?:string;owner?:string;utc?:string;offset?:string;daylight?:boolean;crossDay?:boolean};

export function initialLocalTime(value:string,zone:string):TimeFields{
  if(!value)return {date:"",time:"",occurrence:"",issue:""};
  const parsed=DateTime.fromISO(value,{setZone:true});
  if(!parsed.isValid||parsed.zone.type!=="fixed"||!Info.isValidIANAZone(zone))return {date:"",time:"",occurrence:"",issue:"原期限或IANA时区无效，请核查原对象后重新选择。"};
  const local=parsed.setZone(zone);
  return {date:local.toISODate()!,time:local.toISOTime({includeOffset:false,suppressMilliseconds:true})!,occurrence:local.toISO({suppressMilliseconds:true})!,issue:""};
}

export function checkLocalTime(date:string,time:string,zone:string,occurrence:string,businessClock:string|undefined,ownerZone:string|undefined):TimeCheck{
  const empty={choices:[] as TimeChoice[]};
  if(!date||!time)return {...empty,issue:"请选择本次日期与具体时间。"};
  if(!zone||!Info.isValidIANAZone(zone))return {...empty,issue:"请填写有效的IANA时区。"};
  const input=date+"T"+time,wall=DateTime.fromISO(input,{zone:"UTC"}),local=DateTime.fromISO(input,{zone});
  if(!wall.isValid||!local.isValid)return {...empty,issue:"日期或时间无效，请检查对应字段。"};
  if(local.toFormat("yyyy-MM-dd HH:mm:ss")!==wall.toFormat("yyyy-MM-dd HH:mm:ss"))return {...empty,issue:"该当地时间因夏令时调整不存在，请选择其他时间。"};
  const candidates=local.getPossibleOffsets();
  const choices=candidates.map(value=>({value:value.toISO({suppressMilliseconds:true})!,label:"UTC"+value.toFormat("ZZ")+" · "+(value.isInDST?"夏令时":"标准时间")}));
  const selected=candidates.length===1?candidates[0]:candidates.find(value=>value.toISO({suppressMilliseconds:true})===occurrence);
  if(!selected)return {issue:"该当地时间对应两个UTC时差，请明确选择本次采用的时间。",choices};
  const clock=businessClock?DateTime.fromISO(businessClock,{setZone:true}):null;
  if(!clock?.isValid||clock.zone.type!=="fixed")return {issue:"尚未取得包含明确时区的业务时钟，请重新读取。",choices};
  if(selected.toMillis()<=clock.toMillis())return {issue:"交办期限必须晚于当前业务时钟。",choices};
  const owner=ownerZone&&Info.isValidIANAZone(ownerZone)?selected.setZone(ownerZone):null;
  return {issue:"",choices,value:selected.toISO({suppressMilliseconds:true})!,local:selected.setLocale("zh-CN").toLocaleString(DateTime.DATETIME_FULL_WITH_SECONDS),owner:owner?.setLocale("zh-CN").toLocaleString(DateTime.DATETIME_FULL_WITH_SECONDS),utc:selected.toUTC().toISO()!,offset:selected.toFormat("ZZ"),daylight:selected.isInDST,crossDay:owner?owner.toISODate()!==selected.toISODate():undefined};
}
