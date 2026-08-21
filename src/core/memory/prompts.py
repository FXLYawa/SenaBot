MEMORY_EXTRACTION_PROMPT = """
你负责从当前的新消息中提取可能值得长期保存的用户信息。

历史摘要和最近消息只用于帮助理解当前消息，
不能直接作为本次新记忆的来源。

要求：
1. 只提取能够由当前新消息支持的信息。
2. 每条记忆只表达一个独立事实。
3. 不进行无依据推断。
4. 没有值得记录的信息时返回空列表。
5. 仅返回 JSON，不要输出其他内容。
6. Assistant 的内容只能用于帮助理解用户消息，
   不得把 Assistant 的推测、建议或未经用户确认的信息作为用户事实提取。

输出格式：
{{
  "memories": [
    {{
      "content": "..."
    }}
  ]
}}

历史摘要：
{summary}

最近消息：
{recent_messages}

当前新消息：
{new_messages}
""".strip()


MEMORY_UPDATE_PROMPT = """
你负责判断一条候选长期记忆应该如何影响已有长期记忆。

候选记忆：
{candidate}

已有相关记忆：
{existing_memories}

可选操作：

ADD
候选包含新的长期事实，已有记忆无法覆盖它。

UPDATE
候选与某条已有记忆描述同一事实，
但候选提供了补充、修正或更完整的信息。

DELETE
候选明确否定或使某条已有记忆失效。

NONE
候选已经被已有记忆完整覆盖，不需要修改。

要求：
1. 只能选择 ADD、UPDATE、DELETE、NONE 之一。
2. UPDATE 和 DELETE 必须指定已有相关记忆中的 memory_id。
3. target_memory_id 只能使用已有相关记忆中提供的 memory_id，
   不得自行生成 memory_id。
4. UPDATE 的 content 必须是更新后的完整记忆内容。
5. ADD 的 target_memory_id 必须为 null，
   content 为候选对应的完整记忆内容。
6. DELETE 的 content 必须为 null。
7. NONE 的 target_memory_id 和 content 都必须为 null。
8. 不得修改与候选记忆无关的已有记忆。
9. 仅返回 JSON，不要输出其他内容。

输出格式：
{{
  "action": "add | update | delete | none",
  "target_memory_id": "memory_id 或 null",
  "content": "完整记忆内容或 null"
}}
""".strip()
