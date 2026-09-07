"""兼容 query/documents 与 results/index/relevance_score 协议的重排适配器；只调整顺序，保留向量相似度分数。"""

import logging
import math

import httpx

from core.memory.models import Experience, MemoryRetrievalCandidate


class MemoryReranker:
    def __init__(
        self, *, api_key: str, base_url: str, model: str,
        timeout_seconds: float = 10.0, endpoint: str = "rerank",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._model = model
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout_seconds, transport=transport,
        )
        self._logger = logging.getLogger("senabot.memory.reranker")

    async def close(self) -> None:
        await self._client.aclose()

    async def rerank(
        self, query: str, candidates: list[MemoryRetrievalCandidate],
    ) -> list[MemoryRetrievalCandidate]:
        if len(candidates) < 2:
            return list(candidates)
        documents = [
            item.memory.payload.summary
            if isinstance(item.memory.payload, Experience)
            else item.memory.payload.content
            for item in candidates
        ]
        try:
            response = await self._client.post(self._endpoint, json={
                "model": self._model, "query": query, "documents": documents,
                "top_n": len(candidates), "return_documents": False,
            })
            response.raise_for_status()
            indices = _ranked_indices(response.json(), len(candidates))
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as error:
            # 不记录响应正文、凭证或候选记忆；失败不妨碍正常对话。
            self._logger.warning("Rerank failed (%s); retaining retrieval order", type(error).__name__)
            return list(candidates)
        return [candidates[index] for index in indices]


def _ranked_indices(payload: object, count: int) -> list[int]:
    if not isinstance(payload, dict):
        raise ValueError("rerank response must be an object")
    results = payload.get("results")
    if not isinstance(results, list) or len(results) != count:
        raise ValueError("rerank response must include every candidate")
    ranked = []
    seen = set()
    for result in results:
        if not isinstance(result, dict):
            raise ValueError("invalid rerank result")
        index, score = result["index"], result["relevance_score"]
        if type(index) is not int or not 0 <= index < count or index in seen:
            raise ValueError("invalid or duplicate candidate index")
        if type(score) not in (int, float) or not math.isfinite(score):
            raise ValueError("invalid relevance score")
        seen.add(index)
        ranked.append((index, score))
    return [index for index, _ in sorted(ranked, key=lambda item: item[1], reverse=True)]
