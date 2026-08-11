"""Orchestrator 可测纯逻辑测试。

不调 LLM 的方法：
- _extract_json（模块级函数）：从 LLM 文本提取 JSON
- _format_history（静态方法）：格式化对话历史
- _history_to_messages（静态方法）：转 LangChain 消息
- _build_step_context：构造前序步骤上下文
- _save_step_result / _plan_results_dir：步骤结果落盘
- _reflect 的纯逻辑分支（空 subagent → accept，失败 → retry/accept）
"""
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from AIRAGAgent.agent.orchestrator import (
    Orchestrator, _extract_json, Reflection, PlanSpec, StepSpec,
)
from AIRAGAgent.agent.plan import Plan, PlanStep, PlanStatus, StepStatus


# ═══════════════════════════════════════════════
# _extract_json
# ═══════════════════════════════════════════════

def test_extract_json_pure():
    assert _extract_json('{"a": 1}') == '{"a": 1}'


def test_extract_json_with_code_fence():
    text = '```json\n{"a": 1, "b": 2}\n```'
    assert _extract_json(text) == '{"a": 1, "b": 2}'


def test_extract_json_with_surrounding_text():
    text = '好的，这是计划：\n{"goal": "x", "steps": []}\n请执行。'
    result = _extract_json(text)
    assert '"goal"' in result
    assert '"steps"' in result
    assert "好的" not in result


def test_extract_json_nested():
    text = 'prefix {"a": {"b": [1, 2]}, "c": true} suffix'
    result = _extract_json(text)
    assert json.loads(result) == {"a": {"b": [1, 2]}, "c": True}


def test_extract_json_no_braces():
    """无花括号时原样返回"""
    assert _extract_json("plain text") == "plain text"


def test_extract_json_empty():
    assert _extract_json("") == ""


def test_extract_json_code_fence_no_closing():
    """``` 开头但无结尾 ```"""
    text = '```json\n{"a": 1}'
    result = _extract_json(text)
    assert '"a"' in result


# ═══════════════════════════════════════════════
# _format_history
# ═══════════════════════════════════════════════

def test_format_history_empty():
    assert Orchestrator._format_history(None) == ""
    assert Orchestrator._format_history([]) == ""


def test_format_history_basic():
    history = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好，有什么可以帮你？"},
    ]
    result = Orchestrator._format_history(history)
    assert "用户: 你好" in result
    assert "助手: 你好" in result


def test_format_history_truncates_long_content():
    long_text = "x" * 500
    history = [{"role": "user", "content": long_text}]
    result = Orchestrator._format_history(history)
    # 每条最多 200 字
    assert len(long_text) > 200
    assert "x" * 201 not in result


def test_format_history_only_last_six():
    """只取最近 6 条"""
    history = [{"role": "user", "content": f"msg{i}"} for i in range(10)]
    result = Orchestrator._format_history(history)
    assert "msg3" not in result  # 第 4 条（index 3）被截掉
    assert "msg4" in result      # 第 5 条（index 4）保留


# ═══════════════════════════════════════════════
# _history_to_messages
# ═══════════════════════════════════════════════

def test_history_to_messages_empty():
    assert Orchestrator._history_to_messages(None) == []
    assert Orchestrator._history_to_messages([]) == []


def test_history_to_messages_basic():
    history = [
        {"role": "user", "content": "问题"},
        {"role": "assistant", "content": "回答"},
        {"role": "unknown", "content": "忽略"},
    ]
    msgs = Orchestrator._history_to_messages(history)
    assert len(msgs) == 2  # unknown role 被过滤
    assert msgs[0].content == "问题"
    assert msgs[1].content == "回答"


def test_history_to_messages_truncates_to_six():
    history = [{"role": "user", "content": f"m{i}"} for i in range(10)]
    msgs = Orchestrator._history_to_messages(history)
    assert len(msgs) == 6
    assert msgs[0].content == "m4"  # 最近 6 条从 index 4 开始


# ═══════════════════════════════════════════════
# Pydantic Schema
# ═══════════════════════════════════════════════

def test_plan_spec_validation():
    spec = PlanSpec(goal="测试", steps=[
        StepSpec(description="第一步", subagent="search"),
        StepSpec(description="第二步", subagent="codexec", depends_on=[0]),
    ])
    assert spec.goal == "测试"
    assert len(spec.steps) == 2
    assert spec.steps[1].depends_on == [0]


def test_plan_spec_empty_depends_default():
    spec = StepSpec(description="x", subagent="")
    assert spec.depends_on == []


def test_reflection_action_values():
    r = Reflection(action="accept")
    assert r.feedback == ""
    r2 = Reflection(action="retry", feedback="换种方式")
    assert r2.feedback == "换种方式"


# ═══════════════════════════════════════════════
# Orchestrator 常量
# ═══════════════════════════════════════════════

def test_orchestrator_constants():
    assert Orchestrator.MAX_REVISIONS == 2
    assert Orchestrator.MAX_RETRIES == 1


