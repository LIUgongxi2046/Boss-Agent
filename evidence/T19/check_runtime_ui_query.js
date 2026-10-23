async (page) => {
  await page.getByRole("heading", {name: "运行记录", exact: true}).waitFor();
  await page.getByLabel("Provider", {exact: true}).fill("deepseek");
  await page.getByLabel("数据集", {exact: true}).fill("selection");
  await page.getByLabel("错误类型或终止原因").fill("completed");
  await page.getByRole("combobox", {name: "运行状态", exact: true}).selectOption("SUCCEEDED");
  await page.getByRole("combobox", {name: "每页数量", exact: true}).selectOption("1");
  const [response] = await Promise.all([
    page.waitForResponse(item => item.url().includes("/api/boss/ui/runtime-records?")),
    page.getByRole("button", {name: "查询记录", exact: true}).click(),
  ]);
  if (response.status() !== 200) throw Error("真实运行记录 API 未成功");
  const query = new URL(response.url()).searchParams;
  for (const [key, expected] of Object.entries({provider: "deepseek", dataset_id: "selection",
    stop_reason: "completed", status: "SUCCEEDED", limit: "1"})) {
    if (query.get(key) !== expected) throw Error("服务端筛选字段不匹配：" + key);
  }
  await page.getByText("已读取 1 / 匹配 2", {exact: true}).waitFor();
  if (await page.locator("tbody tr").count() !== 1) throw Error("首个分页记录数量不符");
  const realId = "run-37da688d-3c2b-4fdb-9f58-003073eef52f";
  if (!(await page.locator("tbody").innerText()).includes(realId)) throw Error("首个分页未采用真实运行编号");
  return {status: "PASS", check_id: "A15-QUERY-REAL-METADATA", first_run_id: realId,
    dom: await page.locator("main").ariaSnapshot()};
}
