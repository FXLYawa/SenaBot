"""语言模型 Provider Adapter。"""

from adapter.model.openai_compatible import OpenAICompatibleProvider
from adapter.model.openai_embedding import OpenAICompatibleEmbeddingProvider

__all__ = ["OpenAICompatibleProvider", "OpenAICompatibleEmbeddingProvider"]
