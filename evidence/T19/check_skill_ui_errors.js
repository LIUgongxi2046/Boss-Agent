async(page)=>{
  await page.context().setOffline(false);
  const hosts=[];page.on("request",request=>hosts.push(new URL(request.url()).hostname));
  const body=page.getByRole("textbox",{name:"方法正文：触发、输入、步骤、工具引用、授权、输出与结束条件",exact:true});
  await page.getByRole("button",{name:"读取当前方法",exact:true}).click();
  await page.waitForFunction(()=>document.getElementById("sop-method-body").value.length>0&&!Array.from(document.querySelectorAll('[role="status"]')).some(item=>item.textContent.includes("正在读取当前配置")));
  const initial=await body.inputValue();if(!initial)throw Error("没有当前已读取方法正文");
  await page.context().setOffline(true);
  await page.getByRole("button",{name:"读取当前方法",exact:true}).click();
  await page.getByRole("alert").filter({hasText:"Failed to fetch"}).waitFor();
  await page.context().setOffline(false);
  await page.getByRole("button",{name:"读取当前方法",exact:true}).click();
  await page.waitForFunction(()=>document.getElementById("sop-method-body").value.length>0&&!Array.from(document.querySelectorAll('[role="status"]')).some(item=>item.textContent.includes("正在读取当前配置")));
  await page.context().setOffline(true);
  await page.getByRole("textbox",{name:"新方法版本",exact:true}).fill("0.1.5");
  await page.getByRole("textbox",{name:"变更说明",exact:true}).fill("核查离线时保留原操作编号并明确查询结果");
  await page.getByRole("button",{name:"保存方法草稿",exact:true}).click();
  let dialog=page.getByRole("dialog");
  await dialog.getByRole("checkbox",{name:"已核查当前方法、版本和操作范围",exact:true}).check();
  const [failedRequest]=await Promise.all([page.waitForRequest(request=>request.url().endsWith("/component/sop-command")),
    dialog.getByRole("button",{name:"确认执行技术操作",exact:true}).click()]);
  const originalRequestId=failedRequest.postDataJSON().payload.client_request_id;
  await dialog.getByRole("alert").filter({hasText:"查询原操作回执"}).waitFor();
  await dialog.getByRole("button",{name:"结束本次等待并重读",exact:true}).click();
  await page.getByRole("button",{name:"查询尚待核查的原操作",exact:true}).waitFor();
  await page.context().setOffline(false);
  await page.getByRole("button",{name:"查询尚待核查的原操作",exact:true}).click();
  dialog=page.getByRole("dialog");
  await dialog.getByRole("button",{name:"查询原操作回执",exact:true}).click();
  await dialog.getByRole("alert").filter({hasText:"当前未发现原回执"}).waitFor();
  await dialog.getByRole("checkbox",{name:"已核查当前方法、版本和操作范围",exact:true}).check();
  const [retriedResponse]=await Promise.all([page.waitForResponse(response=>response.url().endsWith("/component/sop-command")),
    dialog.getByRole("button",{name:"确认执行技术操作",exact:true}).click()]);
  const retriedRequestId=retriedResponse.request().postDataJSON().payload.client_request_id;
  const result=await retriedResponse.json();
  if(retriedResponse.status()!==200||retriedRequestId!==originalRequestId||result.draft_version!=="6")throw Error("恢复网络后没有使用原编号保存一次草稿");
  await page.getByRole("dialog").waitFor({state:"hidden"});
  await page.waitForFunction(()=>document.getElementById("sop-method-body").value.length>0&&!Array.from(document.querySelectorAll('[role="status"]')).some(item=>item.textContent.includes("正在读取当前配置")));
  const denied=await page.evaluate(async()=>{
    const token=document.querySelector('meta[name="maintainer-token"]').content;
    const headers={Authorization:"Bearer "+token};
    const invalid=await fetch("/api/boss/ui/admin/sop-method?sop_id=SOP03&namespace=another-space",{headers});
    const duplicate=await fetch("/api/boss/ui/admin/sop-method?sop_id=SOP03&sop_id=SOP03",{headers});
    return {caller_scope:invalid.status,duplicate:duplicate.status};
  });
  if(denied.caller_scope!==400||denied.duplicate!==400)throw Error("当前服务没有拒绝调用方范围或重复参数");
  await page.getByRole("button",{name:"撤销本次维护会话",exact:true}).click();
  await page.waitForFunction(()=>document.getElementById("sop-method-body").value===""&&document.getElementById("sop-history-select").options.length===1);
  for(const label of ["新方法版本","方法说明","变更说明"]){
    if(await page.getByRole("textbox",{name:label,exact:true}).inputValue())throw Error("身份失效后保留方法字段："+label);
  }
  const revoked=await page.evaluate(async()=>{
    const token=document.querySelector('meta[name="maintainer-token"]').content;
    return (await fetch("/api/boss/ui/admin/sop-method?sop_id=SOP03",{headers:{Authorization:"Bearer "+token}})).status;
  });
  if(revoked!==401)throw Error("服务端未拒绝已撤销身份");
  await page.getByRole("button",{name:"读取当前方法",exact:true}).click();
  await page.getByRole("alert").filter({hasText:"技术维护身份已失效"}).waitFor();
  const external=hosts.filter(host=>host!=="127.0.0.1");if(external.length)throw Error("发现外部网络请求");
  return {status:"PASS",check_id:"A06-OFFLINE-ORIGINAL-RECEIPT-IDENTITY",source_type:"RUNTIME_RECORD",external_api_mode:"SIMULATED",
    original_request_id:originalRequestId,retried_request_id:retriedRequestId,same_request_id_verified:true,final_draft_version:result.draft_version,
    caller_scope_rejected:denied.caller_scope,duplicate_query_rejected:denied.duplicate,revoked_identity_rejected:revoked,
    editor_and_history_cleared:true,observed_external_request_count:external.length,real_model_quality_verified:false,public_integration_verified:false};
}
