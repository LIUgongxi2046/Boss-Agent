async (page) => {
  await page.context().setOffline(true);
  try {
    await page.getByRole("button", {name: "检查技术状态", exact: true}).click();
    await page.getByRole("alert").waitFor();
    if (!(await page.getByRole("alert").innerText()).includes("Failed to fetch")) throw Error("实际断网错误未显示");
    await page.getByRole("region", {name: "保存或索引失败定位", exact: true}).getByText("读取失败", {exact: true}).waitFor();
    const current = page.getByRole("region", {name: "当前记忆确认", exact: true});
    if ((await current.innerText()).includes("DELETED")) throw Error("读取失败后仍显示旧确认记录");
  } finally {
    await page.context().setOffline(false);
  }
  await page.getByRole("button", {name: "检查技术状态", exact: true}).click();
  await page.getByRole("region", {name: "当前记忆确认", exact: true}).getByText("DELETED", {exact: true}).waitFor();
  const statuses = await page.evaluate(async () => {
    const token = document.querySelector('meta[name="maintainer-token"]').getAttribute("content");
    const denied = await fetch("/api/boss/ui/admin/memory-status");
    const forbiddenQuery = await fetch("/api/boss/ui/admin/memory-status?namespace=another-space", {
      headers: {Authorization: "Bearer " + token},
    });
    return {unauthenticated: denied.status, caller_namespace: forbiddenQuery.status};
  });
  if (statuses.unauthenticated !== 401 || statuses.caller_namespace !== 400) throw Error("真实读取鉴权或字段拒绝不符");
  await page.evaluate(() => document.querySelector('meta[name="maintainer-token"]').setAttribute("content", "expired-session"));
  const [response] = await Promise.all([
    page.waitForResponse(item => item.url().endsWith("/api/boss/ui/admin/memory-status")),
    page.getByRole("button", {name: "检查技术状态", exact: true}).click(),
  ]);
  if (response.status() !== 401) throw Error("失效会话没有返回实际401");
  await page.getByRole("alert").getByText("记忆技术状态读取失败（HTTP 401）", {exact: true}).waitFor();
  if ((await page.getByRole("region", {name: "当前记忆确认", exact: true}).innerText()).includes("DELETED"))
    throw Error("身份失效后保留旧记忆状态");
  return {status: "PASS", check_id: "A12-READ-FAILURE-AUTH-AND-RECOVERY", actual_statuses: statuses,
    dom: await page.locator("main").ariaSnapshot()};
}
