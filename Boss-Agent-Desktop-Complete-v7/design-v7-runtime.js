/* V7 desktop design preview: long mode, preserve scroll/focus, local demo-only interactions. */
(()=>{
 const page=window.V6_PAGE||{}; const id=page.id||'unknown';
 const key=`boss-v7-scroll:${id}`;
 const q=new URLSearchParams(location.search);
 const full=q.get('long')==='1'||q.get('export')==='1';
 if(full)document.documentElement.classList.add('v7-export');
 if(q.get('export')==='1')document.documentElement.classList.add('v7-capture');
 const bar=document.querySelector('.v6-previewbar');
 if(bar){
  const button=document.createElement('button');button.type='button';button.textContent='完整长页面';button.title='展开全部内容，适合审阅长页面';button.setAttribute('data-v7-toggle','1');
  bar.insertBefore(button,bar.querySelector('.v6-spacer'));
 }
 const savedScroll=()=>{try{sessionStorage.setItem(key,JSON.stringify({inner:document.querySelector('.stage-body')?.scrollTop||0,y:window.scrollY,focus:document.activeElement?.id||''}))}catch(e){}};
 window.addEventListener('pagehide',savedScroll);
 const restore=()=>{try{const v=sessionStorage.getItem(key);if(!v)return;const obj=JSON.parse(v);if(full)window.scrollTo({top:obj.y||0,behavior:'instant'});else {const sc=document.querySelector('.stage-body');if(sc)sc.scrollTop=obj.inner||0}if(obj.focus){const focus=document.getElementById(obj.focus);if(focus)focus.focus({preventScroll:true})}}catch(e){}};
 if(q.get('restore')==='1')setTimeout(restore,120);
 document.addEventListener('click',e=>{
  const toggle=e.target.closest('[data-v7-toggle]');if(toggle){const enable=!document.documentElement.classList.contains('v7-export');document.documentElement.classList.toggle('v7-export',enable);toggle.textContent=enable?'固定窗口预览':'完整长页面';window.scrollTo(0,0);return}
 },true);
 document.addEventListener('click',e=>{
  const el=e.target.closest('[data-act]');if(!el)return;
  const a=el.getAttribute('data-act');
  if(a==='fill-conditions'){
   e.stopImmediatePropagation();e.preventDefault();const box=document.getElementById('v7-chat-text');if(box){box.scrollIntoView({behavior:'smooth',block:'center'});box.focus();box.placeholder='例：确认华南全部法人、上半年期间和客户反馈来源…';}
  }
  if(a==='preview-session'){
   e.stopImmediatePropagation();e.preventDefault();document.querySelectorAll('.v7-chat-history').forEach(n=>n.classList.remove('chosen'));el.classList.add('chosen');
   const title=document.querySelector('.v7-chatmainbar b');if(title)title.textContent='连续对话 · '+el.querySelector('b')?.textContent;
   const hint=document.querySelector('.v7-thread .v7-day-divider');if(hint)hint.textContent='示例会话结构 · 所有真实消息仍需读取获准来源';
  }
 },true);
 // Keyboard-accessible session cards
 document.addEventListener('keydown',e=>{const el=e.target.closest('.v7-chat-history');if(el&&(e.key==='Enter'||e.key===' ')){e.preventDefault();el.click()}});
})();
