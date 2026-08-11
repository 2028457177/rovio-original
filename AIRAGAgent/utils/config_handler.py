import os

import yaml

from AIRAGAgent.utils.path_tool import get_abs_path

# 加载rag配置文件
def load_rag_config(config_path: str=get_abs_path("config/rag.yml"),encoding: str="utf-8"):
    with open(config_path, "r" ,encoding=encoding) as f:
        return yaml.load(f, Loader=yaml.FullLoader)

# 加载chroma配置文件
def load_chroma_config(config_path: str = get_abs_path("config/chroma.yml"), encoding: str = "utf-8"):
    with open(config_path, "r", encoding=encoding) as f:
        return yaml.load(f, Loader=yaml.FullLoader)

# 加载提示词配置文件
def load_prompts_config(config_path: str = get_abs_path("config/prompts.yml"), encoding: str = "utf-8"):
    with open(config_path, "r", encoding=encoding) as f:
        return yaml.load(f, Loader=yaml.FullLoader)

# 加载智能体配置文件
def load_agent_config(config_path: str = get_abs_path("config/agent.yml"), encoding: str = "utf-8"):
    with open(config_path, "r", encoding=encoding) as f:
        return yaml.load(f, Loader=yaml.FullLoader)


# 加载MySQL配置文件
def load_mysql_config(config_path: str = get_abs_path("config/mysql.yml"), encoding: str = "utf-8"):
    with open(config_path, "r", encoding=encoding) as f:
        return yaml.load(f, Loader=yaml.FullLoader)


# 加载Redis配置文件
def load_redis_config(config_path: str = get_abs_path("config/redis.yml"), encoding: str = "utf-8"):
    with open(config_path, "r", encoding=encoding) as f:
        return yaml.load(f, Loader=yaml.FullLoader)


# 加载长期记忆配置文件
def load_memory_config(config_path: str = get_abs_path("config/memory.yml"), encoding: str = "utf-8"):
    with open(config_path, "r", encoding=encoding) as f:
        return yaml.load(f, Loader=yaml.FullLoader)


rag_conf = load_rag_config()
chroma_conf = load_chroma_config()
prompts_conf = load_prompts_config()
agent_conf = load_agent_config()
mysql_conf = load_mysql_config()
redis_conf = load_redis_config()
memory_conf = load_memory_config()

# 敏感凭证优先从环境变量读取（由 .env 注入进程环境），YAML 中仅保留空占位。
# 这样密钥不再进入 git 跟踪的配置文件，避免历史泄露。
rag_conf["api_key"] = os.getenv("DEEPSEEK_API_KEY") or rag_conf.get("api_key", "")
rag_conf["embedding_api_key"] = os.getenv("EMBEDDING_API_KEY") or rag_conf.get("embedding_api_key", "")
rag_conf["tavily_api_key"] = os.getenv("TAVILY_API_KEY") or rag_conf.get("tavily_api_key", "")
rag_conf["gaode_api_key"] = os.getenv("GAODE_API_KEY") or rag_conf.get("gaode_api_key", "")
chroma_conf["openai_api_key"] = os.getenv("OPENAI_EMBEDDING_API_KEY") or chroma_conf.get("openai_api_key", "")
mysql_conf["password"] = os.getenv("MYSQL_PASSWORD") or mysql_conf.get("password", "")

if __name__ == '__main__':
    print(rag_conf["chat_model_name"])