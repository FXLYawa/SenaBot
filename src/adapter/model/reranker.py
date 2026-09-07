"""兼容 query/documents 与 results/index/relevance_score 协议的重排适配器；只调整顺序，保留向量相似度分数。"""

import logging
import math

import httpx

from core.memory.models import Experience, MemoryRetrievalCandidate


class MemoryReranker:
    """Memory重排序的调用接口,用于外部模型传入和配置"""
    def __init__(
        self, *, api_key: str, base_url: str, model: str,
        timeout_seconds: float = 10.0, endpoint: str = "rerank",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """读取配置并创建客户端"""
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
        """真正的重排序入口"""

        # 只有一个候选的时候直接返回,后续设定最低阈值时应删除
        if len(candidates) < 2:
            return list(candidates)
        # 提交要交给模型的正文
        documents = [
            item.memory.payload.summary
            if isinstance(item.memory.payload, Experience)
            else item.memory.payload.content
            for item in candidates
        ]
        try:
            # 发送请求
            response = await self._client.post(self._endpoint, json={
                "model": self._model,
                "query": query,
                "documents": documents,
                # 目前要求返回全部候选,真正的截取前多少条属于业务逻辑,交给业务板块
                "top_n": len(candidates),
                "return_documents": False,
            })
            # 确认http状态没有报错
            response.raise_for_status()
            # 拿到排好序的原始下标
            indices = _ranked_indices(response.json(), len(candidates))
        # 失败降级,直接退回检索顺序
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as error:
            # 不记录响应正文、凭证或候选记忆；失败不妨碍正常对话。
            self._logger.warning("Rerank failed (%s); retaining retrieval order", type(error).__name__)
            return list(candidates)
        # 按照下标取回原候选对象
        return [candidates[index] for index in indices]


def _ranked_indices(payload: object, count: int) -> list[int]:
    """负责检查外部响应"""
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
