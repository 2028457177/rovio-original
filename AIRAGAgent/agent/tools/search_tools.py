from langchain_core.tools import tool
from langchain_community.tools.tavily_search import TavilySearchResults
from AIRAGAgent.utils.config_handler import rag_conf

search_tool = TavilySearchResults(
    tavily_api_key=rag_conf.get("tavily_api_key", ""),
    max_results = 1,
    topic = "general",
    search_depth = "basic",
    include_raw_content = False,
    include_answer = True,
    include_images = False
)

@tool(description="根据用户需求联网搜索相应内容")
def search(content:str):
    """根据用户需求联网搜索，返回搜索结果列表。"""
    result = search_tool.invoke(content)
    return result


if __name__ == '__main__':
    print(search("老弟的压压是什么梗"))
