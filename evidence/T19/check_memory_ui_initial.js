async (page) => {
  const [response] = await Promise.all([
    page.waitForResponse(item => item.url().endsWith("/api/boss/ui/admin/memory-status")),
    page.getByRole("button", {name: "检查技术状态", exact: true}).click(),
  ]);
  if (response.status() !== 200) throw Error("实际记忆技术 API 未成功");
  const result = await response.json();
  if (result.memory.version !== "4" || !result.future_context_eligible || result.latest_context_selection.memory_version !== "3")
    throw Error("当前确认与历史真实模型版本未分别返回");
  const current = page.getByRole("region", {name: "当前记忆确认", exact: true});
  await current.getByText("符合当前确认条件", {exact: true}).waitFor();
  const field = (scope, name) => scope.locator(".boss-kv").filter({has: page.getByText(name, {exact: true})}).locator("strong").innerText();
  if (await field(current, "当前记忆版本") !== "4" || await field(current, "有效期限") !== "未知")
    throw Error("当前版本或未知期限展示不符");
  const aside = page.getByRole("complementary", {name: "新会话与技术核查", exact: true});
  if (await field(aside, "该次记忆版本") !== "3" || await field(aside, "该次运行状态") !== "SUCCEEDED")
    throw Error("已有真实运行观察未正确显示");
  if (await field(aside, "与当前记忆版本一致") !== "版本已经变化") throw Error("历史选择被当作当前版本");
  if ((await page.locator("main").innerText()).includes("简报优先展示现金")) throw Error("页面包含记忆正文");
  for (const name of ["确认记忆", "修改记忆", "删除记忆", "保存记忆"])
    if (await page.getByRole("button", {name, exact: true}).count()) throw Error("维护页面具有本人内容修改控件");
  const initialDom = await page.locator("main").ariaSnapshot();
  const runId = result.latest_context_selection.run_id;
  await page.getByRole("button", {name: "查看关联运行记录", exact: true}).click();
  await page.getByRole("heading", {name: "运行记录", exact: true}).waitFor();
  if (new URL(page.url()).searchParams.get("run_id") !== runId || await page.getByLabel("run_id", {exact: true}).inputValue() !== runId)
    throw Error("关联运行编号没有进入实际查询入口");
  await page.getByRole("button", {name: "查询记录", exact: true}).click();
  await page.getByText("已读取 1 / 匹配 1", {exact: true}).waitFor();
  if (!(await page.locator("tbody").innerText()).includes(runId)) throw Error("未读取对应真实运行记录");
  await page.goto(new URL("/", page.url()).href);
  await page.getByRole("button", {name: "查看获准记录", exact: true}).click();
  await page.getByRole("heading", {name: "获准动作记录", exact: true}).waitFor();
  const audit = JSON.parse(await page.locator("pre").innerText());
  if (audit.projection !== "audit" || audit.private_values_included !== false || !audit.operations.length)
    throw Error("获准动作记录未返回真实脱敏投影");
  return {status: "PASS", check_id: "A12-CURRENT-AND-HISTORICAL-OBSERVATIONS", run_id: runId,
    current_version: result.memory.version, historical_version: result.latest_context_selection.memory_version,
    audit_operation_count: audit.operations.length, dom: initialDom,
    audit_dom: await page.locator("body").ariaSnapshot()};
}
