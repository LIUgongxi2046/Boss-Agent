async (page) => {
  const newest = "run-37da688d-3c2b-4fdb-9f58-003073eef52f";
  const older = "run-47428cbf-2f1e-4ba6-92eb-85a9530db6ae";
  const [more] = await Promise.all([
    page.waitForResponse(item => item.url().includes("cursor_run_id=")),
    page.getByRole("button", {name: "读取更多记录", exact: true}).click(),
  ]);
  if (more.status() !== 200) throw Error("真实游标请求未成功");
  const query = new URL(more.url()).searchParams;
  if (query.get("cursor_run_id") !== newest || query.get("provider") !== "deepseek")
    throw Error("分页没有沿用当前真实游标及筛选条件");
  await page.getByText("已读取 2 / 匹配 2", {exact: true}).waitFor();
  const rows = page.locator("tbody tr");
  if (await rows.count() !== 2 || !(await rows.nth(1).innerText()).includes(older))
    throw Error("第二页记录与真实SQLite不一致");
  await page.getByRole("button", {name: "打开记录 " + newest, exact: true}).click();
  const aside = page.getByRole("complementary", {name: "运行记录详情"});
  await aside.getByText("runtime-1 · v2", {exact: true}).waitFor();
  if (!await aside.getByRole("button", {name: "查看关联任务（没有关联任务）", exact: true}).isDisabled())
    throw Error("无真实交办时关联任务操作必须不可用");
  const [detail] = await Promise.all([
    page.waitForResponse(item => new URL(item.url()).searchParams.get("run_id") === newest),
    aside.getByRole("button", {name: "核查明细", exact: true}).click(),
  ]);
  if (detail.status() !== 200) throw Error("单项记录重新读取未成功");
  await aside.getByText("3129e7ba-0745-4f26-88c5-e87f60b3c310", {exact: true}).waitFor();
  const text = await aside.innerText();
  for (const expected of ["内容v4", "启用v2", "2176", "294", "null（未核算）",
    "COMPLETE_OBSERVED_REQUESTS", "HTTP_REQUESTS_OBSERVED_ONLY", "未通过本投影判定", "read_evidence"])
    if (!text.includes(expected)) throw Error("真实明细字段缺少：" + expected);
  if (text.includes("合成水产饲料外销明细") || text.includes("简报优先展示现金"))
    throw Error("技术记录页面包含私人正文");
  return {status: "PASS", check_id: "A15-PAGINATION-DETAILS-COST", actual_run_ids: [newest, older],
    linked_task_branch: "NOT_RUN_NO_TASK", dom: await page.locator("main").ariaSnapshot()};
}
