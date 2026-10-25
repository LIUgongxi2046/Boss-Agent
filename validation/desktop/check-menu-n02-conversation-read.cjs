const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {once}=require('node:events');
const {randomUUID,createHash}=require('node:crypto');
const {_electron:electron}=require('playwright');
const {expect:baseExpect}=require('@playwright/test');
const access=require('./account-access.cjs');
const expect=baseExpect.configure({timeout:15000});
const root=path.resolve(__dirname,'../..'),validation=path.join(root,'validation');
const directory=path.join(validation,'.work','menu-n02-read-'+randomUUID()),accounts=access.provision(directory);
const ports={business:10741,webui:10742,gateway:20741},origin='http://127.0.0.1:'+ports.webui;
const output=path.join(root,'evidence/menu-delivery/N02/public-read.json'),records=[];
function save(status){fs.mkdirSync(path.dirname(output),{recursive:true});fs.writeFileSync(output,JSON.stringify({status,application_directory:directory,ports,external_api_mode:'SIMULATED_FIRST',scope:'N02_AUTHENTICATED_CONVERSATION_READ',visual:'NOT_RUN',user_acceptance:'NOT_RUN',records},null,2)+'\n');}
async function main(){let desktop;const sockets=[];
  try{
    desktop=await electron.launch({args:[__dirname],cwd:validation,timeout:60000,env:{...process.env,BOSS_VALIDATION_ROOT:validation,BOSS_PRODUCT_UI:'1',BOSS_EXECUTION_SCOPE:'BOSS-PRIORITY-ITERATION',BOSS_PRODUCT_FRONTEND_DIR:path.join(root,'menu-n02-n3-dist'),BOSS_APPLICATION_WORK_DIR:directory,BOSS_APPLICATION_PORTS:JSON.stringify(ports),BOSS_DESKTOP_TEST_WINDOW_HIDDEN:'1',TMPDIR:path.join(directory,'tmp')}});
    const page=await desktop.firstWindow({timeout:120000});await page.waitForURL(origin+'/');
    async function connect(role){const identity=await access.bootstrap(origin,accounts,role),socket=new WebSocket(identity.ws_url+'?token='+encodeURIComponent(identity.token)),events=[];sockets.push(socket);socket.addEventListener('message',event=>events.push(JSON.parse(event.data)));await once(socket,'open');await expect.poll(()=>events.some(event=>event.event==='ready')).toBe(true);
      return {socket,events,identity,async command(action,payload,status=200){const request_id=randomUUID();socket.send(JSON.stringify({type:'webui_request',request_id,action,payload}));await expect.poll(()=>events.some(event=>event.request_id===request_id)).toBe(true);const response=events.find(event=>event.request_id===request_id);assert.equal(response.ok,status===200,JSON.stringify(response.error));if(status!==200)assert.equal(response.error.status,status);return response.result;}};
    }
    const boss=await connect('BOSS'),maintainer=await connect('MAINTAINER');
    async function read(route,role=boss){const response=await fetch(origin+route,{headers:{Authorization:'Bearer '+role.identity.api_token}});assert.equal(response.status,200);return response.json();}
    const configuration=await read('/api/boss/ui/admin/runtime-configuration',maintainer),values={max_tool_rounds:6,max_output_tokens:700,tool_scope:['todayRead','morningListRead','morningDetailRead','morningSourceRead']};
    const draft=await maintainer.command('boss.runtime.save',{client_request_id:randomUUID(),expected_version:configuration.draft?.version??'0',values});
    const checked=await maintainer.command('boss.runtime.validate',{client_request_id:randomUUID(),expected_version:draft.version,expected_content_sha256:draft.content_sha256});
    await maintainer.command('boss.runtime.activate',{client_request_id:randomUUID(),expected_version:checked.version,expected_content_sha256:checked.content_sha256,expected_active_version:configuration.current.version});
    const attachedCount=boss.events.filter(event=>event.event==='attached').length;boss.socket.send(JSON.stringify({type:'new_chat'}));await expect.poll(()=>boss.events.filter(event=>event.event==='attached').length).toBe(attachedCount+1);
    const chat_id=boss.events.filter(event=>event.event==='attached').at(-1).chat_id,meeting=(await read('/api/boss/ui/meetings')).meeting;
    const bindingId=randomUUID();await boss.command('boss.morning.bind',{client_request_id:bindingId,chat_id,date:meeting.starts_at.slice(0,10),timezone:meeting.timezone});
    const uploaded=fs.readFileSync(path.join(root,'specs/morning-coverage.json'));
    boss.socket.send(JSON.stringify({type:'message',chat_id,turn_id:randomUUID(),content:'请整理当前日期需要本人处理的事项',media:[{name:'morning-coverage.json',data_url:'data:application/json;base64,'+uploaded.toString('base64')}],webui:true}));
    let binding,receipt;await expect.poll(async()=>{binding=(await read('/api/boss/ui/morning/binding?client_request_id='+bindingId)).result;if(!binding.last_request_id)return 'PENDING';receipt=await read('/api/boss/ui/morning/request?client_request_id='+binding.last_request_id);return receipt.request_state;},{timeout:60000}).toBe('SUCCEEDED');
    const view=await boss.command('boss.conversation.read',{chat_id});assert.equal(view.session_id,'websocket:'+chat_id);assert.equal(view.runs.length,1);assert.equal(view.runs[0].run_id,receipt.run_id);assert.equal(view.runs[0].status,'SUCCEEDED');
    const reference=view.runs[0].artifacts.find(item=>item.kind==='morning_list');assert(reference);const artifact=await boss.command('boss.conversation.artifact',{chat_id,run_id:receipt.run_id,kind:reference.kind,id:reference.id});assert.equal(artifact.data.result.list_id,reference.id);assert.equal(artifact.business_mutation_performed,false);
    const attachment=await boss.command('boss.conversation.attachments',{chat_id});assert.equal(attachment.attachments.length,1);assert.equal(attachment.attachments[0].original_name,'morning-coverage.json');assert.equal(attachment.attachments[0].mime_type,'application/json');assert.equal(attachment.attachments[0].size_bytes,uploaded.length);assert.equal(attachment.attachments[0].content_sha256,createHash('sha256').update(uploaded).digest('hex'));assert.equal(attachment.attachments[0].processing_state,'STORED');const messages=await boss.command('boss.conversation.messages',{});assert.equal(messages.scope,'OWNER_MESSAGE_HISTORY');assert.equal(messages.business_authorization_granted,false);
    const detached=await connect('BOSS');await detached.command('boss.conversation.read',{chat_id},403);await boss.command('boss.conversation.read',{chat_id,owner_id:'boss-1'},400);await boss.command('boss.conversation.read',{chat_id,session_id:'websocket:'+chat_id},400);await boss.command('boss.conversation.messages',{chat_id},400);
    for(const action of ['boss.conversation.read','boss.conversation.attachments'])await maintainer.command(action,{chat_id},403);await maintainer.command('boss.conversation.messages',{},403);
    await boss.command('boss.conversation.artifact',{chat_id,run_id:receipt.run_id,kind:'query',id:'unrelated-query'},403);
    const after=await boss.command('boss.conversation.read',{chat_id});assert.deepEqual(after,view);for(const value of [view,attachment])assert(!JSON.stringify(value).includes(directory));
    records.push({check:'actual_authenticated_attached_chat_runtime_and_artifact_read',chat_id,session_id:view.session_id,run_id:receipt.run_id,artifact:{kind:reference.kind,id:reference.id},read_only_repeat_unchanged:true});
    records.push({check:'actual_native_upload_metadata_saved_and_current_saved_session_read',attachment_id:attachment.attachments[0].attachment_id,original_name:attachment.attachments[0].original_name,mime_type:attachment.attachments[0].mime_type,size_bytes:uploaded.length,content_sha256:attachment.attachments[0].content_sha256,business_source_authority_granted:false});
    records.push({check:'unattached_connection_maintainer_injected_identity_and_unrelated_artifact_rejected',unattached_status:403,maintainer_status:403,injected_fields_status:400,unrelated_artifact_status:403});save('PASS');
  }finally{for(const socket of sockets)socket.close();if(desktop)await desktop.close();}
}
main().then(()=>console.log(JSON.stringify({status:'PASS',report:output})),failure=>{let message=failure.message;for(const account of Object.values(accounts))for(const key of ['username','password'])message=message.replaceAll(account[key],'[已隐藏]');records.push({check:'failure',message});save('FAIL');console.error(JSON.stringify({status:'FAIL',report:output}));process.exitCode=1;});
