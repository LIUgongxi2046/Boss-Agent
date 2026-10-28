import { CheckCircle2, CircleAlert, LoaderCircle, Search } from "lucide-react";
import { parseGenericToolTrace, type GenericToolRunItem } from "@/components/thread/activity/generic-tool-model";
import { ActivityStep } from "@/components/thread/activity/ActivityStep";
import { redactActivityText } from "@/components/thread/activity/activity-text";
import { formatToolCallTrace, mergeToolProgressEvents } from "@/lib/tool-traces";
import type { ToolProgressEvent } from "@/lib/types";

type BossActivityItem = GenericToolRunItem & {event?: ToolProgressEvent};

function technicalText(value: unknown): string {
  return redactActivityText(typeof value === "string" ? value : JSON.stringify(value, null, 2));
}

const operations: Record<string, {title: string; description: string}> = {
  bosssupplyqualityread: {title: "读取采购与品质资料", description: "读取当前获准的业务资料"},
  bosssupplyqualityquery: {title: "查询采购与品质记录", description: "查询本次问题对应的业务记录"},
  bosssupplyqualityprepare: {title: "准备协调材料", description: "依据当前资料准备本人确认内容"},
  create_assignment: {title: "创建交办事项", description: "按当前授权创建任务"},
  send_assignment: {title: "提交交办消息", description: "按当前授权提交消息"},
  todayread: {title: "查看今日工作", description: "读取当前日期的事项、安排与承诺"},
  morninglistread: {title: "读取今日事项", description: "核查当前事项清单和参与原因"},
  morningdetailread: {title: "查看事项内容", description: "读取选中事项的当前状态和关联材料"},
  morningsourceread: {title: "查阅事项依据", description: "读取当前事项关联的有效原文"},
  ownerplansread: {title: "查看本人计划", description: "读取当前计划和执行记录"},
  assignmentsourcesread: {title: "查阅交办材料", description: "核查当前任务关联的来源材料"},
  meetingarrangementread: {title: "查看会议准备", description: "读取会议安排和准备情况"},
  bosscalendarconflictread: {title: "检查时间冲突", description: "核查所选时间内的会议安排"},
  bosscalendarsharepreview: {title: "预览占用时间", description: "读取本人已授权分享的时间范围"},
  bosssectorread: {title: "读取经营专题", description: "查询当前业务指标及关联资料"},
  businessoverviewread: {title: "查询经营情况", description: "读取所选期间的经营指标与比较资料"},
  query_metrics: {title: "计算经营指标", description: "按照查询范围取得指标和比较结果"},
  bossevidenceread: {title: "查阅来源材料", description: "读取获准使用的原文，核查回答依据"},
  bossdashboardread: {title: "查看工作概览", description: "读取当前事项及相关联系人"},
  bosstasksread: {title: "查看任务进展", description: "读取交办、负责人反馈及当前状态"},
  bossmeetingsread: {title: "查看会议安排", description: "读取会议及准备材料"},
  bossworkspaceread: {title: "查阅工作资料", description: "读取本次问题获准使用的业务内容"},
  conversationread: {title: "查看关联记录", description: "读取当前会话绑定的业务对象"},
  read_assignment: {title: "查看交办事项", description: "核查任务内容、期限与处理记录"},
  read_evidence: {title: "查阅相关材料", description: "核查本次问题关联的资料"},
};

export function isBossToolActivity(name: string) { return name in operations; }

export function canRenderBossToolEvents(events: ToolProgressEvent[]) {
  return events.length > 0 && events.every(event => {
    const trace = parseGenericToolTrace(formatToolCallTrace(event) ?? "");
    return Boolean(event.call_id && trace && isBossToolActivity(trace.name));
  });
}

