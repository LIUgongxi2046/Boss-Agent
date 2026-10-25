async(page)=>{
  const result=await page.evaluate(async()=>{
    const token=document.querySelector('meta[name="maintainer-token"]').content;
    const headers={Authorization:"Bearer "+token,"Content-Type":"application/json"};
    const view=await(await fetch("/api/boss/ui/admin/sop-method?sop_id=SOP03",{headers})).json();
    if(view.active.version!=="0.1.2"||view.draft.draft_version!=="4"||view.draft.validation_status!=="VALIDATED_STATIC_ONLY")throw Error("当前实际方法状态与检查输入不符");
    const requestId="sop-restart-"+crypto.randomUUID();
    const response=await fetch("/component/sop-command",{method:"POST",headers,body:JSON.stringify({action:"prepare",payload:{
      client_request_id:requestId,sop_id:"SOP03",expected_draft_version:view.draft.draft_version,
      expected_content_sha256:view.draft.content_sha256,expected_active_sha256:view.active.content_sha256}})});
    const prepared=await response.json();
    if(response.status!==200||prepared.state!=="PREPARED")throw Error("实际启用操作没有保存准备状态");
    return {activation_request_id:requestId,prepared_state:prepared.state,draft_version:prepared.draft_version,active_version:view.active.version};
  });
  return {status:"PASS_PREPARED_FOR_ACTUAL_SERVER_RESTART",check_id:"A06-PREPARED-ACTIVATION",...result,external_request_count:0};
}
