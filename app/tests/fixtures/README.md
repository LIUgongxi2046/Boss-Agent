# 真实运行检查资料

`observed-owner-state`来自本工程独立隐藏桌面检查`source-review-4084bdad-2dbd-4f4b-adb6-7554f131b1ed`，包含同一获准selection、两项真实创建的交办以及本人来源确认记录。`observed-runtime-failure`来自本工程真实DeepSeek运行`run-7b051faa-8cc7-436a-9eda-145547ee18a1`，包含实际创建后保持OPEN的交办与实际传输失败记录。

数据库均使用SQLite原生backup产生，导出检查逐项比较逻辑内容并执行integrity_check。各目录manifest记录来源报告、数据库与相关源码SHA256。原库保持不变，导出不调用模型，不导入其他工作目录的数据库。

资料只包含已经获准的SIMULATED业务数据和实际技术记录。默认工程检查直接读取这些真实副本，不发起模型请求。新的模型行为验证继续使用明确的真实服务检查，不能从副本推断当前模型输出或业务质量。
