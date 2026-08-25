MEMORY_MATERIALIZATION_PROMPT = """
你负责将一条候选长期记忆转换为唯一、结构化的领域 Payload。

候选记忆是本次要成形的唯一新信息来源。
相关旧记忆只能帮助理解语境、判断类型和引用证据，
不得把旧记忆中本次候选未表达的信息合并进新 Payload。

可选领域：

fact
关于用户、群体或现实状态的可陈述事实，包括明确表达的偏好。

experience
用户、Sena 或其他参与者实际经历过的事件。

understanding
Sena 根据已有记忆证据形成的长期理解或概括。
understanding 必须引用下方相关旧记忆中真实存在的 item_id。

knowledge
可复用的专业知识或通用知识，不是某个用户的个人事实。

要求：
1. 只能选择 fact、experience、understanding、knowledge 之一。
2. 不得返回 item_id、memory_space_id、scopes、provenance、recorded_at 或 operation_id。
3. 不得在本阶段决定新增、更新、删除或替代记忆。
4. 文本字段必须是去除首尾空白后的完整独立陈述。
5. 时间使用 ISO 8601 字符串；无法从候选中确定时返回 null，不得猜测。
6. participants 的每一项必须包含非空 entity_type 和 entity_id。
7. evidence_item_ids 只能使用下方提供的 item_id。
8. 仅返回 JSON 对象，不要输出其他内容。

输出格式：

fact：
{{
  "domain": "fact",
  "payload": {{
    "content": "...",
    "valid_from": "ISO 8601 或 null",
    "valid_to": "ISO 8601 或 null"
  }}
}}

experience：
{{
  "domain": "experience",
  "payload": {{
    "summary": "...",
    "participants": [
      {{"entity_type": "...", "entity_id": "..."}}
    ],
    "occurred_from": "ISO 8601 或 null",
    "occurred_to": "ISO 8601 或 null"
  }}
}}

understanding：
{{
  "domain": "understanding",
  "payload": {{
    "content": "...",
    "evidence_item_ids": ["item_id"]
  }}
}}

knowledge：
{{
  "domain": "knowledge",
  "payload": {{
    "content": "..."
  }}
}}

系统记录时间（仅用于理解相对时间，不得返回）：
{recorded_at}

相关旧记忆：
{related_items}

本次候选记忆：
{candidate}
""".strip()
