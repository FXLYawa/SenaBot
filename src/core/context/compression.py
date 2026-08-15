"""Context 窗口压缩与可选语义摘要"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from core.context.common import load_prompt, render_prompt
from core.model import ModelMessage, ModelProvider, ModelRequest


@dataclass(frozen=True, slots=True)
class CompressionItem:
    """Compressor 可以统一处理的有序文本块"""
    
    first_sequence: int # 对应的原始上下文条目序号
    last_sequence: int
    label: str # 提供给模型的简要来源说明
    text: str # 需要压缩的文本内容



@dataclass(frozen=True, slots=True)
class CompactionInput:
    """一次上下文压缩的输入快照"""
    
    target_level: int # 本次生成的摘要层级
    items: tuple[CompressionItem, ...] # 原始条目或者摘要字段
    context_before: tuple[CompressionItem, ...] = ()  # 可选、辅助压缩模块理解的上下文内容，通常是前一层级的摘要
    context_after: tuple[CompressionItem, ...] = ()  # 可选、只辅助理解的后置内容。
    

class ContextCompressor(Protocol):
    """可选的语义摘要策略；无法生成完整摘要时返回 ``None``。"""

    async def compress(self, compaction_input: CompactionInput) -> str | None: ...

    
@dataclass(frozen=True, slots=True)
class CompactionRequestData:
    """交给上下文压缩事件的请求数据快照"""
    
    session_id: str # 会话标识
    input: CompactionInput # 需要被压缩的上下文输入
    source_summary_ids: tuple[str, ...] = () # 参与本次压缩的原始摘要 ID 列表
    
    
class ContextCompressor(Protocol):
    """上下文压缩器以及对应的压缩策略, 无法生成完整摘要时返回None"""
    
    async def compress(self, input: CompactionInput) -> str | None: ...
    
    
class LLMCompressor:
    """生成式上下文压缩器，使用 LLM 进行上下文压缩"""
    
    def __init__(
        self,
        provider: ModelProvider,
        entry_char_limit: int = 8000, # 单条上下文条目字符限制
    ) -> None:
        if entry_char_limit < 1:
            raise ValueError("entry_char_limit must be positive")
        self._provider = provider # 模型接口，具体的模型由 provider 决定
        self._entry_char_limit = entry_char_limit # 单条上下文条目的上限
        
    async def compress(self, input: CompactionInput) -> str | None:
        """使用 LLM 对上下文进行压缩"""

        # 将原始条目做一下预处理拼接
        prompt = render_prompt(
            "core.context.prompts",
            "compaction_input.txt",
            target_level=input.target_level,
            context_before=_format_items(
                input.context_before,
                self._entry_char_limit,
            ),
            content=_format_items(
                input.items,
                self._entry_char_limit,
            ),
            context_after=_format_items(
                input.context_after,
                self._entry_char_limit,
            ),
        )
        # 生成模型请求
        request = ModelRequest(
            (
                ModelMessage(
                    "system",
                    load_prompt("core.context.prompts", "compaction_system.txt"),
                ),
                ModelMessage("user", prompt),
            ),
            temperature=0.2,
        )
        
        result = await self._provider.generate(request)
        
        if result.finish_reason.lower() in {"length", "max_tokens"}:
            return None
        return result.text.strip() or None


def _format_items(items: tuple[CompressionItem, ...], limit: int) -> str:
    """渲染模型输入；空参考区明确标记为无，避免与目标内容混淆。"""

    if not items:
        return "(无)"
    # 输入保护值来自 Context 配置；保留首尾比只取开头更不易丢失最终结论。
    return "\n".join(
        f"{item.first_sequence}-{item.last_sequence} | {item.label}: "
        f"{_limit_entry(item.text, limit)}"
        for item in items
    )

        
def _limit_entry(text: str, limit: int) -> str:
    """对于异常长的单条输入做截断，保留首尾部分，避免丢失最终结论。"""
    
    if len(text) <= limit:
        return text
    marker = "\n……[中间内容超过摘要输入上限]……\n"
    available = max(0, limit - len(marker))
    if available == 0:
        return marker[:limit]
    head = available * 2 // 3
    return text[:head] + marker + text[-(available - head) :]
        
