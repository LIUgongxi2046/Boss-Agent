# 候选 014 独立预览工具输出

任务：U2-01、U2-09；检查日期：2026-11-02。以下内容摘录自执行聊天中已有的工具调用和返回，保留命令、相关原始输出及退出状态。此文件为事后保存的摘录，完整进程日志与 HTTP 响应正文未单独保存；HTTP 检查的精确时间未提供。没有为保存本证据重复启动服务或重复请求。

## 启动

工具调用命令：

```text
bash .work/upgrade2/u2-03/candidate-014-preview.sh
```

调用返回：`session_id: 74910`；调用时进程仍在运行。后续读取该会话得到的相关原始输出：

```text
2026-11-02 01:56:31.421 | INFO | nanobot.cron.service:register_system_job:754 | NONE
应用验证服务已启动
```

启动入口使用候选 014 的安装环境、前端与独立模拟资料，隔离规则及其他参数可在入口脚本中核查。上述输出只证明服务报告启动，不能证明正式 Hermes 隔离或业务流程通过。

## HTTP 检查

```text
curl --silent --show-error --output /dev/null --write-out 'homepage=%{http_code}\n' http://127.0.0.1:18872/
homepage=200
exit_code: 0
```

```text
curl --silent --show-error --output /dev/null --write-out 'run_api=%{http_code}\n' http://127.0.0.1:18871/api/v2/runs/00000000-0000-0000-0000-000000000000
run_api=401
exit_code: 0
```

```text
curl --silent --show-error --output /dev/null --write-out 'run_api=%{http_code}\n' http://127.0.0.1:18874/api/v2/runs/00000000-0000-0000-0000-000000000000
run_api=401
exit_code: 0
```

同一次检查还请求了 `http://127.0.0.1:18871/`，原始输出为 `homepage=401`、`exit_code: 0`。三个 401 只证明对应未认证请求收到拒绝，响应正文未保存。

## 停止与端口

向会话 `74910` 发送 Ctrl-C 后，工具返回 `exit_code: 0`。相关原始输出：

```text
2026-11-02 01:57:03.192 | INFO | nanobot.agent.loop:stop:1592 | NONE
2026-11-02 01:57:03.193 | INFO | nanobot.channels.manager:stop_all:670 | NONE
2026-11-02 01:57:03.195 | INFO | nanobot.channels.manager:_stop_channel_runtime:414 | NONE
```

随后执行：

```text
lsof -nP -iTCP:18871-18874 -sTCP:LISTEN
```

工具返回空输出及 `exit_code: 1`，检查时没有列出这四个端口的监听进程。该检查只反映当时结果。

## 未保存字段与适用范围

未保存 HTTP 响应正文、响应头、完整服务日志、精确请求时间、独立数据集版本及完整未提交差异摘要。本证据不证明认证后的行为、本人决定后的恢复、实际 Hermes 业务执行、完整隔离或产品验收。
