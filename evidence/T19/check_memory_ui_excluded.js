async (page) => {
  const [response] = await Promise.all([
    page.waitForResponse(item => item.url().endsWith("/api/boss/ui/admin/memory-status")),
    page.getByRole("button", {name: "检查技术状态", exact: true}).click(),
  ]);
  if (response.status() !== 200) throw Error("新会话记录重读未成功");
  const result = await response.json();
  const selection = result.latest_context_selection;
  if (result.memory.version !== "4" || result.future_context_eligible || selection.memory_version !== "4" ||
    selection.eligible || selection.run_status !== "SUCCEEDED" || !selection.model_completion_observed || !selection.matches_current_memory_version)
    throw Error("真实新Runtime的停止采用记录不符");
  const aside = page.getByRole("complementary", {name: "新会话与技术核查", exact: true});
  await aside.getByText("该次停止采用", {exact: true}).waitFor();
  await aside.getByText("版本一致", {exact: true}).waitFor();
  await page.getByRole("button", {name: "定位保存或索引失败", exact: true}).click();
  const diagnostic = page.getByRole("region", {name: "保存或索引失败定位", exact: true});
  await diagnostic.getByText("读取成功", {exact: true}).waitFor();
  if (!(await diagnostic.innerText()).includes("未知")) throw Error("保存故障缺少资料时未保持未知");
  if ((await page.locator("main").innerText()).includes("简报优先展示现金")) throw Error("技术页面包含记忆正文");
  return {status: "PASS", check_id: "A12-ACTUAL-NEW-RUNTIME-EXCLUSION", run_id: selection.run_id,
    memory_version: selection.memory_version, context_selection_count: result.context_selection_count,
    dom: await page.locator("main").ariaSnapshot()};
}
