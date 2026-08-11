"""知识库嵌入模型提供者工厂。

背景：rag.yml 中的 api_key 是 DeepSeek（对话）专用，对 DashScope（嵌入）无效，
导致嵌入调用 401。本模块将嵌入提供者独立配置化（全部为在线服务）：

- ``dashscope`` ：远程 DashScope 嵌入，支持独立 ``embedding_api_key``
  （缺省回退 rag.yml 的 api_key）
- ``openai``   ：OpenAI 兼容端点嵌入（如阿里云百炼 compatible-mode），
  HTTP 直连 /embeddings，无新增依赖

配置位置：config/chroma.yml

.. code-block:: yaml

    embedding_provider : openai              # dashscope | openai
    openai_base_url : https://xxx/compatible-mode/v1
    openai_api_key : sk-xxx
    openai_embedding_model : qwen3.7-text-embedding

注意：切换提供者会改变向量维度/空间，kb_store 集合将在下次初始化时
自动清空并触发全量重建（自愈合，无需手工清库）。
"""
import time
from typing import Optional

from langchain_core.embeddings import Embeddings

from AIRAGAgent.utils.config_handler import chroma_conf, rag_conf
from AIRAGAgent.utils.logger_handler import logger

BATCH_SIZE = 32


class OpenAICompatEmbeddings(Embeddings):
    """OpenAI 兼容端点的嵌入实现（直连 /embeddings，无新增依赖）。

    适用于阿里云百炼/魔搭 MaaS 等 OpenAI 兼容端点：
    POST {base_url}/embeddings，Header Authorization: Bearer {api_key}，
    请求体 {"model": ..., "input": [...]}，响应 data[i].embedding。

    注意：部分云端（如阿里云百炼 qwen3.7-text-embedding）限制单批 ≤ 20 条，
    本类用独立 ``batch_size`` 控制，默认 20。
    """

    def __init__(self, base_url: str, api_key: str, model: str, timeout: int = 60, batch_size: int = 20):
        """初始化嵌入客户端：校验 base_url/api_key 并记录模型与批次大小。"""
        self.base_url = (base_url or "").rstrip("/")
        if not self.base_url:
            raise ValueError("[KB] openai_base_url 未配置")
        self.api_key = api_key or ""
        if not self.api_key:
            raise ValueError("[KB] openai_api_key 未配置")
        self.model = model or "qwen3.7-text-embedding"
        self.timeout = timeout
        self.batch_size = batch_size

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """按批次调用 /embeddings 接口为文本列表生成向量，返回每个文本对应的向量列表。"""
        import requests
        url = f"{self.base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i:i + self.batch_size]
            resp = requests.post(
                url,
                json={"model": self.model, "input": batch},
                headers=headers,
                timeout=self.timeout,
            )
            if resp.status_code != 200:
                raise RuntimeError(
                    f"OpenAI 兼容嵌入调用失败 status={resp.status_code} "
                    f"url={url} body={resp.text[:500]}"
                )
            data = resp.json()
            out.extend([d["embedding"] for d in data["data"]])
        return out

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """为多个文本批量生成向量。"""
        return self._embed_batch(texts)

    def embed_query(self, text: str) -> list[float]:
        """为单个查询文本生成向量。"""
        return self._embed_batch([text])[0]


def get_embedding_provider() -> str:
    """从配置中读取当前嵌入提供者名称（dashscope/openai），返回小写字符串。"""
    return str(chroma_conf.get("embedding_provider", "openai")).strip().lower()


def get_kb_embeddings() -> Embeddings:
    """按 chroma.yml 配置创建知识库专用嵌入模型"""
    provider = get_embedding_provider()

    if provider == "dashscope":
        from langchain_community.embeddings import DashScopeEmbeddings
        api_key = rag_conf.get("embedding_api_key") or rag_conf.get("api_key")
        model = rag_conf.get("embedding_model_name", "text-embedding-v4")
        logger.info(f"[KB] 嵌入提供者: dashscope model={model}")
        return DashScopeEmbeddings(model=model, dashscope_api_key=api_key)

    if provider == "openai":
        base_url = str(chroma_conf.get("openai_base_url", ""))
        api_key = str(chroma_conf.get("openai_api_key", ""))
        model = str(chroma_conf.get("openai_embedding_model", "qwen3.7-text-embedding"))
        logger.info(f"[KB] 嵌入提供者: openai-compatible model={model} url={base_url}")
        return OpenAICompatEmbeddings(base_url=base_url, api_key=api_key, model=model)

    raise ValueError(f"[KB] 未知嵌入提供者 embedding_provider={provider}，可选：dashscope | openai")


def probe_embeddings(embeddings: Embeddings) -> dict:
    """探测嵌入模型可用性：返回维度、耗时、错误信息（用于诊断与维度变更检测）"""
    t0 = time.time()
    try:
        vec = embeddings.embed_query("维度探测")
        return {
            "ok": True,
            "dim": len(vec),
            "latency_ms": int((time.time() - t0) * 1000),
            "error": "",
        }
    except Exception as e:
        return {
            "ok": False,
            "dim": 0,
            "latency_ms": int((time.time() - t0) * 1000),
            "error": str(e)[:500],
        }


def embedding_status() -> dict:
    """诊断端点用：当前提供者 + 可用性探测"""
    provider = get_embedding_provider()
    try:
        emb = get_kb_embeddings()
    except Exception as e:
        return {"provider": provider, "ok": False, "dim": 0, "latency_ms": 0, "error": str(e)[:500]}
    result = probe_embeddings(emb)
    result["provider"] = provider
    if provider == "openai":
        result["model"] = str(chroma_conf.get("openai_embedding_model", "qwen3.7-text-embedding"))
    else:
        result["model"] = rag_conf.get("embedding_model_name", "text-embedding-v4")
    return result
