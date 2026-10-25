async (page) => {
  const older = "run-47428cbf-2f1e-4ba6-92eb-85a9530db6ae";
  const local = async iso => page.evaluate(input => new Intl.DateTimeFormat("sv-SE", {
    year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false,
  }).format(new Date(input)).replace(" ", "T"), iso);
  await page.getByLabel("run_id", {exact: true}).fill(older);
  await page.getByLabel("真实开始时间从", {exact: true}).fill(await local("2026-10-23T06:19:00Z"));
  await page.getByLabel("真实开始时间至", {exact: true}).fill(await local("2026-10-23T06:20:00Z"));
  const [response] = await Promise.all([
    page.waitForResponse(item => item.url().includes("started_from=")),
    page.getByRole("button", {name: "查询记录", exact: true}).click(),
  ]);
  const parameters = new URL(response.url()).searchParams;
  if (response.status() !== 200 || parameters.get("started_from") !== "2026-10-23T06:19:00.000Z" ||
    parameters.get("started_until") !== "2026-10-23T06:20:00.000Z") throw Error("真实时间筛选转换不符");
  await page.getByText("已读取 1 / 匹配 1", {exact: true}).waitFor();
  if (!(await page.locator("tbody").innerText()).includes(older)) throw Error("运行编号和时间筛选结果不符");
  await page.getByRole("combobox", {name: "运行状态", exact: true}).selectOption("FAILED");
  await page.getByRole("button", {name: "查询记录", exact: true}).click();
  await page.getByText("没有符合当前条件的运行记录", {exact: true}).waitFor();
  if (await page.locator("tbody tr").count()) throw Error("空状态保留了旧记录");
  await page.getByLabel("真实开始时间从", {exact: true}).fill(await local("2026-10-24T06:19:00Z"));
  await page.getByRole("button", {name: "查询记录", exact: true}).click();
  await page.getByRole("alert").getByText("真实时间范围无效", {exact: true}).waitFor();
  await page.getByLabel("真实开始时间从", {exact: true}).fill("");
  await page.getByLabel("真实开始时间至", {exact: true}).fill("");
  await page.getByLabel("run_id", {exact: true}).fill("");
  await page.getByRole("combobox", {name: "运行状态", exact: true}).selectOption("SUCCEEDED");
  const denied = await page.evaluate(async () => {
    const response = await fetch("/api/boss/ui/runtime-records");
    return response.status;
  });
  if (denied !== 401) throw Error("实际未认证请求未返回401");
  await page.evaluate(() => {
    const meta = document.querySelector('meta[name="maintainer-token"]');
    if (!meta) throw Error("缺少当前会话配置");
    meta.setAttribute("content", "expired-session");
  });
  await page.getByRole("button", {name: "查询记录", exact: true}).click();
  await page.getByRole("alert").getByText("运行记录读取失败（HTTP 401）", {exact: true}).waitFor();
  if (await page.locator("tbody tr").count()) throw Error("身份失效后保留旧记录");
  return {status: "PASS", check_id: "A15-TIME-ID-EMPTY-AUTH", denied_http_status: denied,
    dom: await page.locator("main").ariaSnapshot()};
}
