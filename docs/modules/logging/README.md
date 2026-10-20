# 日志基础设施第一阶段

基于远程 `develop` 的 `5b0795d`（PR #95），实现于本地 `feat/logging-infrastructure`。
本阶段实现不依赖错误统一的部分，不改变错误类型、业务失败事件、重试次数、降级策略及异常归属。

## 设计评估与明确约定

原方案的目录边界、标准库 logging、单进程同步轮转与事件消费端绑定均适合目前项目。
实现前明确了以下细节，避免把设计建议当成现有能力：

1. **观察事件可以与日志并存。** 事件不必全是命令，也可以是供其他模块订阅的状态事实。
   仓库已有 `context.state.changed`，Memory 根据它决定是否提取，说明观察需求有实际用途。
   以后还可以定义专门的观测事件或订阅器；但日志基础设施不依赖 EventBus，也不为每条日志发布事件。
   观察订阅者可以调用 Logger，Logger 不反向发布观察事件，避免故障递归。
2. **日志基础设施无需等待错误统一。** 错误码规范、失败事件合并、堆栈归属和统一重试需等统一方案；
   文件输出、字段、关联、正常流程记录与生命周期可先实现。队友关于异常相关改动可能返工的担忧合理，
   但它不构成推迟整个基础设施的理由。
3. `log_kind` 明确为 `runtime`、`trace`、`both`；未指定默认为 `runtime`。
   `both` 的一条记录分别接受两路等级过滤；控制台只输出 runtime/both。
   这三种值是分类，不新增 TRACE 等级。
4. 普通事件沿用已有 `TraceInfo`，不再创建平行的事件追踪协议。
   **当前 Memory 批次的业务事件仍继承前台 Trace**，所以原文“后台批次已独立”不能当成现状。
   本阶段仅为批次日志生成独立 Trace：在已有 metadata 中携带 `log_trace_id` 和 `parent_trace_id`，
   由事件消费端提取。`EventEnvelope.trace` 保持原语义；`event_id` 仍是实际当前事件 ID。
   重新排入的下一批次得到新的日志 Trace。未来若要改变业务 Trace 规则，需单独修改 Event 契约。
5. `log_context(reset=True, ...)` 用于消费端和独立任务，避免继承旧 event/session/operation。
   普通嵌套上下文合并字段，退出、异常和取消均恢复。字段只能是允许的标量，不持有 payload。
6. 正则无法识别任意聊天正文。业务调用点只传固定描述和安全标量；Formatter 只输出允许字段，
   未知 extra 丢弃，复杂对象不调用 repr。凭据样式和 URL 做兜底替换。
   异常仅保留类型和最多 24 个调用位置，不输出异常正文、源码行、locals 或 SDK 响应。
   这是受管理日志的约束，不是对第三方自行安装 Handler 或手写 print 的全进程安全承诺。
7. 轮转容量是近似预算，单条记录有长度上限，文件容量仍受编码和轮转时机影响；不是精确磁盘配额。

## 使用

```python
from infrastructure.logging import get_logger, log_context

logger = get_logger(__name__)
with log_context(trace_id="trace-id", session_id="session-id"):
    logger.info("Query completed", extra={
        "log_kind": "trace",
        "action": "memory.query_completed",
        "result_count": 3,
    })
```

`get_logger` 返回兼容标准日志调用的安全 LoggerAdapter，保留每次调用的 extra。
不要传 `extra['module']` 等 LogRecord 保留字段；输出 `module` 从 Logger 名称派生。
新增业务字段需要评估是否含敏感内容，再加入 `formatter.py` 的允许列表。
只在进程入口调用 `configure_logging(LoggingConfig(...))` 和 `shutdown_logging()`。
导入及 get_logger 不创建文件、不添加 Handler。嵌入式 `run()` 的日志生命周期由调用方管理。

配置位置：`config/logging.toml`。默认控制台和 runtime 文件开启，Trace 关闭。
开启 `trace = true` 可查看链路，排查内部步骤时同时设置 `trace_level = "DEBUG"`。
相对目录始终相对于仓库根目录，与终端当前目录无关。

| 输出 | 等级配置 | 轮转 |
| --- | --- | --- |
| stderr 紧凑文本 | level | 无 |
| logs/senabot.log，JSON Lines | level | 20 MiB，5 份备份 |
| logs/senabot.trace.log，JSON Lines | trace_level | 50 MiB，3 份备份 |

`file=false` 禁止所有文件输出；console/file 都为 false 时安装 NullHandler，阻止 lastResort。
命名空间为 `senabot.*`，不向 root 传播；重复配置只替换本设施拥有的 Handler。
文件初始化失败则降级到 stderr；运行中格式化/写入失败使用固定文本、30 秒限频诊断。
每个进程使用自己的目录，不允许多个进程共享同一组轮转文件。

## 本阶段覆盖

- 两种进程入口的初始化、退出释放；实际配置入口在模型和 Data 初始化前建立 stderr 出口。
- Adapter 服务启动/停止；Body 输入在获得真实事件 Trace 的首个消费边界记录长度；输出记录结果数量与耗时。
- Event 发布、分发、每次 Handler 开始和提交；队列消费、控制 Handler 和普通 Handler 都重绑定上下文。
  `handler_completed` 只表示 Handler 返回并提交，不意味着它产生的业务结果一定成功。
- Context 准备的条目/摘要数量、压缩完成；冷恢复中每条暂存输入重绑定自己的原始事件。
- Agent Run 开始、正常完成、Effect 路由；不记录 Observation 或行为状态。
- Memory 查询、召回/重排数量；批次调度、范围、候选数量、成功保存水位后的完成日志。
  新增、结束有效期、替代分别记录，单次变更成功后立即写 runtime，即使后续变更失败也保留已完成事实。
- Model/Embedding 独立 operation_id、开始/完成与耗时，只输出实际返回的 Token 用量。
- Data 初始化和超过 100ms 的事务观测，不输出 SQL 或参数。
- 既有 reranker 降级日志改为结构化 WARNING；其降级行为不变。

## 明确留到错误统一之后

失败事件与错误码统一、所有失败节点结构化补齐、全链路“同一堆栈只记一次”、
Provider 重试/切换与统一终止归属、Data 事务失败归属、Memory 查询失败后继续回答的统一分类。
现有错误分支保留；已有异常日志去除异常原文插值以防凭据/正文泄露。
因此本文不宣称原设计的所有异常相关验收已经完成。

本次没有增加新的观察事件类型、日志数据库、审计服务或尚未接入的工具业务。
服务启动日志也不表示某个外部客户端已经建立连接。

## 验证

`python -m pytest -q tests/infrastructure`：14 项通过。
覆盖并发会话、跨队列派生、背景批次 metadata、嵌套/取消恢复、双路与独立等级、禁用、
重配置、轮转、脱敏、字段限制、目录失败、写盘/格式化失败、入口释放和真实应用对话。
真实应用测试使用本地假模型与内存 SQLite，不调用远程 API。

对同一 Python 环境运行原始 `5b0795d` 快照和本地修改版本：

| 版本 | 通过 | 失败 | 收集错误 |
| --- | ---: | ---: | ---: |
| 原始 HEAD 快照 | 173 | 44 | 17 |
| 本地日志版本 | 187 | 44 | 17 |

两版失败项/收集错误清单相同（均另有 13 个通过的 subtest）。旧测试涉及模块迁移、
旧 Agent/Event 接口、数据库版本、模型返回类型及配置路径等，不能将全仓测试描述为全绿。
对照输出保存在本地忽略目录 `output/logging-validation/`，不提交包含运行环境路径的原始测试报告。
