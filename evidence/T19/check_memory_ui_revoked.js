async (page) => {
  await page.getByRole("link", {name: "返回记忆技术维护", exact: true}).click();
  const [response] = await Promise.all([
    page.waitForResponse(item => item.url().endsWith("/api/boss/ui/admin/memory-status")),
    page.getByRole("button", {name: "检查技术状态", exact: true}).click(),
  ]);
  if (response.status() !== 200) throw Error("撤销后技术状态重读未成功");
  const result = await response.json();
  if (result.memory.version !== "4" || result.memory.confirmation_state !== "CONFIRMED" ||
    result.future_context_eligible || result.next_context_memory_version !== null || !result.latest_context_selection.eligible)
    throw Error("当前确认撤销与历史选择未分别显示");
  const current = page.getByRole("region", {name: "当前记忆确认", exact: true});
  await current.getByText("停止采用", {exact: true}).waitFor();
  await current.getByText("没有可采用版本", {exact: true}).waitFor();
  await page.getByText("当前确认条件已经停止后续采用；上方记录保留当次上下文选择结果。", {exact: true}).waitFor();
  if ((await page.locator("main").innerText()).includes("简报优先展示现金")) throw Error("撤销后投影包含正文");
  return {status: "PASS", check_id: "A12-REVOCATION-AND-HISTORY", current_version: result.memory.version,
    history_version: result.latest_context_selection.memory_version, future_context_eligible: false,
    dom: await page.locator("main").ariaSnapshot()};
}
