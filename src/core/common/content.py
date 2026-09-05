"""跨模块传递的结构化内容。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ContentType(StrEnum):
    """内容及其分段的类型"""

    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    FILE = "file"
    LINK = "link"
    COMMAND = "command"
    INTERACTION = "interaction"
    MIXED = "mixed"
    SYSTEM_MESSAGE = "system_message"


@dataclass(frozen=True, slots=True)
class ContentSegment:
    """有序内容中的一个片段，数据字段由片段类型决定"""

    type: ContentType
    data: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Content:
    """结构化正文及其可选文本表示"""

    content_type: ContentType = ContentType.TEXT
    text: str | None = None
    segments: tuple[ContentSegment, ...] = ()

    def __post_init__(self) -> None:
        # 非空分段决定内容类型；没有分段时保留调用方指定的类型。
        segment_types = {segment.type for segment in self.segments}
        if len(segment_types) == 1:
            object.__setattr__(self, "content_type", next(iter(segment_types)))
        elif len(segment_types) > 1:
            object.__setattr__(self, "content_type", ContentType.MIXED)

        # 显式文本可以是转写等派生表示；缺省时仅拼接文本片段。
        if self.text is None:
            value = "\n".join(
                str(segment.data.get("text", ""))
                for segment in self.segments
                if segment.type == ContentType.TEXT
            ).strip()
            object.__setattr__(self, "text", value or None)

    @classmethod
    def from_text(cls, value: str) -> Content:
        """用文本构造正文，并保留对应的结构化片段。"""

        return cls(
            ContentType.TEXT,
            value,
            (ContentSegment(ContentType.TEXT, {"text": value}),),
        )

    def text_value(self) -> str:
        """返回去除首尾空白的文本表示，不解析非文本片段。"""

        return (self.text or "").strip()
