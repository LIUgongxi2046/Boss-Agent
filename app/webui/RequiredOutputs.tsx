import type {RequiredOutput} from "./upgrade2-run-client";

const options: {value:RequiredOutput;label:string}[] = [
  {value:"TEXT",label:"文字结果"},{value:"BRIEF",label:"简报"},{value:"SOURCE_LIST",label:"来源清单"},
  {value:"ACTION_DRAFT",label:"操作草稿"},{value:"MARKDOWN",label:"Markdown 文件"},{value:"PDF",label:"PDF 文件"},
  {value:"DOCX",label:"Word 文件"},{value:"XLSX",label:"Excel 文件"},{value:"PPTX",label:"PowerPoint 文件"},
  {value:"BUSINESS_RECEIPT",label:"业务回执"},
];

export function describeRequiredOutputs(values:RequiredOutput[]):string {
  return values.map(value=>options.find(option=>option.value===value)!.label).join("、");
}

export function RequiredOutputs({value,onChange,disabled}:{value:RequiredOutput[];onChange:(value:RequiredOutput[])=>void;disabled:boolean}) {
  return <fieldset disabled={disabled}><legend>本人选择必要成果</legend><p>可以选择多项；未选择时保持待确认。提交目标补充时需要重新选择。</p>
    {options.map(option=><label key={option.value}><input type="checkbox" checked={value.includes(option.value)} onChange={event=>onChange(event.target.checked?[...value,option.value]:value.filter(item=>item!==option.value))}/> {option.label}</label>)}
  </fieldset>;
}
