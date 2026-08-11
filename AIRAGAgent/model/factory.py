from abc import ABC, abstractmethod
from typing import Optional
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_deepseek import ChatDeepSeek
from AIRAGAgent.utils.config_handler import rag_conf


class BaseModelFactory(ABC):
    @abstractmethod
    def generator(self) -> Optional[Embeddings | BaseChatModel]:
        """抽象接口：由子类实现生成具体的模型实例。"""
        pass


class ChatModelFactory(BaseModelFactory):
    def generator(self) -> Optional[Embeddings | BaseChatModel]:
        """创建对话模型实例：DeepSeek 用 ChatDeepSeek，其他用 ChatTongyi。"""
        model_name = rag_conf["chat_model_name"]
        api_key = rag_conf["api_key"]

        if "deepseek" in model_name.lower():
            return ChatDeepSeek(model=model_name, api_key=api_key, max_tokens=4096, temperature=0.7,
                                request_timeout=240, max_retries=1)

        return ChatTongyi(model=model_name, api_key=api_key)


class EmbeddingsFactory(BaseModelFactory):
    def generator(self) -> Optional[Embeddings | BaseChatModel]:
        """创建并返回嵌入模型实例，API Key支持独立配置或回退共享Key。"""
        # 嵌入模型支持独立 API Key（embedding_api_key），
        # 缺省回退共享 api_key —— 例如 DeepSeek 对话 key 与 DashScope 嵌入 key 不同的场景
        api_key = rag_conf.get("embedding_api_key") or rag_conf["api_key"]
        return DashScopeEmbeddings(
            model=rag_conf["embedding_model_name"],
            dashscope_api_key=api_key
        )


chat_model = ChatModelFactory().generator()
embed_model = EmbeddingsFactory().generator()


# ==================== 用户自配模型（OpenAI 兼容） ====================

def _fetch_user_model_config(user_id: int) -> Optional[dict]:
    """从 user_service 拉取用户自配的模型配置。

    返回 {"base_url": ..., "api_key": ..., "model_name": ...} 或 None。
    仅在当前进程内（chat_service 环境）可用；拉取失败或未配置返回 None。
    """
    try:
        import httpx
        import os
        url = os.getenv("USER_SERVICE_URL", "http://127.0.0.1:8002")
    except Exception:
        url = "http://127.0.0.1:8002"  # 兜底：user_service 默认端口
    try:
        resp = httpx.get(
            f"{url}/internal/user/model-config",
            params={"user_id": user_id},
            headers={"X-Internal-Call": "1"},
            timeout=3.0,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        return data.get("config") or None
    except Exception:
        return None


def get_user_chat_model(user_id: int) -> BaseChatModel:
    """按用户解析对话模型：用户已自配 OpenAI 兼容模型则返回该模型，否则回退系统默认模型。

    不缓存：每次实时拉取（本地内部接口开销 <5ms），用户保存配置后立即生效。
    """
    if not user_id:
        return chat_model
    cfg = _fetch_user_model_config(user_id)
    if not cfg:
        return chat_model
    try:
        base_url = (cfg.get("base_url") or "").rstrip("/")
        model_name = cfg.get("model_name") or ""
        # DeepSeek 官方端点必须走 ChatDeepSeek：langchain_openai 的 ChatOpenAI 是通用
        # OpenAI 客户端，流式时会丢弃 delta.reasoning_content，导致 Planner/SubAgent
        # 的思考内容（thinking 事件）为空。ChatDeepSeek 会把 reasoning_content 放入
        # additional_kwargs，前端才能正常显示"正在分析任务…"的真实推理过程。
        if "api.deepseek.com" in base_url:
            from langchain_deepseek import ChatDeepSeek
            return ChatDeepSeek(
                model=model_name,
                api_key=cfg["api_key"],
                api_base=base_url,
                max_tokens=4096,
                temperature=0.7,
                request_timeout=240,
                max_retries=1,
            )
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model_name,
            api_key=cfg["api_key"],
            base_url=base_url,
            timeout=120,
            max_retries=1,
        )
    except Exception:
        return chat_model


