import type {OverviewSelection} from "./business-overview-types";

export type SectorSource={source_id:string;version:string;source_type:string;published_at:string;related_scope:string;validity_state:string;author_display_name?:string;observed_at?:string;received_at?:string;valid_until?:string};
export type SectorMetric={id:string;label:string;value:string|null;unit:string|null;period:string|null;source_ids:string[];state:string;definition_version?:string;coverage?:string;comparability?:string};
export type SectorRecord={id:string;values:Record<string,unknown>;source_ids:string[];version:string;state:string};
export type SectorSection={title:string;state:string;text:string|null;source_ids:string[];author?:string;claim_kind?:"FACT"|"OPINION"|"INFERENCE";limitations?:string[]};
export type SectorActionKind="COORDINATE"|"REVIEW"|"MEETING"|"DECISION";
export type SectorAction={code:string;label:string;kind:SectorActionKind;allowed:boolean;reason:string;option_required?:boolean};
export type SectorProjection={
  projection:"sector-workspace";page_id:string;title:string;source_type:"SIMULATED";namespace:string;dataset_version:string;read_at:string;query_id?:string;business_clock?:string;
  overview_reference?:OverviewSelection;filter_options:Record<string,{id:string;label:string}[]>;applied_filters:Record<string,string>;metrics:SectorMetric[];
  trend:{metric_id:string;unit:string;points:{period:string;value:string|null;source_ids:string[]}[]}|null;
  records:SectorRecord[];sections:SectorSection[];relations:{id:string;label:string;state:string;description:string;source_ids:string[]}[];
  workflow:{title:string;description:string;state:"complete"|"current"|"waiting"|"failed";author?:string;source_ids?:string[];confirmed_at?:string}[];
  sources:SectorSource[];coverage:{label:string;value:string;state:string}[];missing_fields:string[];availability:string;
  contacts?:{contact_id:string;version:string;display_name:string;organization:string;responsibility:string;eligible:boolean}[];
  followup_actions?:SectorAction[];resource_options?:{option_id:string;version:string;title:string;description:string;state:string;source_ids:string[]}[];
  timezones?:string[];owner_timezone?:string;
  followups?:{record_id:string;version:string;kind:SectorActionKind;title:string;state:string;created_at:string;task_id?:string;plan_id?:string;meeting_id?:string;source_ids:string[]}[];
};

export function sectorBasis(value:SectorProjection){
  return JSON.stringify([value.page_id,value.namespace,value.dataset_version,value.query_id,value.applied_filters,value.sources.map(source=>[source.source_id,source.version,source.validity_state]),value.contacts,value.resource_options,value.followup_actions]);
}
