"""SubAgent 基类与注册中心。

SubAgent 是 DeepAgent 架构中的执行单元：
- 每个 SubAgent 封装一组相关工具 + 领域 system prompt + 独立 agent 实例
- 由 Orchestrator 调度，输入任务描述，输出执行结果 + 思考过程
- 支持流式输出（thinking / output 分离，与旧 ReactAgent 协议一致）
- 线程安全：每个并行任务用 create_standalone 创建独立实例

替代旧的 Skill 体系（AIRAGAgent/skills/*），但保留兼容层。
"""
from __future__ import annotations

from typing import List, Callable, Dict, Optional, Generator, Any
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
import contextvars

from langchain.agents import create_agent
from langchain.agents.middleware.tool_call_limit import ToolCallLimitMiddleware
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, AIMessageChunk, ToolMessage

from AIRAGAgent.model.factory import chat_model
from AIRAGAgent.utils.logger_handler import logger
from AIRAGAgent.utils.prompt_loader import load_identity_prompts
from AIRAGAgent.agent.tools.middleware import skill_aware_monitor, log_before_model, smart_prompt_switch


# ═══════════════════════════════════════════════
# SubAgent 定义
# ═══════════════════════════════════════════════

@dataclass
class SubAgent:
    """领域子智能体。

    Attributes:
        name: 唯一标识，如 "weather" / "codexec"
        description: 给 Orchestrator Planner 看的简短描述（选 subagent 时用）
        tools: 该 SubAgent 拥有的 langchain @tool 列表
        system_prompt: 激活后注入的领域 prompt（指导如何使用这些工具）
        workflow_hint: 工具调用顺序提示，如 "get_user_location → get_city_code → get_weather"
        max_tool_calls: 单次执行最大工具调用次数
        category: 分类（builtin/domain/memory/artifact/system），用于权限管控和前端展示
    """
    name: str
    description: str
    tools: List[Callable] = field(default_factory=list)
    system_prompt: str = ""
    workflow_hint: str = ""
    max_tool_calls: int = 20
    category: str = "domain"   # builtin / domain / memory / artifact / system

    def __hash__(self):
        """按名称计算哈希，保证 SubAgent 可作字典键。"""
        return hash(self.name)

    def build_agent(self, llm=None):
        """构建一个独立的 LangChain agent 实例（线程安全，每次调用新建）。

        Args:
            llm: 对话模型；缺省用系统默认模型（chat_model）。
        """
        identity = load_identity_prompts()
        full_prompt = identity + ("\n\n---\n\n" + self.system_prompt if self.system_prompt else "")

        return create_agent(
            model=llm or chat_model,
            system_prompt=full_prompt,
            tools=self.tools,
            middleware=[
                ToolCallLimitMiddleware(run_limit=self.max_tool_calls, exit_behavior="end"),
                skill_aware_monitor,
                log_before_model,
                smart_prompt_switch,
            ],
        )


# ═══════════════════════════════════════════════
# 执行器：把 SubAgent 当作可调用单元
# ═══════════════════════════════════════════════

