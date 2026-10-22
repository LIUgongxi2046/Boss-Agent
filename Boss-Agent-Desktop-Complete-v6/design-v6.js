/* Boss Agent v6: offline design prototype, no network/real action. */
(()=>{'use strict';
const here=window.V6_PAGE||{}, id=here.id||'', meta=here.meta||{}, links=here.links||{};
if(!id)return;
const $=(s,root=document)=>root.querySelector(s), $$=(s,root=document)=>[...root.querySelectorAll(s)];
const esc=(v)=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const nav=(page,params={})=>{let file=links[page]; if(!file)return;try{sessionStorage.setItem('v6:return',id)}catch(e){};let q=new URLSearchParams({from:id,...params});window.location.href='./'+encodeURIComponent(file)+'.html?'+q.toString()};
const previewToast=(message)=>{let node=$('.v6-toast');if(node)node.remove();node=document.createElement('div');node.className='v6-toast';node.setAttribute('role','status');node.textContent='设计预览 · '+message;document.body.appendChild(node);window.setTimeout(()=>node.remove(),3600)};
const modal=(title,html,actions='')=>{let prev=document.activeElement;let overlay=document.createElement('div');overlay.className='v6-modal-overlay';overlay.innerHTML=`<div class="v6-modal-dialog" role="dialog" aria-modal="true" aria-labelledby="v6-dialog-title" tabindex="-1"><h2 id="v6-dialog-title">${esc(title)}</h2>${html}<div class="v6-actions" style="margin-top:18px">${actions}<button class="v6-btn primary" type="button" data-modal-close="true">返回设计稿</button></div></div>`;document.body.append(overlay);let dlg=$('.v6-modal-dialog',overlay);dlg.focus();const close=()=>{overlay.remove();if(prev && prev.focus)prev.focus()};overlay.addEventListener('click',e=>{if(e.target===overlay||e.target.closest('[data-modal-close]'))close()});overlay.addEventListener('keydown',e=>{if(e.key==='Escape')close();if(e.key==='Tab'){const foc=$$('button,a,input,textarea,select,[tabindex]:not([tabindex="-1"])',overlay).filter(x=>!x.disabled);if(foc.length){const i=foc.indexOf(document.activeElement);if(e.shiftKey&&i===0){e.preventDefault();foc.at(-1).focus()}else if(!e.shiftKey&&i===foc.length-1){e.preventDefault();foc[0].focus()}}}});
return overlay};
const H=(a,b)=>`<div class="v6-kv"><span class="key">${esc(a)}</span><span class="val">${esc(b)}</span></div>`;
const stateNote=(n)=>{let s=(here.states||[]).find(x=>x.code===n);return s?.description||'按当前业务对象呈现，并保留原始条件与操作结果。'};
const stateClass=(label)=>/失败|错误|拒绝|冲突|异常|不可/.test(label)?'error':/过期|部分|条件不足|缺少|待/.test(label)?'warning':/已完成|已保存|已通过|成功/.test(label)?'success':'';
let currentState='MAIN';
function selectDesignState(code){currentState=code;const s=(here.states||[]).find(x=>x.code===code);const label=s?.title||meta.initial_state||'主页面';
 const alert=$('.v6-state-alert');if(alert){alert.className='v6-state-alert '+stateClass(label);alert.innerHTML=`<strong>${esc(code==='MAIN'?'主页面':'状态 '+code+' · '+label)}</strong><span class="v6-grow">${code==='MAIN'?'当前主视图；所有数据及运行结果以正式连接为准。':esc(stateNote(code))}</span><span class="v6-chip">静态演示</span>`;}
 const ghost=$('.v6-state-example');if(ghost){ghost.hidden=code==='MAIN';ghost.innerHTML=`<div class="v6-state-alert ${stateClass(label)} v6-state-preview"><div><strong>${esc(label)}</strong><div style="margin-top:6px">${esc(stateNote(code))}</div><div style="margin-top:7px;color:#6a7f91">关联：${esc(id)} · ${esc(meta.title||'')} · 不模拟真实执行结果。</div></div></div>`;}
 const qp=new URL(location.href);if(code==='MAIN')qp.searchParams.delete('state');else qp.searchParams.set('state',code);history.replaceState({},'',qp.href);
 const select=$('#v6-state-select');if(select&&select.value!==code)select.value=code;
}
const navRoot=$('.sidebar');
if(navRoot){const bossNav={'今日工作':'F01','聊天交办':'N02','经营关注':'N03','会议与资料':'N04','任务与承诺':'N05','通知与设置':'N06'};const techNav={'档案与访问':'A01','模拟中心':'F25','Agent配置':'A08','运行与评测':'A15'};
 $$('.navitem',navRoot).forEach(el=>{const label=el.textContent.trim();const page=meta.technical?techNav[label]:bossNav[label];if(!page)return;const a=document.createElement('a');a.className=el.className;a.innerHTML=el.innerHTML;a.href='./'+encodeURIComponent(links[page]||page)+'.html';a.setAttribute('aria-label','前往'+label);el.replaceWith(a)});
 const foot=$('.sidefooter',navRoot);if(foot){foot.innerHTML=`<a href="../index.html" style="display:flex;align-items:center;gap:7px;min-height:44px">← 返回 72 页设计目录</a>`;}
}
const topbar=$('.topbar');
if(topbar){let logo=$('.topright .badge',topbar);if(logo)logo.textContent='设计预览 · v6.0';let second=$$('.topright .badge',topbar)[1];if(second)second.textContent='不连接真实数据';
 const nav=document.createElement('nav');nav.className='v6-quicknav';nav.setAttribute('aria-label',meta.technical?'维护快捷导航':'老板快捷导航');nav.innerHTML=meta.technical?
 `<a href="./${encodeURIComponent(links.A01)}.html">档案</a><a href="./${encodeURIComponent(links.F25)}.html">模拟中心</a><a href="./${encodeURIComponent(links.A08)}.html">模型</a><a href="./${encodeURIComponent(links.A15)}.html">运行</a>`:
 `<a href="./${encodeURIComponent(links.F01)}.html">今日</a><a href="./${encodeURIComponent(links.N02)}.html">开始对话</a><a href="./${encodeURIComponent(links.F27)}.html">语音</a><a href="./${encodeURIComponent(links.N06)}.html">通知</a>`;
 topbar.insertBefore(nav,$('.topright',topbar)||null);
 const exit=document.createElement('button');exit.type='button';exit.className='v6-btn';exit.style.minHeight='36px';exit.textContent='退出登录';exit.setAttribute('data-act','logout-preview');$('.topright',topbar)?.append(exit);
 const search=$('.search',topbar);if(search){search.setAttribute('role','button');search.setAttribute('tabindex','0');search.setAttribute('aria-label','查找设计页面');search.addEventListener('click',()=>{window.location.href='../index.html'})}}
const stage=$('.stage');const body=$('.stage-body');
if(stage){const bar=document.createElement('div');bar.className='v6-previewbar';bar.innerHTML=`<strong>${esc(id)} · ${esc(meta.title||'')}</strong><span class="v6-badge">${meta.technical?'技术维护':'老板本人'}</span><label for="v6-state-select" class="v6-hint">设计状态</label><select id="v6-state-select" aria-label="选择当前设计状态"><option value="MAIN">主页面 · ${esc(meta.initial_state||'默认')}</option>${(here.states||[]).map(s=>`<option value="${s.code}">${s.code} · ${esc(s.title)}</option>`).join('')}</select><span class="v6-spacer"></span><button type="button" data-act="review-map">需求映射</button><button type="button" data-act="sys-preview">系统状态</button><button type="button" data-act="go-back">返回</button>`;
 stage.insertBefore(bar,body||null);
}
const enhancedBuilder=window.V6PageBuilders?.[id];
if(body){if(enhancedBuilder){body.innerHTML=`<div class="v6-body"><div class="v6-state-alert"><strong>主页面</strong>当前设计场景均未接入真实数据。</div><div class="v6-state-example" hidden></div>${enhancedBuilder()}</div>`;
 }else{const alert=document.createElement('div');alert.className='v6-state-alert';alert.innerHTML=`<strong>设计预览 · ${esc(meta.initial_state||'默认状态')}</strong><span>当前未读取真实数据；保存、发送、启用等动作仅展示设计交互。</span>`;body.insertBefore(alert,body.firstChild);const ghost=document.createElement('div');ghost.className='v6-state-example';ghost.hidden=true;body.insertBefore(ghost,alert.nextSibling);}}
let stateAlert=$('.v6-state-alert');if(stateAlert){stateAlert.setAttribute('role','status')}
const getPersist=(name)=>{try{return sessionStorage.getItem('v6:'+id+':'+name)}catch(e){return null}};
$$('[data-persist]').forEach(el=>{const key=el.getAttribute('data-persist');const stored=getPersist(key);if(stored!==null)el.value=stored;el.addEventListener('input',()=>{try{sessionStorage.setItem('v6:'+id+':'+key,el.value)}catch(e){}})});
let query=new URLSearchParams(location.search);let from=query.get('from');if(from){const link=document.createElement('a');link.href='./'+encodeURIComponent(links[from]||links.F01)+'.html';link.className='v6-btn soft';link.textContent='← 返回 '+(here.names?.[from]||'来源页面');const pre=$('.v6-previewbar');if(pre)pre.insertBefore(link,pre.querySelector('.v6-spacer'));}
const draft=query.get('draft');if(draft&&id==='N02'){let e=$('[data-persist="本次消息"]');if(e){e.value=draft;previewToast('已带入确认文本；尚未发送业务动作。')}}
function showStep(message){const alert=$('.v6-state-alert');if(alert){alert.className='v6-state-alert';alert.innerHTML=`<strong>设计交互反馈</strong><span>${esc(message)}</span><span class="v6-chip">仅演示</span>`;}previewToast(message)}
function requireField(label){const el=$$('[data-persist]').find(x=>x.getAttribute('data-persist')===label);if(!el||!el.value.trim()){if(el){el.focus();el.setAttribute('aria-invalid','true')}showStep('缺少“'+label+'”，已保留原有输入。');return null}return el.value.trim()}
function action(a){switch(a){
 case'go-back':if(history.length>1)history.back();else nav(from||'F01');return;
 case'review-map':modal('需求与验收映射',H('页面',id+' · '+(meta.title||''))+H('原始来源',meta.source_file||'待核查')+H('设计状态',meta.initial_state||'主页面')+H('业务字段',meta.fields?.join('、')||'参见原始提示词')+H('必须操作',meta.actions?.join('、')||'参见原始提示词')+H('可用窗口','1440×1024 / 1280×800 / 1024×768 / 200% 缩放')+`<p>本预览为交互与状态说明，不证明 PRD、实际服务或部署验收已通过。</p>`);return;
 case'sys-preview':{
 const states=['SYS-STARTUP','SYS-CLOSE','SYS-EXIT','SYS-RESTORE','SYS-NETWORK','SYS-NOTIFICATION','SYS-MICROPHONE','SYS-FILE'];let text='<div class="v6-list">'+states.map(s=>`<button type="button" class="v6-btn" data-act="${s}">${s} · ${({'SYS-STARTUP':'启动与实例','SYS-CLOSE':'关闭窗口','SYS-EXIT':'完整退出','SYS-RESTORE':'重启恢复','SYS-NETWORK':'网络中断','SYS-NOTIFICATION':'通知权限','SYS-MICROPHONE':'麦克风权限','SYS-FILE':'文件授权'})[s]}</button>`).join('')+'</div>';modal('系统状态设计入口',text);return;}
 case'SYS-STARTUP':modal('启动与实例',`<p>启动中 / 缺少配置 / 服务不可用 / 已有实例；重复启动不会新建第二个调度执行者。</p>${H('允许操作','查看配置、查看既有实例、取消启动')}`);return;
 case'SYS-CLOSE':modal('关闭窗口',`<p>未保存对象：${esc(meta.title||'当前对象')} · 当前编辑版本：待核查。</p><p>继续编辑、保存适用草稿、放弃未提交修改；隐藏窗口仅在平台支持且已获准后台运行时可选。</p>`);return;
 case'SYS-EXIT':modal('完整退出应用',`<p>本地调度停止、录音采集停止、未执行动作停止；已保存和已确认内容保留，未知执行结果需重新查询。</p>${H('当前正在录音','待读取')}${H('在途任务','待核查')}`);return;
 case'SYS-RESTORE':modal('恢复任务与授权',`<p>逐项重读任务、授权、计划版本、旧运行结果。不自动重发未知执行结果的动作。</p><button type="button" class="v6-btn" data-go="D03">查询原执行结果 ↗</button>`);return;
 case'SYS-NETWORK':modal('网络中断与恢复',`<p>保留已确认结果，待核查未知动作；恢复网络后先查询原记录，不重复发送。</p><button type="button" class="v6-btn" data-go="F29">查看异常详情 ↗</button>`);return;
 case'SYS-NOTIFICATION':modal('系统通知权限',`<p>首次许可、拒绝、撤销；应用内通知仍可用，系统通知不预览私人正文、附件或摘要。</p><button type="button" class="v6-btn" data-go="N08">隐私设置 ↗</button>`);return;
 case'SYS-MICROPHONE':modal('麦克风权限',`<p>系统许可被拒绝或撤销时停止录音，保留“使用文字”和“上传获准音频”入口。</p><button type="button" class="v6-btn" data-go="F27">语音交办 ↗</button>`);return;
 case'SYS-FILE':modal('文件访问范围',`<p>只读取用户选定的资料；系统选择取消或读取失败不清空已有输入。系统对话框等待 T02 实机绑定。</p>`);return;
 case'start-chat':case'submit-home':{const txt=$('[data-persist="本次需求"]')?.value||'';nav('N02',txt?{draft:txt}:{});return}
 case'submit-chat':if(!requireField('本次消息'))return;showStep('已进入“演示提交”状态；真实发送需绑定模型与有效授权。');return;
 case'confirm-transcript':{const txt=requireField('修改后文本');if(!txt)return;nav('N02',{draft:txt});return}
 case'confirm-task':{const t=$('[data-persist="证据完整性"]');if(!t||t.value!=='完整'){showStep('证据尚未验证完整，暂不可确认完成；可以要求补充。');return}modal('确认完成 · 对象核查',`<p>当前交办：待核查。完成操作只针对已提交且证据完整的结果；独立记录老板本人的当前决定。</p>${H('对象版本','待核查')}${H('授权','需实时检查')}`);return}
 case'cancel-task':case'exit-impact':case'full-exit':case'reset-dataset':modal('影响范围核查',`<p>当前对象：${esc(meta.title||'未知')}；操作会停止尚未执行步骤，已执行结果、消息和证据保持可查。</p>${H('授权','尚未核验')}${H('影响范围','需在真实业务端确认')}`);return;
 case'approve-delay':if(!requireField('申请新期限'))return;showStep('延期批准设计状态：只有经本人授权后才更新有效期限，当前不写入真实记录。');return;
 case'create-selected':case'send-selected':{const check=$('.v6-check input');if(!check?.checked){showStep('请先勾选具体交办草稿；默认不全选。');return}showStep((a==='create-selected'?'逐项创建':'逐项发送')+'仅演示状态，正式操作还需核查每条的负责人、期限、证据及授权。');return}
 case'enable-model':{if(!document.body.dataset.modelValidated){showStep('当前版本尚未通过真实验证，启用不可用。');return}showStep('设计状态：已通过预览验证的版本进入启用确认；不触发实际模型切换。');return}
 case'validate-model':document.body.dataset.modelValidated='demo';showStep('已进入“验证通过”演示分支；非实际 API 验证，启用仍需正式记录。');return;
 case'enable-tool':if(!document.body.dataset.toolValidated){showStep('Schema/连接未验证，启用不可用。');return}showStep('已显示启用工具的设计反馈，真实业务写入仍需授权。');return;
 case'validate-tool':case'validate-schema':document.body.dataset.toolValidated='demo';showStep('已展示校验反馈样式，未发送真实请求。');return;
 case'approve-memory':if(!requireField('要求具体内容'))return;showStep('本人确认要求的预览反馈；正式确认需鉴权与版本记录。');return;
 case'delete-memory':modal('删除个人要求',`<p>删除后立即停止后续采用，索引传播另显示处理中、完成或失败。旧版本仅在获准审计范围内可见。</p>`);return;
 case'upload-audio':case'choose-file':showStep('这是文件选择交互说明；文件选择器需由 T02 桌面宿主实现，本预览不会读取本地文件。');return;
 case'os-permissions':showStep('系统权限入口需根据真实目标 OS / 宿主环境 T02 证据绑定。');return;
 case'record-start':showStep('模拟状态：等待系统许可 / 录音中。不会访问真实麦克风。');return;
 case'record-stop':showStep('模拟状态：停止录音；没有真实音频或时长。');return;
 case'use-text':nav('N02');return;
 case'new-session':{const a=$('[data-persist="本次消息"]');if(a){a.value='';a.focus()}showStep('新会话编辑状态，不自动读取其他会话对象。');return;}
 case'query-owner':showStep('演示目录查询：无可验证候选人；请勿选择不存在的稳定 ID。');return;
 case'confirm-owner':showStep('尚未选择唯一稳定 ID，不能回填负责人。');return;
 case'close-picker':action('go-back');return;
 case'save-before-leave':showStep('草稿保存等待真实服务；未确认成功前保留编辑上下文。');return;
 case'discard-edit':showStep('放弃编辑的设计状态，需要在正式宿主中验证恢复与返回。');return;
 case'reorder':case'reorder-up':case'reorder-down':showStep('排序更改的设计反馈：保存中 / 已保存 / 保存失败（保留未保存标记）。');return;
 case'logout-preview':modal('退出登录',`<p>退出登录清除受限界面，完成退出应用是不同操作；本预览不会注销真实会话。</p><button class="v6-btn" type="button" data-go="N01">查看登录状态 ↗</button>`);return;
 case'confirm-time':if(!requireField('IANA 时区'))return;showStep('时间与时区核查预览：原值保留，确认后回填原对象。');return;
 case'check-time':showStep('需实际时区数据库验证 DST、UTC offset、跨日与不存在的当地时间。');return;
 case'save-notification':showStep('已呈现保存状态示意，真实系统通知授权需另向宿主申请。');return;
 case'save-model':case'save-tool':case'save-plan':case'save-minutes':case'save-metric':case'save-config':case'confirm-minutes':case'save':showStep('草稿保存的设计反馈；保存与校验、启用、实际采用分别记录。');return;
 case'confirm-calendar':showStep('必须明确日历对象、变更前后版本与有效授权，不能直接写入。');return;
 case'run-plan':showStep('获准手动执行需检查当前唯一执行责任、授权、版本和在途状态。');return;
 case'refresh':case'query-tasks':case'query-topics':case'latest-progress':case'query-data':showStep('查询 / 更新设计反馈；真实来源未接入，数据截至时间仍为待核查。');return;
 default:showStep('“'+a+'”的设计交互反馈已展示；不产生真实业务写入。');return;
}}
// Event delegation handles static mock interaction only. Real connections remain explicitly unimplemented.
document.addEventListener('click',e=>{const el=e.target.closest('[data-go],[data-act],[data-tab]');if(!el)return;if(el.hasAttribute('data-go')){e.preventDefault();nav(el.getAttribute('data-go'));return;}if(el.hasAttribute('data-act')){e.preventDefault();action(el.getAttribute('data-act'));return;}if(el.hasAttribute('data-tab')){const group=el.closest('[data-tabs]');if(group)$$('.v6-tab',group).forEach(x=>{x.classList.toggle('selected',x===el);x.setAttribute('aria-selected',x===el?'true':'false')});previewToast('已切换 '+el.getAttribute('data-tab')+' 分类视图（设计演示）')}});
$('#v6-state-select')?.addEventListener('change',e=>selectDesignState(e.target.value));
const initial=query.get('state');selectDesignState(initial && (here.states||[]).some(s=>s.code===initial)?initial:'MAIN');
})();
