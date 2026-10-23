async (page) => {
  const observations=[];
  const body=page.getByRole("textbox",{name:"方法正文：触发、输入、步骤、工具引用、授权、输出与结束条件",exact:true});
  const version=page.getByRole("textbox",{name:"新方法版本",exact:true});
  const note=page.getByRole("textbox",{name:"变更说明",exact:true});
  async function current(){
    return await page.evaluate(async()=>{
      const token=document.querySelector('meta[name="maintainer-token"]').content;
      const response=await fetch("/api/boss/ui/admin/sop-method?sop_id=SOP03",{headers:{Authorization:"Bearer "+token},cache:"no-store"});
      if(!response.ok)throw Error("实际方法读取失败");
      return await response.json();
    });
  }
  async function confirm(action){
    const dialog=page.getByRole("dialog");
    await dialog.getByRole("checkbox",{name:"已核查当前方法、版本和操作范围",exact:true}).check();
    const [response]=await Promise.all([
      page.waitForResponse(response=>response.url().endsWith("/component/sop-command")&&response.request().postDataJSON().action===action),
      dialog.getByRole("button",{name:"确认执行技术操作",exact:true}).click(),
    ]);
    const result=await response.json();
    if(response.status()!==200)throw Error("实际方法操作没有成功："+action+" "+JSON.stringify(result));
    await page.getByRole("dialog").waitFor({state:"hidden"});
    await page.getByRole("button",{name:"读取当前方法",exact:true}).waitFor({state:"visible"});
    await page.waitForFunction(()=>!document.querySelector('button[class*="boss-btn"][disabled]')||!Array.from(document.querySelectorAll('[role="status"]')).some(item=>item.textContent.includes("正在读取当前配置")));
    observations.push({action,status:response.status(),result});
    return result;
  }
  if(await body.inputValue()!==""||await body.isEnabled())throw Error("未读取页面提前填入方法正文");
  await page.getByRole("button",{name:"读取当前方法",exact:true}).click();
  await body.waitFor({state:"visible"});
  await page.waitForFunction(()=>document.getElementById("sop-method-body").value.length>0);
  if(await page.getByRole("table",{name:"已保存方法步骤表",exact:true}).getByRole("row").count()!==5)throw Error("当前原生方法步骤表不完整");
  const initial=await current();
  const original=await body.inputValue();
  const revised=original+"\n\n工具引用变化后重新核查当前结果。";
  await version.fill("0.1.1");await note.fill("核查当前经营方法的正文版本保存与读取");await body.fill(revised);
  await page.getByRole("button",{name:"保存方法草稿",exact:true}).click();
  await page.getByRole("dialog").getByRole("button",{name:"取消未提交操作",exact:true}).click();
  if((await current()).draft!==null)throw Error("取消未提交操作仍保存了草稿");
  await page.getByRole("button",{name:"保存方法草稿",exact:true}).click();await confirm("save");
  let saved=await current();
  if(saved.draft.draft_version!=="1"||saved.draft.state!=="DRAFT"||saved.active.content_sha256!==initial.active.content_sha256)throw Error("保存草稿改变了原生当前方法");
  await page.getByRole("button",{name:"校验当前草稿",exact:true}).click();await confirm("validate");
  await page.getByRole("button",{name:"启用当前草稿",exact:true}).click();await confirm("activate");
  let active=await current();
  if(active.active.version!=="0.1.1"||active.active.body!==revised||active.draft.state!=="ACTIVE")throw Error("原生方法没有采用保存的正文与版本");
  const history=active.history.find(item=>item.method_version==="0.1.0");
  await page.getByRole("combobox",{name:"选择历史版本",exact:true}).selectOption(history.history_id);
  await page.getByRole("button",{name:"查看历史正文",exact:true}).click();
  await page.getByRole("article",{name:"历史方法正文",exact:true}).waitFor();
  if(await page.getByRole("article",{name:"历史方法正文",exact:true}).locator("pre").textContent()!==original)throw Error("历史方法正文与原生版本不符");
  await version.fill("0.1.2");await note.fill("恢复历史正文为新的方法草稿");
  await page.getByRole("button",{name:"恢复历史为新草稿",exact:true}).click();await confirm("restore");
  let restored=await current();
  if(restored.active.version!=="0.1.1"||restored.draft.method_version!=="0.1.2"||restored.draft.body!==original||restored.draft.restored_from!==history.history_id)throw Error("历史恢复未保持当前生效方法");
  await body.fill(original+"\n尚未保存的本次编辑。");
  await page.getByRole("combobox",{name:"选择方法",exact:true}).selectOption("SOP01");
  await page.getByRole("dialog").getByRole("button",{name:"继续编辑",exact:true}).click();
  if(!(await body.inputValue()).includes("尚未保存的本次编辑"))throw Error("取消切换后没有保留未保存编辑");
  await page.getByRole("combobox",{name:"选择方法",exact:true}).selectOption("SOP01");
  await page.getByRole("dialog").getByRole("button",{name:"确认取消修改",exact:true}).click();
  if(await body.inputValue()!=="")throw Error("明确取消编辑后旧方法正文仍然显示");
  await page.getByRole("combobox",{name:"选择方法",exact:true}).selectOption("SOP03");
  await page.getByRole("button",{name:"读取当前方法",exact:true}).click();
  await page.waitForFunction(()=>document.getElementById("sop-method-body").value.length>0);
  if(await body.inputValue()!==original)throw Error("未保存内容进入了持久化草稿");
  await page.getByRole("button",{name:"停用当前方法",exact:true}).click();await confirm("disable");
  if((await current()).active.enabled!==false)throw Error("停用没有保存到当前原生配置");
  await page.getByRole("button",{name:"校验当前草稿",exact:true}).click();await confirm("validate");
  await page.getByRole("button",{name:"启用当前草稿",exact:true}).click();await confirm("activate");
  if((await current()).active.version!=="0.1.2"||(await current()).active.enabled!==true)throw Error("恢复后的新版本没有启用");
  const broken=original.replace("[read_evidence](tool:read_evidence)","[read_evidence](tool:unknown_operation)");
  await version.fill("0.1.3");await note.fill("核查工具引用无效时停止启用");await body.fill(broken);
  await page.getByRole("button",{name:"保存方法草稿",exact:true}).click();await confirm("save");
  await page.getByRole("button",{name:"校验当前草稿",exact:true}).click();await confirm("validate");
  let invalid=await current();
  if(invalid.draft.validation_status!=="INVALID"||invalid.active.version!=="0.1.2"||await page.getByRole("button",{name:"启用当前草稿",exact:true}).isEnabled())throw Error("无效工具引用仍然允许启用");
  await page.getByRole("alert").filter({hasText:"TOOL_REFERENCES_CHANGED"}).waitFor();
  await body.fill(original);await note.fill("使用当前获准工具引用保存新草稿版本");
  await page.getByRole("button",{name:"保存方法草稿",exact:true}).click();await confirm("save");
  await page.getByRole("button",{name:"校验当前草稿",exact:true}).click();await confirm("validate");
  const final=await current();
  if(final.draft.draft_version!=="4"||final.draft.validation_status!=="VALIDATED_STATIC_ONLY"||final.active.version!=="0.1.2")throw Error("当前版本与已保存草稿结果不符");
  return {status:"PASS",check_id:"A06-DRAFT-HISTORY-NATIVE-LIFECYCLE",source_type:"RUNTIME_RECORD",external_api_mode:"SIMULATED",
    command_observations:observations.map(item=>({action:item.action,status:item.status,state:item.result.state??null,draft_version:item.result.draft_version??null})),
    initial_native_version:initial.active.version,final_native_version:final.active.version,final_draft_version:final.draft.draft_version,
    original_content_sha256:initial.active.content_sha256,final_native_sha256:final.active.content_sha256,
    final_draft_sha256:final.draft.content_sha256,history_count:final.history.length,
    unsubmitted_cancel_verified:true,unsaved_discard_verified:true,invalid_reference_rejected:true,
    external_request_count:0,real_model_quality_verified:false,public_integration_verified:false};
}