class SubAgentRunner:
    """执行单个 SubAgent 的任务，流式产出 thinking / output。

    协议与旧 ReactAgent.execute_stream 完全一致，方便上层无缝替换：
        yield {"type": "thinking",  "content": "..."}
        yield {"type": "thinking_end", "content": ""}
        yield {"type": "output",    "content": "..."}
    """

    def __init__(self, sub_agent: SubAgent, llm=None):
        """初始化执行器：保存 SubAgent 并构建独立的 agent 实例。"""
        self.sub_agent = sub_agent
        # 每次执行都用独立 agent 实例，避免并行 stream 互相干扰；
        # llm 缺省用系统默认模型（chat_model）
        self._agent = sub_agent.build_agent(llm=llm)

    @staticmethod
    def _history_to_messages(chat_history: Optional[List[Dict[str, str]]]) -> list:
        """把聊天历史（角色+内容字典列表）转成 LangChain 消息列表。"""
        if not chat_history:
            return []
        messages = []
        for entry in chat_history:
            role = entry.get("role", "")
            content = entry.get("content", "")
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))
        return messages

    def execute_stream(self, query: str, chat_history: Optional[List[Dict[str, str]]] = None,
                       context: Optional[dict] = None) -> Generator[dict, None, None]:
        """流式执行 SubAgent 任务。

        Args:
            query: 任务描述（来自 PlanStep.description）
            chat_history: 当前会话历史（让 SubAgent 能引用上文）
            context: runtime context，影响 smart_prompt_switch 等 middleware
                     会自动注入 active_skills=[self.sub_agent.name]
        """
        history_messages = self._history_to_messages(chat_history)
        input_messages = history_messages + [HumanMessage(content=query)]
        input_dict = {"messages": input_messages}

        # 注入 runtime context：标记当前激活的 subagent，smart_prompt_switch 会注入对应 prompt
        runtime_context = dict(context or {})
        runtime_context.setdefault("active_skills", [self.sub_agent.name])
        runtime_context.setdefault("report", False)

        seen_tool_ids = set()
        reported_tool_results = set()
        has_entered_tool_phase = False
        any_tools_called = False
        last_tool_results: Dict[str, str] = {}
        has_user_output = False

        try:
            stream = self._agent.stream(
                input_dict,
                stream_mode="messages",
                subgraphs=False,
                context=runtime_context,
                config={"recursion_limit": 50},
            )
        except TypeError:
            # 兼容不支持 context 参数的 langchain 版本
            stream = self._agent.stream(
                input_dict,
                stream_mode="messages",
                subgraphs=False,
                config={"recursion_limit": 50},
            )

        for msg, _meta in stream:
            if isinstance(msg, AIMessageChunk):
                has_tool_calls = bool(getattr(msg, 'tool_calls', None))
                if has_tool_calls:
                    any_tools_called = True
                    for tc in msg.tool_calls:
                        tc_id = tc.get("id", "")
                        tc_name = tc.get("name", "")
                        if tc_id and tc_name and tc_id not in seen_tool_ids:
                            seen_tool_ids.add(tc_id)
                            has_entered_tool_phase = True
                            yield {"type": "thinking", "content": f"\n[{self.sub_agent.name}] 调用工具: {tc_name}\n"}

                output_text = msg.content or ""
                reasoning = (getattr(msg, 'additional_kwargs', None) or {}).get('reasoning_content', '')

                if reasoning and not output_text:
                    yield {"type": "thinking", "content": reasoning}
                else:
                    if not output_text and reasoning:
                        output_text = reasoning

                if output_text:
                    if has_entered_tool_phase:
                        yield {"type": "thinking_end", "content": ""}
                        has_entered_tool_phase = False
                    has_user_output = True
                    yield {"type": "output", "content": output_text}

            elif isinstance(msg, ToolMessage):
                tool_name = getattr(msg, 'name', '未知工具')
                last_tool_results[tool_name] = str(msg.content)
                if tool_name not in reported_tool_results:
                    reported_tool_results.add(tool_name)
                    yield {"type": "thinking", "content": f"\n[{self.sub_agent.name}] 工具 [{tool_name}] 完成\n"}

        # 兜底：调用了工具但没有面向用户的输出
        if any_tools_called and not has_user_output and last_tool_results:
            fallback_parts = []
            for tname, tresult in last_tool_results.items():
                fallback_parts.append(f"**{tname} 结果**：\n{tresult}\n")
            yield {"type": "output", "content": "\n\n---\n" + "\n".join(fallback_parts)}

    def execute(self, query: str, chat_history: Optional[List[Dict[str, str]]] = None,
                context: Optional[dict] = None) -> str:
        """同步执行，收集所有 output 拼接返回（用于并行任务、不需要流式时）。"""
        parts = []
        for chunk in self.execute_stream(query, chat_history, context):
            if isinstance(chunk, dict) and chunk.get("type") == "output":
                parts.append(chunk.get("content", ""))
        return "".join(parts)


# ═══════════════════════════════════════════════
# 注册中心
# ═══════════════════════════════════════════════

