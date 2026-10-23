async(page)=>{
  await page.getByRole("textbox",{name:"原料",exact:true}).waitFor();
  await page.getByRole("textbox",{name:"原料",exact:true}).fill("核查当前原料范围");
  await page.getByRole("button",{name:"核对资料范围",exact:true}).click();
  await page.getByRole("status").filter({hasText:"已记录当前页面的查询条件"}).waitFor();
  await page.getByRole("combobox",{name:"专题页面",exact:true}).selectOption("F15");
  await page.getByRole("textbox",{name:"区域",exact:true}).waitFor();
  if(await page.getByRole("status").filter({hasText:"已记录当前页面的查询条件"}).count())throw Error("切换专题后保留上一页面的已应用范围提示");
  await page.getByRole("textbox",{name:"区域",exact:true}).fill("核查当前区域范围");
  await page.getByRole("button",{name:"核对资料范围",exact:true}).click();
  await page.getByRole("combobox",{name:"专题页面",exact:true}).selectOption("F17");
  await page.getByRole("textbox",{name:"区域",exact:true}).waitFor();
  if(await page.getByRole("textbox",{name:"区域",exact:true}).inputValue())throw Error("另一专题保留上一专题的输入范围");
  const selector=page.getByRole("combobox",{name:"专题页面",exact:true});
  const pages=await selector.locator("option").evaluateAll(items=>items.map(item=>item.value));
  const observed=[];
  for(const id of pages){
    const [response]=await Promise.all([page.waitForResponse(response=>response.url().endsWith("/api/boss/ui/sector?page="+encodeURIComponent(id))),selector.selectOption(id)]);
    const view=await response.json();
    if(response.status()!==200||view.page_id!==id||view.source_type!=="SIMULATED")throw Error("当前专题读取范围不符");
    const inputs=page.locator(".boss-sector-filter-row").getByRole("textbox");await inputs.first().waitFor();
    if(await inputs.count()!==view.design_filters.length)throw Error("当前专题筛选字段不完整");
    for(const input of await inputs.all())if(await input.inputValue())throw Error("跨专题保留旧筛选字段："+id);
    if(await page.getByRole("status").filter({hasText:"已记录当前页面的查询条件"}).count())throw Error("跨专题保留旧已应用范围："+id);
    if(!view.metrics.every(item=>item.value===null&&item.unit===null)||view.sector_kpi_calculations_supported!==false)throw Error("当前没有来源的指标被填入数值");
    await inputs.first().fill("核查当前专题范围");await page.getByRole("button",{name:"核对资料范围",exact:true}).click();
    observed.push({page_id:id,filter_count:view.design_filters.length,unknown_metrics_preserved:true});
  }
  await selector.selectOption("F17");await page.getByRole("textbox",{name:"区域",exact:true}).waitFor();
  return {status:"PASS",check_id:"SECTOR-PAGE-FILTER-BOUNDARY",source_type:"SIMULATED",pages:["F14","F15","F17"],
    previous_applied_notice_cleared:true,previous_scope_input_cleared:true,all_page_observations:observed,model_requests:0};
}
