"""
总结服务类:用户提问，搜索参考资料，将提问和参考资料提交给模型，让模型总结回复

检索数据源为多知识库系统（AIRAGAgent.kb）：
- 全局启用知识库对所有人可见；
- 个人知识库仅对属主可见（通过请求级 user_id ContextVar 解析）；
- 缓存键包含用户与知识库签名，避免跨用户/跨库脏读。
"""
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from AIRAGAgent.utils.prompt_loader import load_rag_prompts
from langchain_core.prompts import PromptTemplate
from AIRAGAgent.model.factory import chat_model, get_user_chat_model
from AIRAGAgent.utils.config_handler import chroma_conf
from AIRAGAgent.infrastructure.rag_cache import get_cached_rag_result, cache_rag_result


def print_prompt(prompt):
    # 打印提示词
    print("="*50)
    print(prompt.to_string())
    print("="*50)
    return prompt


def _current_user_id() -> int | None:
    """从请求上下文解析当前用户 ID（非 Web 请求场景返回 None）。

    懒导入避免与 agent_tools 循环依赖。
    """
    try:
        from AIRAGAgent.agent.tools.agent_tools import user_id_var
        return user_id_var.get()
    except Exception:
        return None


# 总结服务类
class RagSummarizeService(object):
    def __init__(self):
        """初始化总结服务：加载提示词模板、默认聊天模型并构建处理链。"""
        self.prompt_text = load_rag_prompts()    # 加载提示词
        self.prompt_template = PromptTemplate.from_template(self.prompt_text)    # 提示词模板
        self.model = chat_model    # 聊天模型
        self.chain = self._init_chain()    # 初始化链

    # 初始化链
    def _init_chain(self):
        chian = self.prompt_template | print_prompt | self.model | StrOutputParser()
        return chian

    # 检索文档
    def retrieve_doce(self, query: str) -> list[Document]:
        from AIRAGAgent.kb import models as kb_models
        from AIRAGAgent.kb import service as kb_service

        user_id = _current_user_id()
        kb_ids = kb_models.list_accessible_kb_ids(user_id)
        if not kb_ids:
            return []

        # 缓存键：用户 + 知识库集合签名 + 查询，保证多库/个人库隔离
        sig = ",".join(map(str, kb_ids))
        cache_query = f"u{user_id or 0}|k{sig}|{query}"

        cached = get_cached_rag_result(cache_query)
        if cached is not None:
            return [
                Document(page_content=item.get("content", ""), metadata=item.get("metadata", {}))
                for item in cached
            ]

        docs = kb_service.search(query, kb_ids, top_k=int(chroma_conf.get("k", 3)))

        cache_rag_result(cache_query, [
            {"content": doc.page_content, "metadata": doc.metadata} for doc in docs
        ])
        return docs

    # 总结回复
    def rag_summarize(self, query: str) -> str:
        context_docs = self.retrieve_doce(query)
        context = ""
        counter = 0
        # 遍历文档，将文档内容和元数据拼接起来
        for doc in context_docs:
            counter += 1
            context += f"【参考资料{counter}】: 参考资料:{doc.page_content}| 参考元数据:{doc.metadata}\n"
        # 按当前用户解析对话模型（用户自配 OpenAI 兼容模型优先，否则系统默认）
        user_id = _current_user_id()
        model = get_user_chat_model(user_id)
        chain = self.prompt_template | print_prompt | model | StrOutputParser()
        return chain.invoke(
            {
                    "input": query,
                    "context": context,
            }
        )


if __name__ == '__main__':
    rag = RagSummarizeService()

    print(rag.rag_summarize("如何提升办公效率"))