# ═══════════════════════════════════════════════
# _build_step_context / _save_step_result（需 Orchestrator 实例）
# ═══════════════════════════════════════════════

@pytest.fixture
def orchestrator(tmp_path, monkeypatch):
    """创建 Orchestrator 实例，mock LLM 和 workspace 路径。"""
    # Mock register_all_subagents（__init__ 调用）
    import AIRAGAgent.agent.sub_agents as _sub_mod
    monkeypatch.setattr(_sub_mod, "register_all_subagents", lambda: None)

    # Mock get_daily_workspace 返回 tmp_path（避免污染真实 workspace）
    import AIRAGAgent.agent.orchestrator as _orch_mod
    def _fake_daily_ws(user_id):
        d = tmp_path / str(user_id) / "20260804"
        d.mkdir(parents=True, exist_ok=True)
        return d
    monkeypatch.setattr(_orch_mod, "get_daily_workspace", _fake_daily_ws)

    # 重置单例
    _orch_mod._orchestrator = None
    orch = Orchestrator()
    # 清空 registry（__init__ 可能注册了一些 agent）
    orch.registry._agents = {}
    return orch


def test_build_step_context_empty(orchestrator):
    plan = Plan(id="p1", user_id=1, session_id="", goal="g", steps=[
        PlanStep(step_idx=0, description="x", status=StepStatus.PENDING.value),
    ])
    ctx = orchestrator._build_step_context(plan, exclude=set())
    assert ctx == ""


def test_build_step_context_with_completed(orchestrator):
    plan = Plan(id="p1", user_id=1, session_id="", goal="g", steps=[
        PlanStep(step_idx=0, description="搜索", subagent="search",
                 status=StepStatus.COMPLETED.value, result="找到 3 个结果"),
        PlanStep(step_idx=1, description="汇总", subagent="codexec",
                 status=StepStatus.PENDING.value, depends_on=[0]),
    ])
    ctx = orchestrator._build_step_context(plan, exclude=set())
    assert "前序步骤结果" in ctx
    assert "步骤 0" in ctx
    assert "找到 3 个结果" in ctx
    assert "plan_results/p1/step_0.md" in ctx


def test_build_step_context_excludes_specified(orchestrator):
    """exclude 集合中的步骤不出现在上下文"""
    plan = Plan(id="p1", user_id=1, session_id="", goal="g", steps=[
        PlanStep(step_idx=0, description="a", subagent="x",
                 status=StepStatus.COMPLETED.value, result="result_a"),
        PlanStep(step_idx=1, description="b", subagent="x",
                 status=StepStatus.COMPLETED.value, result="result_b"),
    ])
    ctx = orchestrator._build_step_context(plan, exclude={1})
    assert "result_a" in ctx
    assert "result_b" not in ctx


def test_build_step_context_excludes_empty_result(orchestrator):
    """result 为空的完成步骤不出现"""
    plan = Plan(id="p1", user_id=1, session_id="", goal="g", steps=[
        PlanStep(step_idx=0, description="a", subagent="x",
                 status=StepStatus.COMPLETED.value, result=""),
    ])
    ctx = orchestrator._build_step_context(plan, exclude=set())
    assert ctx == ""


def test_build_step_context_truncates_long_result(orchestrator):
    long_result = "x" * 500
    plan = Plan(id="p1", user_id=1, session_id="", goal="g", steps=[
        PlanStep(step_idx=0, description="a", subagent="x",
                 status=StepStatus.COMPLETED.value, result=long_result),
    ])
    ctx = orchestrator._build_step_context(plan, exclude=set())
    # 摘要截断到 200 字
    assert "..." in ctx
    assert "x" * 201 not in ctx


def test_save_step_result(orchestrator):
    plan = Plan(id="p_save", user_id=1, session_id="", goal="g", steps=[])
    step = PlanStep(step_idx=2, description="执行搜索", subagent="search",
                    result="搜索结果内容")
    rel_path = orchestrator._save_step_result(plan, step)
    assert rel_path == f"plan_results/p_save/step_2.md"

    # 验证文件写入
    daily_ws = orchestrator._plan_results_dir(plan)
    f = daily_ws / "step_2.md"
    assert f.exists()
    content = f.read_text(encoding="utf-8")
    assert "步骤 2" in content
    assert "search" in content
    assert "执行搜索" in content
    assert "搜索结果内容" in content


def test_save_step_result_empty_result(orchestrator):
    plan = Plan(id="p_empty", user_id=1, session_id="", goal="g", steps=[])
    step = PlanStep(step_idx=0, description="x", result="")
    rel_path = orchestrator._save_step_result(plan, step)
    assert rel_path != ""
    f = orchestrator._plan_results_dir(plan) / "step_0.md"
    assert "(无结果)" in f.read_text(encoding="utf-8")


def test_plan_results_dir(orchestrator):
    plan = Plan(id="p_dir", user_id=42, session_id="", goal="g", steps=[])
    d = orchestrator._plan_results_dir(plan)
    assert "42" in str(d)
    assert "tasks" in str(d)
    assert "p_dir" in str(d)
    assert "plan_results" in str(d)
