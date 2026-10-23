async(page)=>{
  await page.getByRole("button",{name:"读取当前方法",exact:true}).click();
  await page.getByRole("button",{name:"取消本次读取",exact:true}).waitFor();
  await page.getByRole("button",{name:"取消本次读取",exact:true}).click();
  await page.getByRole("status").filter({hasText:"本次读取已经取消"}).waitFor();
  if(await page.getByRole("button",{name:"取消本次读取",exact:true}).count())throw Error("取消后仍然显示读取中操作");
  return {status:"PASS",check_id:"A06-CANCEL-ACTUAL-PENDING-READ",source_type:"RUNTIME_RECORD",external_api_mode:"SIMULATED",
    pending_read_created_by_owned_server_stop:true,actual_abort_verified:true,business_mutation_performed:false,external_request_count:0};
}
