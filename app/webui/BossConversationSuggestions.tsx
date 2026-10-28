import {CalendarDays, ChartNoAxesCombined, ClipboardList, Files} from "lucide-react";

const suggestions = [
  {title: "安排今日工作", icon: CalendarDays, prompt: "今天有哪些事情需要我决定、协调或知晓？请按紧急程度说明原因和建议。"},
  {title: "了解经营情况", icon: ChartNoAxesCombined, prompt: "原料与饲料当前有哪些经营问题？请说明相关指标、资料依据和处理建议。"},
  {title: "跟进任务进展", icon: ClipboardList, prompt: "当前任务和承诺有哪些需要我跟进？请列出负责人、期限和下一步建议。"},
  {title: "查看会议与资料", icon: Files, prompt: "最近有哪些会议和相关资料需要我关注？请说明会议安排和准备事项。"},
];

export function BossConversationSuggestions({onSelect}: {onSelect: (prompt: string) => void}) {
  return <section className="boss-chat-suggestions" aria-label="提问示例">
    <div className="boss-chat-suggestions-label">可以从这些问题开始</div>
    <div className="boss-chat-suggestions-grid">
      {suggestions.map(({title, icon: Icon, prompt}) => <button type="button" key={title}
        className="boss-chat-suggestion" onClick={() => onSelect(prompt)}>
        <span className="boss-chat-suggestion-heading"><Icon size={18} aria-hidden="true"/><strong>{title}</strong></span>
        <span>{prompt}</span>
      </button>)}
    </div>
  </section>;
}
