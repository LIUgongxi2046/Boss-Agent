async(page)=>{
  await page.getByRole("textbox",{name:"专业责任人",exact:true}).waitFor();
  if(await page.getByRole("combobox",{name:"专题页面",exact:true}).inputValue()!=="F17")throw Error("已取消的旧专题请求覆盖了当前页面");
  if(await page.getByRole("textbox",{name:"品种",exact:true}).count())throw Error("旧专题筛选字段重新显示");
  if(await page.getByRole("textbox",{name:"区域",exact:true}).inputValue())throw Error("当前专题沿用了旧范围");
  return {status:"PASS",check_id:"SECTOR-RESUMED-READ-CURRENT-PAGE",source_type:"SIMULATED",current_page:"F17",old_page_reappeared:false,model_requests:0};
}
