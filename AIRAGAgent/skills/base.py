"""
Skill 基类与注册中心
"""
from __future__ import annotations
from typing import List, Callable, Dict, Optional
from dataclasses import dataclass, field

from AIRAGAgent.utils.logger_handler import logger


@dataclass
class Skill:
    """
    领域能力包。
    封装一组相关的工具 + 领域专属 system prompt，统一激活/注销。
    """
    name: str                                    # skill 唯一标识，如 "weather"
    description: str                             # 给 Supervisor 看的简短描述（选 skill 时用）
    tools: List[Callable] = field(default_factory=list)
    system_prompt: str = ""                       # 激活后注入 worker 的领域 prompt
    workflow_hint: str = ""                       # 工具调用顺序提示，如 "get_user_location → get_city_code → get_weather"

    def __hash__(self):
        """以skill名称计算哈希值。"""
        return hash(self.name)


class SkillRegistry:
    """
    技能注册中心，管理所有 Skill 的生命周期。
    单例模式，全局共享。
    """
    _instance: Optional["SkillRegistry"] = None

    def __new__(cls):
        """单例模式：保证全局只存在一个技能注册中心实例。"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._skills: Dict[str, Skill] = {}
            cls._instance._active_skills: Dict[str, Skill] = {}
            cls._instance._initialized = False
        return cls._instance

    def register(self, skill: Skill):
        """注册一个 Skill"""
        self._skills[skill.name] = skill
        logger.info(f"[SkillRegistry] 注册 skill: {skill.name}（含 {len(skill.tools)} 个工具）")

    def get_all_descriptions(self) -> str:
        """生成给 Supervisor 的 Skill 选择菜单（仅含简短描述，不泄露实现细节）"""
        lines = ["## 可用技能清单"]
        for i, (name, skill) in enumerate(self._skills.items(), 1):
            lines.append(f"{i}. **{name}**：{skill.description}")
            if skill.workflow_hint:
                lines.append(f"   调用流程：{skill.workflow_hint}")
        return "\n".join(lines)

    def get_skill(self, name: str) -> Optional[Skill]:
        """按名称获取已注册的 Skill，不存在返回 None。"""
        return self._skills.get(name)

    def get_all_skills(self) -> Dict[str, Skill]:
        """返回所有已注册Skill的字典副本。"""
        return dict(self._skills)

    def get_all_tools(self) -> List[Callable]:
        """获取所有 Skill 中的所有工具（供 LangChain agent 注册）"""
        all_tools = []
        seen_names = set()
        for skill in self._skills.values():
            for tool in skill.tools:
                if tool.name not in seen_names:
                    all_tools.append(tool)
                    seen_names.add(tool.name)
        return all_tools

    def activate(self, skill_name: str) -> Optional[str]:
        """
        激活一个 Skill，返回其 system_prompt。
        激活后会将此 skill 的详细 prompt 注入到后续对话中。
        """
        skill = self._skills.get(skill_name)
        if not skill:
            logger.warning(f"[SkillRegistry] 尝试激活不存在的 skill: {skill_name}")
            return None
        self._active_skills[skill_name] = skill
        logger.info(f"[SkillRegistry] 激活 skill: {skill_name}")
        return skill.system_prompt

    def deactivate_all(self):
        """清空所有已激活的 Skill。"""
        self._active_skills.clear()

    def is_active(self, skill_name: str) -> bool:
        """判断指定名称的Skill当前是否处于激活状态。"""
        return skill_name in self._active_skills

    def get_active_prompts(self) -> str:
        """获取所有已激活 Skill 的 system_prompt 拼接"""
        if not self._active_skills:
            return ""
        prompts = []
        for name, skill in self._active_skills.items():
            if skill.system_prompt:
                prompts.append(f"<!-- 已激活技能 [{name}] -->\n{skill.system_prompt}")
        return "\n\n---\n\n".join(prompts)

    def find_skill_by_tool(self, tool_name: str) -> Optional[Skill]:
        """根据工具名反查所属 Skill"""
        for skill in self._skills.values():
            for t in skill.tools:
                if t.name == tool_name:
                    return skill
        return None
