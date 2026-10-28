import {useEffect,useState} from "react";
import {useTechnicalWorkspace} from "./useTechnicalWorkspace";
import {V7Panel,V7ReadState} from "./BossV7UI";
import {MaintainerRelationships} from "./MaintainerRelationships";
type Configuration={version:string;recipient_id:string;recipient_name:string;channel:"EMAIL"|"INTERNAL_IM";address:string};
type Projection={projection:"secretary";private_body_available_here:false;configuration:Configuration|null;contacts:{id:string;name:string;organization:string}[]};
export function MaintainerContactsWorkspace({onDirtyChange,onNavigate,onViewSource}:{onDirtyChange:(value:boolean)=>void;onNavigate:(page:string)=>void;onViewSource:(id:string)=>void}){
  const [secretaryDirty,setSecretaryDirty]=useState(false),[contactsDirty,setContactsDirty]=useState(false);
  useEffect(()=>{onDirtyChange(secretaryDirty||contactsDirty);},[secretaryDirty,contactsDirty,onDirtyChange]);
  return <><MaintainerSecretary onDirtyChange={setSecretaryDirty}/><MaintainerRelationships onDirtyChange={setContactsDirty} onNavigate={onNavigate} onViewSource={onViewSource}/></>;
}
export function MaintainerSecretary({onDirtyChange}:{onDirtyChange:(value:boolean)=>void}){
  const api=useTechnicalWorkspace<Projection>("secretary");
  const [form,setForm]=useState<Configuration|null>(null);
  const busy=api.loading||api.busy||!!api.pending;
  useEffect(()=>{onDirtyChange(!!form||api.busy||!!api.pending);},[form,api.busy,api.pending,onDirtyChange]);
  const current=form??api.data?.configuration;
  return <V7Panel title="秘书接收方式" description="老板确认交办后，向配置的固定秘书发送一条消息。">
    <V7ReadState loading={api.loading} error={api.error} onReload={api.reload}/>
    {api.pending&&<button className="boss-btn" disabled={api.busy} onClick={()=>void api.reconcile()}>查询保存结果</button>}
    {form?<form onSubmit={event=>{event.preventDefault();void api.execute("save",{expected_version:form.version,recipient_id:form.recipient_id,channel:form.channel,address:form.address}).then(saved=>{if(saved)setForm(null);});}}>
      <fieldset disabled={busy} className="boss-v7-form-fieldset"><label className="boss-field">固定秘书<select required value={form.recipient_id} onChange={event=>setForm({...form,recipient_id:event.target.value})}><option value="">选择联系人</option>{api.data?.contacts.map(contact=><option key={contact.id} value={contact.id}>{contact.name} · {contact.organization}</option>)}</select></label>
        <label className="boss-field">接收渠道<select value={form.channel} onChange={event=>setForm({...form,channel:event.target.value as Configuration["channel"]})}><option value="EMAIL">邮件</option><option value="INTERNAL_IM">内部 IM</option></select></label>
        <label className="boss-field">{form.channel==="EMAIL"?"邮箱地址":"内部 IM 接收账号"}<input required maxLength={320} type={form.channel==="EMAIL"?"email":"text"} value={form.address} onChange={event=>setForm({...form,address:event.target.value})}/></label>
        <div className="boss-actions"><button className="boss-btn boss-btn-primary">保存接收方式</button><button className="boss-btn" type="button" onClick={()=>setForm(null)}>取消编辑</button></div>
      </fieldset>
    </form>:<><p>{current?`${current.recipient_name} · ${current.channel==="EMAIL"?"邮件":"内部 IM"} · ${current.address}`:"尚未配置固定秘书"}</p><button className="boss-btn" disabled={busy} onClick={()=>setForm(api.data?.configuration??{version:"0",recipient_id:"",recipient_name:"",channel:"EMAIL",address:""})}>配置秘书</button></>}
    <p className="boss-helper">当前使用模拟发送与回复，发送记录保留所选接收方式。</p>
  </V7Panel>;
}
