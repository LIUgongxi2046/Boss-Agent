async (page) => {
  const [response] = await Promise.all([
    page.waitForResponse(item => item.url().endsWith("/api/boss/ui/admin/memory-status")),
    page.getByRole("button", {name: "检查技术状态", exact: true}).click(),
  ]);
  if (response.status() !== 200) throw Error("删除后新Runtime记录未成功重读");
  const result = await response.json();
  const selection = result.latest_context_selection;
  if (result.memory.confirmation_state !== "DELETED" || result.memory.version !== "5" || result.future_context_eligible ||
    selection.memory_version !== "5" || selection.eligible || selection.run_status !== "SUCCEEDED" || !selection.model_completion_observed)
    throw Error("删除后真实新Runtime采用状态不符");
  const aside = page.getByRole("complementary", {name: "新会话与技术核查", exact: true});
  await aside.getByText("该次停止采用", {exact: true}).waitFor();
  await aside.getByText("版本一致", {exact: true}).waitFor();
  const field = name => aside.locator(".boss-kv").filter({has: page.getByText(name, {exact: true})}).locator("strong").innerText();
  if (await field("该次记忆版本") !== "5" || await field("已记录选择次数") !== "5")
    throw Error("删除后选择次数或版本未采用实际记录");
  return {status: "PASS", check_id: "A12-DELETED-NEW-RUNTIME", run_id: selection.run_id,
    current_version: result.memory.version, context_selection_count: result.context_selection_count,
    dom: await page.locator("main").ariaSnapshot()};
}
