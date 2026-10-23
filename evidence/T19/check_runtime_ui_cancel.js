async (page) => {
  await page.getByRole("button", {name: "查询记录", exact: true}).click();
  await page.getByText("正在读取运行记录", {exact: true}).waitFor();
  await page.getByRole("button", {name: "取消读取", exact: true}).click();
  await page.getByText("已取消本次读取，业务任务继续保持原有状态", {exact: true}).waitFor();
  if (!await page.getByRole("button", {name: "取消读取", exact: true}).isDisabled())
    throw Error("取消后读取仍显示进行中");
  if (await page.locator("tbody tr").count()) throw Error("取消后的新查询产生未读取记录");
  return {status: "PASS", check_id: "A15-CANCEL-PENDING-READ", backend_condition: "OWN_SERVICE_PROCESS_SUSPENDED",
    dom: await page.locator("main").ariaSnapshot()};
}
