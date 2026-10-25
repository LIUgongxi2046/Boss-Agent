async (page) => {
  const runId = "run-8142c95f-18a3-47f5-873e-2d215928586f";
  const taskId = "a11d0910-d79f-4144-8871-fe4ac16da38b";
  const button = "查看关联任务 " + taskId;
  await page.getByRole("button", {name: button, exact: true}).click();
  await page.getByRole("region", {name: "关联任务技术信息", exact: true}).waitFor();
  await page.context().setOffline(true);
  await page.getByRole("button", {name: button, exact: true}).click();
  await page.getByRole("alert").waitFor();
  if (await page.getByRole("region", {name: "关联任务技术信息", exact: true}).count())
    throw Error("读取失败后仍展示旧任务信息");
  await page.context().setOffline(false);
  await page.getByRole("button", {name: "查询记录", exact: true}).click();
  await page.getByRole("button", {name: "打开记录 " + runId, exact: true}).click();
  await page.evaluate(() => {document.querySelector('meta[name="maintainer-token"]').content = "expired-session";});
  const [response] = await Promise.all([
    page.waitForResponse(item => item.url().includes("/runtime-records/task?")),
    page.getByRole("button", {name: button, exact: true}).click(),
  ]);
  if (response.status() !== 401) throw Error("失效身份没有拒绝关联任务读取");
  await page.getByRole("alert").filter({hasText: "HTTP 401"}).waitFor();
  if (await page.locator("tbody tr").count() ||
    await page.getByRole("region", {name: "关联任务技术信息", exact: true}).count())
    throw Error("身份失效后没有清理旧记录");
  await page.reload();
  return {status: "PASS", check_id: "A15-TASK-READ-ERRORS", offline_old_data_cleared: true,
    invalid_session_status: response.status(), dom: await page.locator("main").ariaSnapshot()};
}
