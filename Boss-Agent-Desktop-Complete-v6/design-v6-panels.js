/* Desktop V6 page-specific refinements from desktop-design-review-v5. Static design preview only. */
(()=>{
const C=(label,inner,sub='')=>`<section class="v6-panel"><div class="v6-sectionhead"><div><h2>${label}</h2>${sub?`<p class="v6-desc">${sub}</p>`:''}</div></div>${inner}</section>`;
const B=(label,act='',kind='')=>`<button type="button" class="v6-btn ${kind}" data-act="${act||label}">${label}</button>`;
const G=(label,id,kind='')=>`<button type="button" class="v6-btn ${kind}" data-go="${id}">${label} ↗</button>`;
const X=(label='',data='',type='text',hint='')=>`<label class="v6-field"><span>${label}</span>${type==='textarea'?`<textarea data-persist="${label}" placeholder="${data||'待填写'}"></textarea>`:type==='select'?`<select data-persist="${label}"><option value="">${data||'请选择'}</option>${hint.split('|').filter(Boolean).map(a=>`<option>${a}</option>`).join('')}</select>`:`<input type="${type}" data-persist="${label}" ${type==='text'?`placeholder="${data||'待提供'}"`:''} value="${data && type==='text' && data.startsWith('Asia/') ? data : ''}"/>`}${hint && type!=='select'?`<small>${hint}</small>`:''}</label>`;
const R=(key,val='待核查')=>`<div class="v6-kv"><span class="key">${key}</span><span class="val">${val}</span></div>`;
const T=(...labels)=>`<div class="v6-tabs" data-tabs="true">${labels.map((a,i)=>`<button type="button" class="v6-tab ${i===0?'selected':''}" data-tab="${a}">${a}</button>`).join('')}</div>`;
const Note=(text,kind='')=>`<div class="v6-note ${kind}">${text}</div>`;
const Empty=(text)=>`<div class="v6-empty"><div class="v6-icon">◈</div><div><b>暂无可验证的业务记录</b><div>${text}</div></div></div>`;
const Action=(...bs)=>`<div class="v6-actions">${bs.join('')}</div>`;
const columns=(left,right)=>`<div class="v6-grid"><div class="v6-stack">${left}</div><div class="v6-stack">${right}</div></div>`;
const split=(a,b)=>`<div class="v6-grid split">${a}${b}</div>`;
const textArea=(label,ph='请填写此项的具体内容')=>X(label,ph,'textarea');
const check=(t)=>`<label class="v6-check"><input type="checkbox"/>${t}</label>`;
const litem=(h,detail='',target='',chip='')=>`<div class="v6-item ${target?'selectable':''}" ${target?`data-go="${target}"`:''}><span class="v6-icon">✓</span><div class="v6-grow"><b>${h}</b><p>${detail}</p></div>${chip?`<span class="v6-chip">${chip}</span>`:''}${target?' →':''}</div>`;
const form=(...fields)=>`<div class="v6-formgrid">${fields.join('')}</div>`;
const TOPIC=['原料与饲料','水产季节','苗种批次','动保与技服','生猪合作','禽类与反刍','公司水产养殖','食品与品质','海外业务','研发应用'];
const home=()=>columns(
 C('业务日期与资料范围',`<div class="v6-formgrid cols3">${X('业务日期','','date')}${X('IANA 时区','Asia/Shanghai','text')}${X('资料截至时间','尚未读取')}</div>${Action(B('更新当前事项','refresh','primary'))}${Note('资料范围尚未读取：本人事项、会议承诺、关联交办和时间冲突均需从有权来源核查。')}`)+
 C('今天需要我参与的事',`${T('待决定','待协调','需要知晓')}<div class="v6-list">${litem('当前事项待读取','排序理由：待核查 · 处理人：待核查 · 本人参与原因：待核查 · 有效期限：未知 · 状态：未加载')}</div>${Note('设计状态可切换到“事项可读、部分资料未更新、排序失败”；不预设真实老板任务。')}${Action(B('上移 ↑','reorder-up'),B('下移 ↓','reorder-down'),B('调整次序','reorder'),B('继续讨论','start-chat','primary'))}`)+
 C('交给 Boss Agent',`${textArea('本次需求','描述要推进的事项，提交后进入连续对话；保留当前日期与事项引用')}${Action(G('语音输入','F27'),B('提交需求','submit-home','primary'))}`),
 C('选中事项与关联对象',`${R('对象与当前版本')}${R('关联来源')}${R('关联会议')}${R('交办记录')}${Action(G('查看依据','D01'),G('准备交办','F06'),G('打开关联会议','F04'))}${Note('如不存在关联会议或交办，明确显示“无关联对象”，而不是创建虚构记录。')}`)+
 C('保存与返回',`${R('排序保存状态','未更改')}${R('资料完整性','待核查')}${Action(G('任务与承诺','N05'),G('通知中心','N06'))}${Note('从来源、会议和交办详情返回时保留日期、筛选、滚动位置与焦点，重新检查当前事项进展。')}`));
const assignment=()=>columns(
 C('当前交办任务',`${form(X('任务对象与版本'),X('业务状态','RESULT_SUBMITTED','select','待反馈|处理中|结果已提交|老板已确认完成|已取消'),X('任务类别','他人交办','select','本人承诺|他人交办'),X('唯一负责人'))}${Note('结果已提交 ≠ 老板已确认完成；消息发送、送达、回复也各自记录。')}`)+
 C('结果提交与证据',`${form(X('结果提交作者'),X('提交时间'),X('产物名称'),X('证据完整性','待核查','select','完整|缺少证据|未提交'))}${R('证据附件','尚未取得授权可读附件')}${R('来源与资料版本')}${Action(G('打开证据来源','D01'),B('确认完成','confirm-task','primary'),B('要求补充','request-evidence'))}${Note('证据缺失时不允许设计示例直接标记为完成。完成决定须由老板本人作出。','warn')}`)+
 C('延期与有效期限',`${form(X('原有效期限'),X('申请新期限','','datetime-local'),X('IANA 时区','Asia/Shanghai'),X('延期申请理由'))}${Action(G('选择时间与时区','D05'),B('批准延期','approve-delay'))}${Note('批准前保留原期限；批准、拒绝和当前有效期限须分开显示。')}`),
 C('执行记录',`${R('业务状态','等待读取')}${R('催办记录','待核查')}${R('已发送消息','保留原记录')}${R('本次处理结果','待操作')}${Action(B('取消交办','cancel-task','danger'))}${Note('取消仅停止未执行催办和后续步骤；历史发送、已提交产物仍可查询。','warn')}`)+
 C('继续任务',`${Action(G('返回当前事项','F01'),G('任务与承诺','N05'),G('必要决定与授权','D02'))}${Note('F01/N05 返回时重新读取原对象、任务版本、期限与当前进展。')}`));
const tasks=()=>columns(
 C('任务与承诺',`${T('全部任务','本人承诺','他人交办','待核查结果')}<div class="v6-formgrid cols3">${X('当前状态','待查询','select','已提交结果|老板已确认完成|已取消|处理中')}${X('负责人')}${X('有效期限','','date')}</div>${Action(B('查询任务','query-tasks','primary'),G('返回今日','F01'))}`)+
 C('任务列表与结果核查',`${litem('待读取的任务与结果','提交时间：待核查 · 证据完整性：待核查 · 当前有效期限：待核查 · 类别：待核查','F06','查看结果')}${litem('结果已提交（设计状态）','与老板已确认完成分别展示，不能提前标记终态','F06','RESULT_SUBMITTED')}${Note('筛选、分页、选中任务、滚动位置均作为跨页面返回上下文保留。')}`),
 C('当前选中任务',`${R('结果提交时间')}${R('证据完整性')}${R('有效期限')}${R('确认完成记录')}${Action(G('查看结果','F06'),G('继续讨论','N02'))}`));
const meeting=()=>columns(
 C('会议、资料与版本',`${form(X('会议对象'),X('原始会议记录'),X('资料版本'),X('参会人'))}${R('关联事项','待读取')}${Note('来源版本变更后需重新核查；此前已保存与已发送的逐项结果仍保留。','warn')}`)+
 C('会议纪要 · 四类内容',`${T('意见','建议','明确决定','交办草稿')}${textArea('当前类别内容','按原始会议记录填写，不自动将意见视为决定')}${R('作者与原文位置','待核查')}${Action(G('查看原文引用','D01'),B('保存纪要','save-minutes','primary'))}`)+
 C('逐项交办草稿',`${check('选择此条交办草稿（默认不选）')}${form(X('交办目的'),X('唯一负责人'),X('期限','','datetime-local'),X('IANA 时区','Asia/Shanghai'),X('要求产物'),X('证据要求'))}${Action(G('选择负责人','D04'),B('创建所选交办','create-selected','primary'),B('发送获准交办','send-selected'))}${Note('“创建”与“发送”分开记录；每一条草稿具有独立授权、结果与失败后的继续条件。')}`),
 C('当前纪要版本与操作结果',`${R('纪要保存状态','草稿 · 待保存')}${R('本人确认状态','尚未确认')}${R('逐项创建结果','尚未创建')}${R('逐项发送结果','尚未发送')}${R('来源版本','待核查')}${Action(B('确认当前纪要','confirm-minutes','primary'))}${Note('当前预览支持逐项选择与分步状态反馈，不代表真正发送消息。')}`)+
 C('关联',`${Action(G('会前准备','F04'),G('交办详情','F06'),G('返回当前事项','F01'))}`));
const trip=()=>columns(
 C('行程时间与时区',`${form(X('出发地点'),X('到达地点'),X('出发时间','','datetime-local'),X('到达时间','','datetime-local'),X('出发地 IANA 时区','Asia/Shanghai'),X('到达地 IANA 时区'))}${form(X('老板本地时间'),X('目的地当地时间'),X('交通资料来源时间'),X('交通缓冲（分钟）','','number'))}${Note('同一变更需要明确时区、跨日、夏令时和资料时效；目前均为未填状态。')}`)+
 C('受影响会议与事项',`${litem('关联会议记录待查询','原安排：待查询 · 拟议安排：待填写 · 冲突：待核查 · 准备期限：未知')}${Action(G('打开会议','F04'),B('检查冲突','check-conflicts'))}`)+
 C('确认具体变更',`${form(X('日历对象'),X('对象版本'),X('原安排（只读）'),X('拟议安排'))}${R('有效授权','待核查')}${Action(G('查看授权详情','D02'),B('确认具体变更','confirm-calendar','primary'),B('放弃未提交编辑','discard'))}${Note('保存失败保留原日历；完成后可查看更新后行程或返回今日。')}`),
 C('来源与风险',`${R('交通资料日期')}${R('天气资料日期')}${R('跨日提醒')}${R('仍需补充信息')}${Action(G('查看来源原文','D01'))}`)+
 C('后续入口',`${Action(G('查看更新后行程','F11'),G('返回今日','F01'))}`));
const memory=()=>columns(
 C('个人要求与版本',`${T('候选待确认','当前有效','历史版本','删除传播')}${litem('候选要求','尚未生效 · 来源：待核查 · 有效期：未确认 · 版本：草稿','','候选')}${form(X('要求具体内容','','textarea'),X('可见范围','本人专用','select','本人专用|获准共享'),X('有效期限','','date'),X('来源说明'))}${Action(B('确认当前要求','approve-memory','primary'),B('修改要求','edit-memory'),B('删除要求','delete-memory','danger'))}`)+
 C('来源、确认和采用',`${R('本人确认记录','未确认')}${R('当前有效版本','待读取')}${R('新会话采用时间','尚无记录')}${R('采用范围','尚未生效')}${Action(B('查看新会话采用记录','adoption-record'),G('聊天交办','N02'))}`),
 C('删除与传播状态',`${R('后续采用','没有删除请求')}${R('索引传播','无待处理任务')}${R('传播失败原因','不适用')}${Note('删除后应立即停止后续采用；传播中的旧索引状态和失败原因持续可见。')}`));
const voice=()=>columns(
 C('录音与上传',`${T('本次许可','录音中','上传中','转写中','文本核查')}${Note('录音需要操作系统许可和本次明确同意；这是桌面静态设计预览，不会开启实际麦克风。')}${Action(B('允许录音并开始','record-start','primary'),B('停止录音','record-stop'),B('上传音频','upload-audio'),B('使用文字','use-text'))}${R('录音实际时长','尚未录音')}${R('格式与时长上限','取决于实际服务能力')}${R('权限撤销时','立即停止采集')}`)+
 C('原始转写与修改后文本',`${split(C('原始转写（只读）',`${R('转写服务状态','尚未调用')}${Note('无真实音频时不生成文本或虚构录音波形。')}`),C('核查并编辑',`${textArea('修改后文本','核对并修改人名、金额、时间、动作后再提交')}`))}${T('人名','金额','时间','动作')}${form(X('原文版本'),X('确认文本版本'))}${Action(B('确认文本并继续','confirm-transcript','primary'),G('返回聊天交办','N02'))}`),
 C('提交与业务动作',`${R('文本提交状态','未确认')}${R('业务动作状态','尚未发起')}${R('实际服务用量','未知')}${R('录音与转写费用','未知')}${Action(B('取消本次操作','cancel-voice','danger'))}${Note('确认文本只会进入 N02 共同任务流程；任何发信、交办和写入仍需独立授权。')}`)+
 C('失败与继续',`${R('麦克风被拒绝','使用文字或上传获准音频')}${R('无声 / 转写失败','保留错误与原文本')}${Action(B('使用文字继续','use-text','primary'),B('查看实际权限管理入口','os-permissions'))}`));
const chat=()=>columns(
 C('当前会话与关联事项',`${R('关联事项','尚未关联')}${R('资料版本','待读取')}${R('任务对象','尚未发起')}${Action(G('返回当前事项','F01'),B('开始新会话','new-session'))}`)+
 C('对话与任务运行',`${Note('当前是设计演示：不会连接模型，也不会真的发送任务。')}${C('交办消息',`${textArea('本次消息','输入问题、补充信息或待执行任务')}${Action(B('添加附件','choose-file'),G('语音输入','F27'),B('提交需求','submit-chat','primary'))}`)}${C('可观察执行步骤',`${litem('准备与核查','待补充条件：待核查 · 已执行项：无已验证记录 · 未执行项：待查询')}${R('执行结果','尚未运行')}${R('最近产物','暂无真实产物')}${Action(G('核查来源','D01'),G('查看交办','F06'),G('查询原执行结果','D03'))}`)}`),
 C('持续进展与异常',`${R('运行状态','未执行')}${R('是否存在必要决定','尚未检查')}${R('历史阅读位置','返回时恢复')}${Action(B('查看最新进展','latest-progress'),G('必要决定','D02'))}${Note('未知执行结果时禁止重复发送同一动作；入口转至 D03 查询原记录。','warn')}`));
const topics=()=>columns(
 C('经营关注范围',`${form(X('法人范围'),X('区域'),X('期间','','date'),X('关注条件'))}${Action(B('查询专题范围','query-topics','primary'))}${Note('从 F14—F23 返回后恢复法人、区域、期间、专题、位置。资料时间和缺口逐项显示。')}`)+
 C('十个经营专题',`<div class="v6-grid split">${TOPIC.map((t,i)=>`<div class="v6-item selectable" data-go="F${String(i+14)}"><div class="v6-icon">${String(i+1).padStart(2,'0')}</div><div class="v6-grow"><b>${t}</b><p>资料截至：待核查 · 覆盖缺口：待核查 · 关联事项：待查询</p></div>→</div>`).join('')}</div>${Note('禽类与反刍进入 F19，可进一步切换肉禽、蛋禽、奶畜、肉用牛羊；更换对象时清除不适用的条件。')}`),
 C('经营提醒与来源',`${R('最新资料时间')}${R('当前覆盖缺口')}${Action(G('经营查询与追问','F03'),G('来源原文','D01'),G('查看禽类与反刍','F19'))}`));
const builders={F01:home,F05:meeting,F06:assignment,N05:tasks,F11:trip,F13:memory,F27:voice,N02:chat,N03:topics};
window.V6PageBuilders={...window.V6PageBuilders,...builders};
window.V6Helpers={C,B,G,X,R,T,Note,Empty,Action,columns,split,check,litem,form,textArea};
})();
(()=>{
const {C,B,G,X,R,T,Note,Empty,Action,columns,split,check,litem,form,textArea}=window.V6Helpers;
const dataset=()=>columns(
 C('数据集生成条件',`${form(X('随机种子 seed'),X('数据规模','请选择规模','select','小规模|中规模|大规模'),X('业务期间','','date'),X('生成器版本'))}${form(X('关系配置版本'),X('数据集版本'))}${Action(B('生成模拟数据','generate-data','primary'),B('载入获准数据集','load-data'))}${Note('SIMULATED · 仅针对获准的模拟资料；未执行生成时不展示记录数量和结果。')}`)+
 C('校验与生成记录',`${R('实体关系','未校验')}${R('数值平衡','未校验')}${R('来源属性','未校验')}${R('生成记录','尚无执行记录')}${Action(B('运行关系检查','check-data'),B('查看生成明细','data-details'))}`)+
 C('重置影响确认',`${R('受影响会话','待查询')}${R('个人记忆','待查询')}${R('任务与计划','待查询')}${R('发件箱与在途运行','待查询')}${Action(B('查看重置影响','reset-impact','warn'),B('重置模拟空间','reset-dataset','danger'))}${Note('确认重置前不能擦除既有可查记录；旧 execution_namespace 只读保留。','warn')}`),
 C('当前模拟空间',`${R('execution_namespace','尚未创建')}${R('业务时钟','待设置')}${R('已载入版本','无')}${R('旧空间结果','可通过只读入口查询')}${Action(G('模拟中心','F25'),G('运行记录','A15'))}`));
const events=()=>columns(
 C('注入事件与模拟回复',`${form(X('事件类型','请选择','select','市场价格变动|反馈到达|资料更新|任务变更'),X('关联事项'),X('反馈作者'),X('资料版本'),X('业务事件时间','','datetime-local'),X('来源资料时间','','datetime-local'))}${textArea('事件或模拟回复内容','仅在获准的模拟空间写入，不能冒充老板授权或确认完成')}${Action(B('注入事件','inject-event','primary'),B('提供模拟回复','simulate-reply'))}`)+
 C('推进业务时钟',`${form(X('当前业务时钟'),X('目标业务时钟','','datetime-local'))}${R('影响范围','待核查')}${Action(B('推进时钟','advance-clock'))}${Note('时间推进改变模拟业务时钟，不等同于真实系统时间。')}`),
 C('模拟与 Agent 处理结果',`${R('事件保存结果','尚未执行')}${R('触发任务','尚未执行')}${R('系统通知','未生成')}${R('模拟执行结果','尚未执行')}${R('Agent 处理结果','尚未执行')}${Action(G('关联运行记录','A15'))}`)+
 C('权限边界',`${R('当前身份','技术维护')}${R('可用范围','模拟资料与获准维护')}${R('老板决定','必须由老板入口完成')}${Note('场景执行成功但 Agent 处理失败必须分别显示，不能合并为完成。')}`));
const model=()=>columns(
 C('模型与 Provider 配置',`${T('GPT 配置','DeepSeek 配置','当前启用版本')}${form(X('Provider','请选择','select','OpenAI|DeepSeek'),X('API 类型','请选择','select','官方 API|兼容接口|私有化部署'),X('model_id'),X('服务端凭据引用'),X('超时（秒）','','number'),X('轮数限制','','number'),X('用量计价'),X('当前编辑版本'))}${check('对话生成')}${check('工具调用')}${check('多模态理解')}${Action(B('保存草稿','save-model','primary'),B('实际连接验证','validate-model'))}${Note('服务端凭据引用不展示密钥；模型验证未通过时不能启用，不自动换到其他模型。')}`)+
 C('启用与实际采用',`${R('当前草稿','未保存')}${R('当前启用版本','待查询')}${R('本次验证结果','未验证')}${R('实际采用版本','尚未读取真实运行')}${Action(B('启用模型','enable-model'),G('查看共同任务结果','A15'))}`),
 C('真实连接记录',`${R('验证版本','未验证')}${R('验证发生时间','无')}${R('连接错误','未知')}${R('用量与费用','未发生测试')}${R('验证能力','待核验')}${Action(G('查看运行与用量','F30'))}`));
const tools=()=>columns(
 C('工具目录与版本',`${form(X('工具名称'),X('用途说明'),X('当前编辑版本'),X('连接状态','未启用','select','未启用|配置中|验证失败|已启用'))}${Note('目录中的名称、用途与版本必须关联真实工具定义；无接口时只显示“待配置”。')}`)+
 C('输入输出 Schema',`${split(C('Input Schema',`${textArea('输入 Schema JSON','待定义：type / properties / required')}`),C('Output Schema',`${textArea('输出 Schema JSON','待定义：response / status / evidence')}`))}${Action(B('校验 Schema','validate-schema'),B('保存工具草稿','save-tool','primary'))}`)+
 C('接口、安全与执行规则',`${form(X('请求地址与方法'),X('授权检查'),X('工具副作用'),X('超时设置（秒）','','number'),X('幂等规则'),X('错误定义'))}${Action(B('验证参数与连接','validate-tool'),B('启用工具','enable-tool'))}${Note('工具启用只代表接口可用，不扩大任何业务授权。涉及业务写入时仍检查本人有效授权。')}`),
 C('验证和实际调用',`${R('输入字段定位','尚未校验')}${R('连接错误','无实际连接记录')}${R('验证版本','尚未验证')}${R('请求 / 响应','尚未调用')}${R('老板授权核查','未执行')}${Action(B('查看实际调用','real-call'),G('正式执行结果','D03'))}`));
const metrics=()=>columns(
 C('指标定义与生效',`${form(X('指标名称'),X('指标公式'),X('维度'),X('单位'),X('数值精度','','number'),X('适用范围'),X('生效时间','','datetime-local'),X('刷新条件'))}${Action(B('保存指标草稿','save-metric','primary'),B('校验公式','validate-formula'))}`)+
 C('经营提醒与规则',`${form(X('提醒阈值'),X('持续时间'),X('恢复条件'),X('冷却时间'),X('免打扰条件'),X('老板参与条件'))}${Action(B('检查提醒规则','check-rule'),B('启用经验证规则','enable-rule'))}${Note('指标单位、期间和法人不可比时必须保留冲突，不输出伪趋势或“通过”。')}`),
 C('独立复算结果',`${R('当前输入范围','待选择')}${R('公式版本','待查询')}${R('计算结果','未知')}${R('与来源差异','未知')}${Action(B('独立复算','recompute','primary'),G('核查原文','D01'))}`)+
 C('规则运行记录',`${R('最近触发','尚未查询')}${R('恢复记录','尚未查询')}${R('重复抑制','尚未查询')}${R('升级通知','尚未查询')}${Action(G('打开通知记录','N06'))}`));
const scheduler=()=>columns(
 C('调度对象与责任',`${form(X('计划名称'),X('唯一执行责任组件'),X('当前计划版本'),X('下次触发时间'))}${R('所属范围','仅获准的任务范围')}${Note('未核验唯一责任组件和有效授权时，下次执行时间为“待确认”，不能生成计划成功状态。')}`)+
 C('条件、时区和去重',`${form(X('时间 / 事件模式','请选择','select','定时计划|业务事件'),X('IANA 时区','Asia/Shanghai'),X('调度表达式'),X('获准任务范围'),X('重复抑制窗口'),X('重启恢复行为'))}${Action(B('保存计划草稿','save-plan','primary'),B('验证条件','validate-plan'))}`),
 C('执行控制',`${R('计划状态','未启用')}${R('应用退出后的状态','本地调度停止')}${R('休眠恢复检查','尚未检查')}${R('当前在途运行','待读取')}${Action(B('启用计划','enable-plan'),B('暂停','pause-plan','warn'),B('取消','cancel-plan','danger'),B('获准手动执行','run-plan'))}${Note('暂停/取消仅影响尚未触发的动作，已执行结果仍可查询；老板授权范围在本人计划中修改。')}`)+
 C('关联记录',`${Action(G('本人计划','N09'),G('运行详情','F24'),G('运行记录','A15'))}`));
const local=()=>columns(
 C('本地环境与版本',`${form(X('目标 OS / 架构'),X('应用版本'),X('上游组件版本'),X('实际检查时间'))}${R('服务状态','待核查')}${R('已获准维护动作','待确认')}${Note('目标操作系统、权限入口及安装行为尚待 T02 设备与宿主环境证据绑定。','warn')}`)+
 C('窗口、后台与调度',`${form(X('前台窗口状态'),X('后台运行状态','关闭（默认）'),X('自启动','关闭（默认）'),X('自动更新','关闭（默认）'))}${R('当前录音状态','未采集')}${R('调度进程','待核查')}${Action(B('完整退出影响','exit-impact','danger'),B('重新启动说明','restart-guide'))}`)+
 C('恢复核查',`${R('任务重读','待核查')}${R('有效授权重读','待核查')}${R('计划版本重读','待核查')}${R('执行结果未知','前往原运行核查')}${Action(G('查询执行结果','D03'),G('查看异常任务','F29'))}`),
 C('安装与数据备份',`${litem('安装与启动','在已验证宿主环境安装，不预设成功状态')}${litem('完整退出','停止本地调度、录音及未执行步骤')}${litem('备份与恢复','保留核验记录和授权边界')}${Action(B('查看安装记录','install-record'),B('查看备份记录','backup-record'))}`));
const owner=()=>columns(
 C('负责人查询',`${form(X('姓名 / 组织 / 职责关键词'),X('组织范围'))}${Action(B('搜索已授权通讯录','query-owner','primary'))}${Empty('暂无来自有效组织目录的候选负责人，不能根据同名推断身份。')}`)+
 C('选中唯一负责人',`${R('完整姓名','未选择')}${R('组织','未选择')}${R('当前职责','未选择')}${R('职责有效期','未核验')}${R('稳定 ID','未选择')}${Action(B('确认负责人','confirm-owner','primary'),B('取消选择','close-picker'))}`),
 C('范围与异常',`${R('同名候选','必须明确选择唯一稳定 ID')}${R('资料过期','不可确认')}${R('查询失败','保留原选择')}${Note('返回原交办表单后保留已填写的目标、期限与证据要求。')}`));
const time=()=>columns(
 C('时间选择与对象',`${T('延期申请','日程变更','暂缓提醒')}${form(X('本次日期','','date'),X('具体时间','','time'),X('IANA 时区','请选择','select','Asia/Shanghai|Asia/Singapore|Europe/London|America/Los_Angeles'),X('原对象版本'))}${Action(B('检查当地时间','check-time','primary'),B('确认并返回','confirm-time'))}`)+
 C('跨时区核查',`${R('老板时间','待计算')}${R('当地时间','待计算')}${R('UTC offset','待计算')}${R('夏令时','待核查')}${R('是否跨日','待核查')}${Note('时间歧义或无效当地时间必须提示字段原因；不能默认为老板当前时区。')}`),
 C('原对象与取消',`${R('原选择','保留')}${R('变更对象','尚未指定')}${Action(B('取消本次选择','close-picker'),G('返回今日','F01'))}`));
const unsaved=()=>columns(
 C('未保存的编辑内容',`${form(X('未保存对象','请选择','select','纪要|消息|行程|私人安排|配置'),X('本次编辑范围'),X('准备离开的目的'),X('当前版本'))}${Note('离开或关闭窗口前保留原编辑上下文；取消关闭应恢复原控件焦点。','warn')}${Action(B('继续编辑','continue-edit','primary'),B('保存草稿并离开','save-before-leave'),B('放弃本次编辑','discard-edit','danger'))}`)+
 C('完整退出的独立影响',`${R('本地调度','将停止')}${R('录音采集','将停止')}${R('未执行步骤','将停止')}${R('已保存记录','保留')}${R('未知结果','需重新核查')}${Action(B('确认完整退出（仅预览）','full-exit','danger'))}`),
 C('设计反馈',`${R('当前处理结果','尚未选择')}${Note('保存失败须停留在原编辑内容，不得清空表单。完整退出在真实宿主中仍需 T02 验证。')}`));
const settings=()=>columns(
 C('桌面与权限',`${form(X('应用内通知'),X('系统通知许可','待实际读取'),X('麦克风许可','待实际读取'),X('后台运行','关闭（默认）'),X('开机自启动','关闭（默认）'),X('自动更新','关闭（默认）'))}${Action(G('通知隐私设置','N08'),B('打开系统权限管理','os-permissions'))}${Note('系统权限管理入口依赖真实 OS / 宿主能力，当前为设计占位。')}`)+
 C('会话退出与完整退出',`${R('退出登录','清除受限界面，不等于关闭应用')}${R('完整退出应用','停止本地调度、录音及未执行动作')}${R('已确认内容','继续保留')}${Action(B('退出登录（预览）','logout-preview'),B('完整退出应用','exit-impact','danger'))}`),
 C('设置应用状态',`${R('有效版本','尚未读取')}${R('系统权限检查时间','无')}${Action(G('本地运行与交接','F32'),G('返回今日','F01'))}`));
const notifications=()=>columns(
 C('应用内与系统通知',`${form(X('应用内通知要求','待确认','select','全部|重要事项|免打扰'),X('系统通知许可','待读取','select','许可|拒绝|撤销'),X('提醒时段'),X('可见范围','最小化预览'))}${Action(B('保存本人通知要求','save-notification','primary'),G('应用内通知中心','N06'))}`)+
 C('隐私预览',`${R('系统预览应用名','Boss Agent')}${R('事项类别','待确认事项')}${R('返回入口','打开后检查当前授权')}${R('私人标题与正文','不展示')}${R('附件或摘要','不展示')}${Note('系统许可被拒绝时仍能从应用内通知中心读取经授权的内容。')}`),
 C('权限与返回',`${R('首次许可原因','仅在实际需要时说明')}${R('拒绝 / 撤销','提供平台支持的管理入口')}${R('会话过期','进入 D08 核验')}${R('历史通知','进入 D09 只读')}${Action(B('查看系统通知权限','os-permissions'),G('登录过期状态','D08'),G('历史通知详情','D09'))}`));
const builders={A03:dataset,A04:events,A08:model,A09:tools,A10:metrics,A13:scheduler,F32:local,D04:owner,D05:time,D06:unsaved,F26:settings,N08:notifications};
window.V6PageBuilders={...window.V6PageBuilders,...builders};
})();
