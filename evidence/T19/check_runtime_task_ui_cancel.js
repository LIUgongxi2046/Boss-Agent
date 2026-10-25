async (page) => {
  const taskId = "a11d0910-d79f-4144-8871-fe4ac16da38b";
  await Promise.all([
    page.waitForRequest(item => item.url().includes("/runtime-records/task?")),
    page.getByRole("button", {name: "查看关联任务 " + taskId, exact: true}).click(),
  ]);
  await page.getByRole("button", {name: "取消读取", exact: true}).click();
  await page.getByRole("status").filter({hasText: "已取消本次读取"}).waitFor();
  if (await page.getByRole("region", {name: "关联任务技术信息", exact: true}).count())
    throw Error("取消读取后出现关联任务结果");
  return {status: "PASS", check_id: "A15-TASK-CANCEL-PENDING-READ", business_mutation_performed: false,
    dom: await page.locator("main").ariaSnapshot()};
}
