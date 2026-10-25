async (page) => {
  await page.context().setOffline(true);
  try {
    await page.getByRole("button", {name: "查询记录", exact: true}).click();
    await page.getByRole("alert").waitFor();
    const message = await page.getByRole("alert").innerText();
    if (!message.includes("Failed to fetch")) throw Error("断网后未显示实际读取失败");
    if (await page.locator("tbody tr").count()) throw Error("断网后保留旧查询记录");
  } finally {
    await page.context().setOffline(false);
  }
  await page.getByRole("button", {name: "查询记录", exact: true}).click();
  await page.getByText("已读取 2 / 匹配 2", {exact: true}).waitFor();
  return {status: "PASS", check_id: "A15-OFFLINE-AND-RECOVERY", backend_mutation_performed: false,
    dom: await page.locator("main").ariaSnapshot()};
}