export function BossToolEvents({events, active}: {events: ToolProgressEvent[]; active: boolean}) {
  const merged = events.reduce<ToolProgressEvent[]>((current, event) => mergeToolProgressEvents(current, [event]), []);
  const items = merged.map(event => {
    const trace = parseGenericToolTrace(formatToolCallTrace(event) ?? "");
    if (!trace || !event.call_id || !isBossToolActivity(trace.name)) throw new Error("业务工具事件缺少有效调用信息");
    const status = event.phase === "end" ? "done" : event.phase === "error" ? "error" : "running";
    return {trace, status, observedStatus: status, active, result: event.result, event} satisfies BossActivityItem;
  });
  return <BossToolActivity items={items}/>;
}

function resultSummary(result: unknown): string | null {
  const decoded: unknown = typeof result === "string" ? JSON.parse(result) : result;
  if (!decoded || typeof decoded !== "object" || Array.isArray(decoded)) return null;
  const data = decoded as Record<string, unknown>;
  const counts = [["items", "事项"], ["records", "业务记录"], ["sources", "来源材料"], ["metrics", "经营指标"], ["tasks", "任务"], ["meetings", "会议"], ["topics", "经营专题"]]
    .flatMap(([key, label]) => Array.isArray(data[key]) ? [`${label} ${data[key].length} 项`] : []);
  return counts.length ? counts.join(" · ") : null;
}

export function BossToolActivity({items}: {items: BossActivityItem[]}) {
  return <div className="boss-tool-activity" role="list" aria-label="实际执行过程">{items.map((item, index) => {
    const operation = operations[item.trace.name];
    const status = item.observedStatus;
    const running = status === "running" && item.active;
    const completed = status === "done";
    const failed = status === "error";
    const Icon = running ? LoaderCircle : completed ? CheckCircle2 : failed ? CircleAlert : Search;
    const state = running ? "正在处理" : completed ? "已返回结果" : failed ? "处理失败" : status === "running" ? "处理已停止，结果待确认" : "操作已记录";
    const summary = completed ? resultSummary(item.result) : null;
    const event = item.event;
    const label = [operation.title, event?.name ?? item.trace.name, state, summary].filter(Boolean).join(" · ");
    const argumentsValue = event?.arguments;
    const resultText = item.result !== undefined ? technicalText(item.result) : null;
    return <div role="listitem" key={event?.call_id ?? index} data-state={running ? "running" : completed ? "done" : failed ? "error" : "unknown"}>
      <details className="boss-tool-details">
        <summary aria-label={label + "，展开调用详情"}>
          <ActivityStep icon={Icon} label={label} ariaLabel={label} tooltipContent={label}
            active={Boolean(running)} tone={failed ? "error" : completed ? "success" : running ? "active" : "neutral"}/>
          <span className="boss-tool-expand">调用详情</span>
        </summary>
        <dl className="boss-tool-facts">
          <div><dt>工具</dt><dd><code>{event?.name ?? item.trace.name}</code></dd></div>
          {event?.call_id && <div><dt>调用编号</dt><dd><code>{event.call_id}</code></dd></div>}
          {event?.phase && <div><dt>事件</dt><dd><code>{event.phase}</code></dd></div>}
        </dl>
        {argumentsValue !== undefined && <div className="boss-tool-payload"><strong>调用参数</strong><pre>{technicalText(argumentsValue)}</pre></div>}
        {item.result !== undefined && <div className="boss-tool-payload"><strong>实际返回</strong><pre>{technicalText(item.result)}</pre></div>}
        {event?.error != null && <div className="boss-tool-payload"><strong>错误信息</strong><pre>{technicalText(event.error)}</pre></div>}
        {!event && <p>当前历史记录未保存完整调用事件。</p>}
      </details>
      {event && <div className="boss-tool-call"><code>{redactActivityText(formatToolCallTrace(event) ?? "")}</code></div>}
      {resultText !== null && <div className="boss-tool-result-preview">
        <span>实际返回摘要{resultText.length > 360 ? " · 完整内容见调用详情" : ""}</span>
        <pre>{resultText.slice(0, 360)}{resultText.length > 360 ? "…" : ""}</pre>
      </div>}
    </div>;
  })}</div>;
}
