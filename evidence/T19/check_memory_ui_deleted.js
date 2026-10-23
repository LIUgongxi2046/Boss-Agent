async (page) => {
  const [response] = await Promise.all([
    page.waitForResponse(item => item.url().endsWith("/api/boss/ui/admin/memory-status")),
    page.getByRole("button", {name: "检查技术状态", exact: true}).click(),
  ]);
  if (response.status() !== 200) throw Error("删除后的实际技术状态未成功读取");
  const result = await response.json();
  if (result.memory.version !== "5" || result.memory.confirmation_state !== "DELETED" || result.future_context_eligible ||
    result.next_context_memory_version !== null || result.deletion_scopes.current_memory_content !== "CLEARED" ||
    result.deletion_scopes.initial_approved_source !== "RETAINED" || result.physical_secure_erasure_verified)
    throw Error("当前内容、原始来源与物理擦除范围不符");
  const current = page.getByRole("region", {name: "当前记忆确认", exact: true});
  await current.getByText("DELETED", {exact: true}).waitFor();
  await current.getByText("没有可采用版本", {exact: true}).waitFor();
  const propagation = page.getByRole("region", {name: "删除传播范围", exact: true});
  for (const expected of ["CURRENT_CONTEXT_CLEARED", "CLEARED", "RETAINED", "尚未验证清理", "尚未验证", "未使用派生索引"])
    if (!(await propagation.innerText()).includes(expected)) throw Error("删除传播字段缺少：" + expected);
  const aside = page.getByRole("complementary", {name: "新会话与技术核查", exact: true});
  await aside.getByText("版本已经变化", {exact: true}).waitFor();
  if ((await page.locator("main").innerText()).includes("简报优先展示现金")) throw Error("删除后页面包含记忆正文");
  return {status: "PASS", check_id: "A12-DELETION-SCOPE-AND-REOPEN", current_version: result.memory.version,
    historical_context_version: result.latest_context_selection.memory_version,
    physical_erasure: "NOT_VERIFIED", dom: await page.locator("main").ariaSnapshot()};
}
