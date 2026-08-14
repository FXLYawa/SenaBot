"""Desktop Adapter 的固定归属与本地 owner 身份补齐。"""

from __future__ import annotations

from core.body import AdapterInboundMessage

from adapter.base import BaseAdapter, InboundPublisher
from adapter.codec import Codec
from adapter.connector import Connector


class DesktopAdapter(BaseAdapter):
    """使用组合根提供的固定 owner identity 补齐 Desktop 入站消息。"""

    adapter_type = "desktop"
    platform = "desktop"

    def __init__(
        self,
        connector: Connector,
        codec: Codec,
        publish_input: InboundPublisher,
        owner_user_id: str,
        owner_display_name: str,
    ) -> None:
        super().__init__(connector, codec, publish_input)
        self.owner_user_id = owner_user_id
        self.owner_display_name = owner_display_name

    def _complete_inbound_message(self, message: AdapterInboundMessage) -> None:
        """在发布前用 localhost MVP 的固定 owner identity 覆盖 wire 占位值。"""
        message.user_id = self.owner_user_id
        message.display_name = self.owner_display_name
