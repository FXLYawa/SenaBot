MEMORY_REVIEW_PROMPT = """
你负责审查一条已经成形的长期记忆 Payload，判断它应该如何影响已有相关记忆。

你只能决定操作类型和选择已提供的 target_item_id。
不得改写 Payload，不得返回 content、payload、replacement、provenance、scopes 或新的 item_id。

操作：

add
当前 Payload 是值得保存的新记忆。

end_fact_validity
已有 Fact 曾经有效，但被当前 Fact 明确变更或否定。
只能选择已提供的 Fact item_id。

supersede
当前 Understanding 或 Knowledge 应当替代同领域的已有版本。
只能选择已提供且同领域的 item_id。

no_change
已有记忆已完整覆盖当前 Payload，或当前 Payload 不应形成正式记忆。

领域规则：
1. Fact 可以 add、end_fact_validity、end_fact_validity + add 或 no_change。
2. Experience 只能 add 或 no_change；已发生的经历不得失效或被替代。
3. Understanding 只能 add、supersede 或 no_change。
4. Knowledge 只能 add、supersede 或 no_change。
5. no_change 不得与其他操作组合。
6. 同一个 target_item_id 不得被操作多次。
7. 单个 Payload 最多执行一次 add 或一次 supersede。
8. 仅返回 JSON 对象，不要输出其他内容。

每种操作只允许以下字段，不得添加无关字段：

add：
{{"type": "add"}}

end_fact_validity：
{{"type": "end_fact_validity", "target_item_id": "已提供的 Fact item_id"}}

supersede：
{{"type": "supersede", "target_item_id": "已提供的同领域 item_id"}}

no_change：
{{"type": "no_change", "reason": "可选原因"}}

最终输出格式：
{{"operations": [上述操作对象]}}

当前 Payload：
{payload}

已有相关记忆：
{related_items}
""".strip()
