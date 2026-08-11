import re
from AIRAGAgent.utils.config_handler import prompts_conf
from AIRAGAgent.utils.path_tool import get_abs_path
from AIRAGAgent.utils.logger_handler import logger

# 加载系统提示词（完整版，含工具描述，保留向后兼容）
def load_system_prompts():
    try:
        system_prompt_path = get_abs_path(prompts_conf["main_prompt_path"])
    except KeyError as e:
        logger.error(f"load_system_prompts]在yaml配置项中没有main_prompt_path配置项")
        raise e

    try:
        return open(system_prompt_path, "r", encoding="utf-8").read()
    except Exception as e:
        logger.error(f"load_system_prompts]解析系统提示词出错，{str(e)}")
        raise e

# 加载身份提示词（仅含角色定义、思考准则、输出规则、工具概览）
def load_identity_prompts():
    try:
        identity_prompt_path = get_abs_path(prompts_conf["identity_prompt_path"])
    except KeyError as e:
        logger.error(f"load_identity_prompts]在yaml配置项中没有identity_prompt_path配置项")
        raise e

    try:
        return open(identity_prompt_path, "r", encoding="utf-8").read()
    except Exception as e:
        logger.error(f"load_identity_prompts]解析身份提示词出错，{str(e)}")
        raise e

# 加载工具提示词文件原始内容（含所有工具的详细描述）
def _load_tools_prompt_raw():
    try:
        tools_prompt_path = get_abs_path(prompts_conf["tools_prompt_path"])
    except KeyError as e:
        logger.error(f"_load_tools_prompt_raw]在yaml配置项中没有tools_prompt_path配置项")
        raise e

    try:
        return open(tools_prompt_path, "r", encoding="utf-8").read()
    except Exception as e:
        logger.error(f"_load_tools_prompt_raw]解析工具提示词出错，{str(e)}")
        raise e

# 根据工具名称列表，从tools_prompt.txt中提取对应工具的详细描述
def load_tool_details(tool_names: list[str]) -> str:
    raw_text = _load_tools_prompt_raw()
    if not tool_names:
        return ""

    sections = {}
    # 按 ### tool_name 分割各工具的详细描述
    pattern = r'### (\w+)\n(.*?)(?=\n### \w+\n|\Z)'
    for match in re.finditer(pattern, raw_text, re.DOTALL):
        sections[match.group(1)] = match.group(2).strip()

    result_parts = []
    for name in tool_names:
        if name in sections:
            result_parts.append(f"### {name}\n{sections[name]}")
        else:
            logger.warning(f"[load_tool_details] 工具 '{name}' 在tools_prompt.txt中未找到对应描述")

    return "\n\n".join(result_parts)


def load_all_tool_details() -> str:
    """加载工具提示词文件中全部工具的详细描述并拼接后返回。"""
    raw_text = _load_tools_prompt_raw()
    sections = {}
    pattern = r'### (\w+)\n(.*?)(?=\n### \w+\n|\Z)'
    for match in re.finditer(pattern, raw_text, re.DOTALL):
        sections[match.group(1)] = match.group(2).strip()

    result_parts = []
    for name, desc in sections.items():
        result_parts.append(f"### {name}\n{desc}")

    return "\n\n".join(result_parts)

# 加载RAG总结提示词
def load_rag_prompts():
    try:
        rag_prompt_path = get_abs_path(prompts_conf["rag_summarize_prompt_path"])
    except KeyError as e:
        logger.error(f"load_rag_prompts]在yaml配置项中没有rag_summarize_prompt_path配置项")
        raise e

    try:
        return open(rag_prompt_path, "r", encoding="utf-8").read()
    except Exception as e:
        logger.error(f"load_rag_prompts]解析RAG总结提示词出错，{str(e)}")
        raise e

# 加载报告生成提示词
def load_report_prompts():
    try:
        report_prompt_path = get_abs_path(prompts_conf["report_prompt_path"])
    except KeyError as e:
        logger.error(f"load_report_prompt]在yaml配置项中没有report_prompt_path配置项")
        raise e

    try:
        return open(report_prompt_path, "r", encoding="utf-8").read()
    except Exception as e:
        logger.error(f"load_report_prompt]解析报告生成提示词出错，{str(e)}")
        raise e



if __name__ == '__main__':
    print(load_rag_prompts())

