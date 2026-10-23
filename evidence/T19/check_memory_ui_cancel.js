async (page) => {
  await page.getByRole("button", {name: "检查技术状态", exact: true}).click();
  await page.getByText("正在读取当前确认与删除传播状态", {exact: true}).waitFor();
  await page.getByRole("button", {name: "取消查询", exact: true}).click();
  await page.getByText("已取消本次技术状态读取，记忆内容保持当前状态", {exact: true}).waitFor();
  if (!await page.getByRole("button", {name: "取消查询", exact: true}).isDisabled()) throw Error("取消后仍显示读取中");
  return {status: "PASS", check_id: "A12-CANCEL-PENDING-READ", backend_condition: "OWN_SERVICE_PROCESS_SUSPENDED",
    dom: await page.locator("main").ariaSnapshot()};
}
