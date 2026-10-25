async (page) => {
  const runId = "run-8142c95f-18a3-47f5-873e-2d215928586f";
  const taskId = "a11d0910-d79f-4144-8871-fe4ac16da38b";
  await page.getByRole("button", {name: "查询记录", exact: true}).click();
  await page.getByRole("button", {name: "打开记录 " + runId, exact: true}).click();
  const [response] = await Promise.all([
    page.waitForResponse(item => item.url().includes("/runtime-records/task?")),
    page.getByRole("button", {name: "查看关联任务 " + taskId, exact: true}).click(),
  ]);
  if (response.status() !== 200) throw Error("关联任务读取没有成功");
  const body = await response.json();
  const panel = page.getByRole("region", {name: "关联任务技术信息", exact: true});
  await panel.getByText("OPEN", {exact: true}).waitFor();
  if (body.run_id !== runId || body.task_id !== taskId || body.task_version !== "1" ||
    body.private_body_available_here !== false || body.business_mutation_performed !== false)
    throw Error("实际任务与界面关联不一致");
  const keys = Object.keys(body).sort();
  const expected = ["projection", "source_type", "task_source_type", "namespace", "run_id", "dataset_id",
    "dataset_version", "task_id", "task_version", "task_status", "read_at",
    "private_body_available_here", "business_mutation_performed"].sort();
  if (JSON.stringify(keys) !== JSON.stringify(expected)) throw Error("关联任务返回范围超出获准字段");
  const rejected = await page.evaluate(async ({runId, taskId}) => {
    const token = document.querySelector('meta[name="maintainer-token"]').content;
    const headers = {Authorization: "Bearer " + token};
    const path = "/api/boss/ui/runtime-records/task?";
    const valid = new URLSearchParams({run_id: runId, task_id: taskId});
    return {
      unauthenticated: (await fetch(path + valid)).status,
      caller_namespace: (await fetch(path + valid + "&namespace=other", {headers})).status,
      repeated: (await fetch(path + valid + "&task_id=" + taskId, {headers})).status,
      unlinked: (await fetch(path + new URLSearchParams({run_id: runId, task_id: runId}), {headers})).status,
    };
  }, {runId, taskId});
  if (JSON.stringify(rejected) !== JSON.stringify({unauthenticated: 401, caller_namespace: 400,
    repeated: 400, unlinked: 403})) throw Error("任务读取权限或查询范围判定不符");
  return {status: "PASS", check_id: "A15-REAL-TASK-REFERENCE", run_id: runId, task_id: taskId,
    task_status: body.task_status, task_version: body.task_version, rejected,
    dom: await page.locator("main").ariaSnapshot()};
}
