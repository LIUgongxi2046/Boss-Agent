async (page) => {
  await page.getByRole("tab", {name: "任务提示 1", exact: true}).click();
  const choices = page.getByRole("combobox", {name: "当前类别已保存的版本", exact: true});
  const available = await choices.locator("option").evaluateAll(items => items.map(item => item.value).filter(Boolean));
  if (available.length !== 1) throw Error("没有取得既有实际Prompt版本");
  await choices.selectOption(available[0]);
  const body = page.getByRole("textbox", {name: "版本正文（20—5000 字）", exact: true});
  if (!(await body.inputValue())) throw Error("没有读取已保存Prompt正文");
  const [revoked] = await Promise.all([
    page.waitForResponse(response => response.url().endsWith("/component/session/revoke")),
    page.getByRole("button", {name: "撤销本次维护会话", exact: true}).click(),
  ]);
  if (revoked.status() !== 200) throw Error("真实本机会话没有撤销");
  await page.getByRole("status").filter({hasText: "Provider token 已清除"}).waitFor();
  const denied = await page.evaluate(async () => {
    const token = document.querySelector('meta[name="maintainer-token"]').content;
    return (await fetch("/api/boss/ui/workspace/prompt-versions", {headers: {Authorization: "Bearer " + token}})).status;
  });
  if (denied !== 401) throw Error("已撤销会话仍可以读取服务端配置");
  await page.waitForFunction(() => {
    const body = document.getElementById("boss-prompt-text");
    const choices = document.getElementById("boss-prompt-select");
    return body.value === "" && choices.options.length === 1 &&
      Array.from(document.querySelectorAll('[role="alert"]')).some(item => item.textContent.includes("身份已失效"));
  }, null, {timeout: 5000});
  for (const label of ["Prompt 标题", "获准知识来源 ID（逗号分隔）", "变更说明"]) {
    if (await page.getByRole("textbox", {name: label, exact: true}).inputValue()) throw Error("身份失效后保留配置字段：" + label);
  }
  return {status: "PASS", check_id: "A05-REVOKED-PROVIDER-IDENTITY", upstream_provider_used: true,
    server_rejection: denied, configuration_fields_cleared: true, stale_prompt_options_cleared: true,
    model_requests: 0, business_mutation_performed: false};
}