class SubAgentRegistry:
    """SubAgent 注册中心，单例，全局共享。

    取代旧的 SkillRegistry，但保留对 SkillRegistry 的兼容访问。
    """
    _instance: Optional["SubAgentRegistry"] = None

    def __new__(cls):
        """单例模式：保证全局只存在一个注册中心实例。"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._agents: Dict[str, SubAgent] = {}
            cls._instance._initialized = False
        return cls._instance

    def register(self, agent: SubAgent) -> None:
        """注册一个 SubAgent，并按名称存进注册表。"""
        self._agents[agent.name] = agent
        logger.info(f"[SubAgentRegistry] 注册 subagent: {agent.name}（含 {len(agent.tools)} 个工具，category={agent.category}）")

    def get(self, name: str) -> Optional[SubAgent]:
        """按名称获取 SubAgent，不存在时返回 None。"""
        return self._agents.get(name)

    def all(self) -> Dict[str, SubAgent]:
        """返回全部已注册 SubAgent 的字典副本。"""
        return dict(self._agents)

    def by_category(self, category: str) -> Dict[str, SubAgent]:
        """按分类筛选出对应类别的 SubAgent 字典。"""
        return {n: a for n, a in self._agents.items() if a.category == category}

    def descriptions_for_planner(self, exclude: Optional[set] = None) -> str:
        """生成给 Planner 看的 SubAgent 选择菜单（仅 name + description + workflow）。

        Args:
            exclude: 需要从菜单中排除的 subagent name 集合（如关闭联网搜索时排除 "search"）。
        """
        exclude = exclude or set()
        lines = ["## 可用 SubAgent 清单（选择 step.subagent 时只能用以下 name）"]
        for name, agent in self._agents.items():
            if name in exclude:
                continue
            lines.append(f"- **{name}**：{agent.description}")
            if agent.workflow_hint:
                lines.append(f"  - 调用流程：{agent.workflow_hint}")
        return "\n".join(lines)

    def find_by_tool(self, tool_name: str) -> Optional[SubAgent]:
        """根据工具名反查拥有该工具的 SubAgent，未找到时返回 None。"""
        for agent in self._agents.values():
            for t in agent.tools:
                if getattr(t, "name", None) == tool_name:
                    return agent
        return None

    def get_all_tools(self) -> List[Callable]:
        """聚合所有 SubAgent 的工具（用于兼容旧的 agent 创建路径）。"""
        all_tools = []
        seen = set()
        for agent in self._agents.values():
            for t in agent.tools:
                name = getattr(t, "name", None)
                if name and name not in seen:
                    all_tools.append(t)
                    seen.add(name)
        return all_tools


# ═══════════════════════════════════════════════
# 并行执行器（保留旧 SupervisorAgent 的并行能力）
# ═══════════════════════════════════════════════

def run_steps_parallel(
    step_specs: List[Dict[str, Any]],
    chat_history: Optional[List[Dict[str, str]]] = None,
    max_workers: int = 5,
    llm=None,
) -> List[Dict[str, Any]]:
    """并行执行多个 SubAgent 任务。

    Args:
        step_specs: [{"step_idx": int, "subagent": str, "description": str}, ...]
        chat_history: 会话历史（每个 worker 共享只读）
        max_workers: 最大并行数
        llm: 对话模型；缺省用系统默认模型（chat_model）

    Returns:
        [{"step_idx": int, "subagent": str, "result": str, "success": bool, "thinking": [chunks]}, ...]
        按 step_idx 排序
    """
    registry = SubAgentRegistry()
    # 捕获当前 contextvars 快照（含 user_id/ip/lat/lon/plan_id 等）
    # 注意：Context 对象非线程安全，不能多线程共享同一个 Context.run()，
    # 每个 worker 必须复制自己的副本。
    parent_ctx = contextvars.copy_context()
    results: List[Dict[str, Any]] = []

    def _run_one(spec):
        """执行单个并行步骤：查找 SubAgent 并在独立 context 副本中流式跑完，返回结果。"""
        idx = spec["step_idx"]
        sub_name = spec["subagent"]
        desc = spec["description"]
        sub = registry.get(sub_name)
        if sub is None:
            return {"step_idx": idx, "subagent": sub_name, "result": f"[未知 SubAgent: {sub_name}]",
                    "success": False, "thinking": []}
        runner = SubAgentRunner(sub, llm=llm)
        thinking_chunks = []
        output_parts = []
        try:
            def _inner():
                """在独立的 context 副本中流式消费 SubAgent 输出并分类收集。"""
                for chunk in runner.execute_stream(desc, chat_history):
                    if isinstance(chunk, dict):
                        if chunk.get("type") == "output":
                            output_parts.append(chunk.get("content", ""))
                        else:
                            thinking_chunks.append(chunk)
            # 每个 worker 用独立的 context 副本运行，避免 "already entered" 错误
            child_ctx = parent_ctx.copy()
            child_ctx.run(_inner)
            result = "".join(output_parts)
            logger.info(f"[Parallel] step={idx} subagent={sub_name} 完成，结果长度={len(result)}")
            return {"step_idx": idx, "subagent": sub_name, "result": result,
                    "success": True, "thinking": thinking_chunks}
        except Exception as e:
            logger.error(f"[Parallel] step={idx} subagent={sub_name} 失败: {e}")
            return {"step_idx": idx, "subagent": sub_name, "result": f"[执行失败: {e}]",
                    "success": False, "thinking": thinking_chunks}

    with ThreadPoolExecutor(max_workers=min(max_workers, len(step_specs) or 1)) as executor:
        futures = {executor.submit(_run_one, spec): spec for spec in step_specs}
        for fut in as_completed(futures):
            results.append(fut.result())

    results.sort(key=lambda x: x["step_idx"])
    return results
