"""AIRAGAgent.agent.plan 纯逻辑测试。

覆盖：
- PlanStep / Plan dataclass 序列化
- 依赖解析：get_ready_steps（并行 / 串行 / 阻塞）
- 状态判断：is_all_done / has_failure
- 持久化 CRUD：create_plan / load_plan / update_step_status / replace_plan_steps / update_plan_status / list_user_plans
"""
import time

import pytest

from AIRAGAgent.agent.plan import (
    Plan, PlanStep, PlanStatus, StepStatus,
    create_plan, load_plan, update_step_status, replace_plan_steps,
    update_plan_status, list_user_plans, get_session_plan,
)


# ═══════════════════════════════════════════════
# Dataclass 序列化
# ═══════════════════════════════════════════════

def test_plan_step_to_dict():
    step = PlanStep(step_idx=0, description="搜索", subagent="search", depends_on=[])
    d = step.to_dict()
    assert d["step_idx"] == 0
    assert d["description"] == "搜索"
    assert d["subagent"] == "search"
    assert d["status"] == StepStatus.PENDING.value
    assert d["depends_on"] == []
    assert d["result"] == ""
    assert d["attempts"] == 0


def test_plan_to_dict():
    plan = Plan(
        id="p1", user_id=1, session_id="s1", goal="测试目标",
        steps=[PlanStep(step_idx=0, description="步骤1")],
    )
    d = plan.to_dict()
    assert d["id"] == "p1"
    assert d["user_id"] == 1
    assert d["goal"] == "测试目标"
    assert d["status"] == PlanStatus.PLANNING.value
    assert len(d["steps"]) == 1
    assert d["steps"][0]["step_idx"] == 0


def test_plan_step_from_row():
    """from_row 应正确解析 depends_on 字符串"""
    row = {
        "id": 10,
        "step_idx": 2,
        "description": "第三步",
        "subagent": "codexec",
        "depends_on": "0,1",
        "status": "pending",
        "result": "",
        "attempts": 0,
        "error_msg": "",
        "started_at": None,
        "finished_at": None,
    }
    step = PlanStep.from_row(row)
    assert step.step_idx == 2
    assert step.depends_on == [0, 1]
    assert step.subagent == "codexec"


def test_plan_step_from_row_empty_depends():
    row = {
        "id": 1, "step_idx": 0, "description": "x", "subagent": "",
        "depends_on": "", "status": "pending", "result": "",
        "attempts": 0, "error_msg": "",
        "started_at": None, "finished_at": None,
    }
    step = PlanStep.from_row(row)
    assert step.depends_on == []


def test_plan_step_from_row_invalid_depends():
    """非数字的 depends_on 应被忽略"""
    row = {
        "id": 1, "step_idx": 0, "description": "x", "subagent": "",
        "depends_on": "abc,xyz", "status": "pending", "result": "",
        "attempts": 0, "error_msg": "",
        "started_at": None, "finished_at": None,
    }
    step = PlanStep.from_row(row)
    assert step.depends_on == []


# ═══════════════════════════════════════════════
# 依赖解析：get_ready_steps
# ═══════════════════════════════════════════════

def test_get_ready_steps_all_independent():
    """3 个独立步骤全部 ready"""
    plan = Plan(id="p", user_id=1, session_id="", goal="g", steps=[
        PlanStep(step_idx=0, description="a"),
        PlanStep(step_idx=1, description="b"),
        PlanStep(step_idx=2, description="c"),
    ])
    ready = plan.get_ready_steps()
    assert len(ready) == 3
    assert {s.step_idx for s in ready} == {0, 1, 2}


def test_get_ready_steps_serial_dependency():
    """1→2→3 串行依赖：只有第一个 ready"""
    plan = Plan(id="p", user_id=1, session_id="", goal="g", steps=[
        PlanStep(step_idx=0, description="a"),
        PlanStep(step_idx=1, description="b", depends_on=[0]),
        PlanStep(step_idx=2, description="c", depends_on=[1]),
    ])
    ready = plan.get_ready_steps()
    assert len(ready) == 1
    assert ready[0].step_idx == 0


def test_get_ready_steps_partial_completion():
    """step 0 完成 → step 1, 2（依赖 0）变 ready"""
    plan = Plan(id="p", user_id=1, session_id="", goal="g", steps=[
        PlanStep(step_idx=0, description="a", status=StepStatus.COMPLETED.value),
        PlanStep(step_idx=1, description="b", depends_on=[0]),
        PlanStep(step_idx=2, description="c", depends_on=[0]),
    ])
    ready = plan.get_ready_steps()
    assert len(ready) == 2
    assert {s.step_idx for s in ready} == {1, 2}


def test_get_ready_steps_blocked_on_failure():
    """依赖步骤失败 → 标记 blocked"""
    plan = Plan(id="p", user_id=1, session_id="", goal="g", steps=[
        PlanStep(step_idx=0, description="a", status=StepStatus.FAILED.value),
        PlanStep(step_idx=1, description="b", depends_on=[0]),
    ])
    ready = plan.get_ready_steps()
    assert len(ready) == 0
    # step 1 应被标记为 blocked
    step1 = plan.get_step(1)
    assert step1.status == StepStatus.BLOCKED.value
    assert "失败" in step1.error_msg


def test_get_ready_steps_excludes_non_pending():
    """running / completed / skipped 等状态不出现在 ready 中"""
    plan = Plan(id="p", user_id=1, session_id="", goal="g", steps=[
        PlanStep(step_idx=0, description="a", status=StepStatus.RUNNING.value),
        PlanStep(step_idx=1, description="b", status=StepStatus.COMPLETED.value),
        PlanStep(step_idx=2, description="c", status=StepStatus.PENDING.value),
    ])
    ready = plan.get_ready_steps()
    assert len(ready) == 1
    assert ready[0].step_idx == 2


def test_get_step_not_found():
    plan = Plan(id="p", user_id=1, session_id="", goal="g", steps=[
        PlanStep(step_idx=0, description="a"),
    ])
    assert plan.get_step(0) is not None
    assert plan.get_step(99) is None


# ═══════════════════════════════════════════════
# 状态判断
# ═══════════════════════════════════════════════

def test_is_all_done_when_all_completed():
    plan = Plan(id="p", user_id=1, session_id="", goal="g", steps=[
        PlanStep(step_idx=0, description="a", status=StepStatus.COMPLETED.value),
        PlanStep(step_idx=1, description="b", status=StepStatus.COMPLETED.value),
    ])
    assert plan.is_all_done() is True


def test_is_all_done_false_when_pending():
    plan = Plan(id="p", user_id=1, session_id="", goal="g", steps=[
        PlanStep(step_idx=0, description="a", status=StepStatus.COMPLETED.value),
        PlanStep(step_idx=1, description="b", status=StepStatus.PENDING.value),
    ])
    assert plan.is_all_done() is False


def test_is_all_done_false_when_running():
    plan = Plan(id="p", user_id=1, session_id="", goal="g", steps=[
        PlanStep(step_idx=0, description="a", status=StepStatus.RUNNING.value),
    ])
    assert plan.is_all_done() is False


def test_is_all_done_true_when_failed_or_skipped():
    """failed / skipped / blocked 都算 done（不再活跃）"""
    plan = Plan(id="p", user_id=1, session_id="", goal="g", steps=[
        PlanStep(step_idx=0, description="a", status=StepStatus.FAILED.value),
        PlanStep(step_idx=1, description="b", status=StepStatus.SKIPPED.value),
        PlanStep(step_idx=2, description="c", status=StepStatus.BLOCKED.value),
    ])
    assert plan.is_all_done() is True


def test_has_failure_true():
    plan = Plan(id="p", user_id=1, session_id="", goal="g", steps=[
        PlanStep(step_idx=0, description="a", status=StepStatus.COMPLETED.value),
        PlanStep(step_idx=1, description="b", status=StepStatus.FAILED.value),
    ])
    assert plan.has_failure() is True


def test_has_failure_false():
    plan = Plan(id="p", user_id=1, session_id="", goal="g", steps=[
        PlanStep(step_idx=0, description="a", status=StepStatus.COMPLETED.value),
    ])
    assert plan.has_failure() is False


def test_has_failure_blocked_counts():
    plan = Plan(id="p", user_id=1, session_id="", goal="g", steps=[
        PlanStep(step_idx=0, description="a", status=StepStatus.BLOCKED.value),
    ])
    assert plan.has_failure() is True


# ═══════════════════════════════════════════════
# 持久化 CRUD（真实 DB）
# ═══════════════════════════════════════════════

def test_create_plan_persists():
    steps = [
        PlanStep(step_idx=0, description="搜索", subagent="search"),
        PlanStep(step_idx=1, description="汇总", subagent="codexec", depends_on=[0]),
    ]
    plan = create_plan(user_id=100, session_id="sess_1", goal="测试任务", steps=steps)
    assert plan.id.startswith("plan_")
    assert plan.status == PlanStatus.PLANNING.value
    assert len(plan.steps) == 2
    # 所有 step 都应有 DB id
    assert all(s.id is not None for s in plan.steps)

    # reload 验证
    loaded = load_plan(plan.id)
    assert loaded is not None
    assert loaded.goal == "测试任务"
    assert loaded.user_id == 100
    assert len(loaded.steps) == 2
    assert loaded.steps[0].description == "搜索"
    assert loaded.steps[0].subagent == "search"
    assert loaded.steps[1].depends_on == [0]


def test_load_plan_not_found():
    assert load_plan("nonexistent_plan") is None


def test_update_step_status_running():
    plan = create_plan(user_id=1, session_id="", goal="g",
                       steps=[PlanStep(step_idx=0, description="x")])
    update_step_status(plan.id, 0, StepStatus.RUNNING.value)
    loaded = load_plan(plan.id)
    assert loaded.steps[0].status == StepStatus.RUNNING.value
    assert loaded.steps[0].started_at is not None


def test_update_step_status_completed_with_result():
    plan = create_plan(user_id=1, session_id="", goal="g",
                       steps=[PlanStep(step_idx=0, description="x")])
    update_step_status(plan.id, 0, StepStatus.COMPLETED.value, result="执行完成")
    loaded = load_plan(plan.id)
    assert loaded.steps[0].status == StepStatus.COMPLETED.value
    assert loaded.steps[0].result == "执行完成"
    assert loaded.steps[0].finished_at is not None


def test_update_step_status_failed_with_error():
    plan = create_plan(user_id=1, session_id="", goal="g",
                       steps=[PlanStep(step_idx=0, description="x")])
    update_step_status(plan.id, 0, StepStatus.FAILED.value, error_msg="超时",
                       increment_attempts=True)
    loaded = load_plan(plan.id)
    assert loaded.steps[0].status == StepStatus.FAILED.value
    assert loaded.steps[0].error_msg == "超时"
    assert loaded.steps[0].attempts == 1


def test_replace_plan_steps():
    """修订计划：旧 step 被删，新 step 写入"""
    plan = create_plan(user_id=1, session_id="", goal="g", steps=[
        PlanStep(step_idx=0, description="旧步骤"),
    ])
    new_steps = [
        PlanStep(step_idx=0, description="新步骤1"),
        PlanStep(step_idx=1, description="新步骤2"),
        PlanStep(step_idx=2, description="新步骤3", depends_on=[0, 1]),
    ]
    replace_plan_steps(plan.id, new_steps)
    loaded = load_plan(plan.id)
    assert len(loaded.steps) == 3
    assert loaded.steps[0].description == "新步骤1"
    assert loaded.steps[2].depends_on == [0, 1]
    # plan 状态应回到 executing
    assert loaded.status == PlanStatus.EXECUTING.value


def test_update_plan_status():
    plan = create_plan(user_id=1, session_id="", goal="g",
                       steps=[PlanStep(step_idx=0, description="x")])
    update_plan_status(plan.id, PlanStatus.COMPLETED.value, final_answer="最终答案")
    loaded = load_plan(plan.id)
    assert loaded.status == PlanStatus.COMPLETED.value
    assert loaded.final_answer == "最终答案"


def test_list_user_plans():
    create_plan(user_id=200, session_id="s1", goal="任务A",
                steps=[PlanStep(step_idx=0, description="x")])
    create_plan(user_id=200, session_id="s2", goal="任务B",
                steps=[PlanStep(step_idx=0, description="y")])
    create_plan(user_id=300, session_id="s3", goal="别人的",
                steps=[PlanStep(step_idx=0, description="z")])

    plans = list_user_plans(200)
    assert len(plans) == 2
    goals = {p["goal"] for p in plans}
    assert goals == {"任务A", "任务B"}


def test_list_user_plans_empty():
    plans = list_user_plans(9999)
    assert plans == []


def test_get_session_plan():
    """取会话最近的 plan"""
    plan = create_plan(user_id=1, session_id="sess_get", goal="g",
                       steps=[PlanStep(step_idx=0, description="x")])
    found = get_session_plan("sess_get")
    assert found is not None
    assert found.id == plan.id


def test_get_session_plan_not_found():
    assert get_session_plan("no_such_session") is None


def test_plan_status_enum_values():
    """状态枚举字符串值正确"""
    assert PlanStatus.PLANNING.value == "planning"
    assert PlanStatus.EXECUTING.value == "executing"
    assert PlanStatus.REFLECTING.value == "reflecting"
    assert PlanStatus.COMPLETED.value == "completed"
    assert PlanStatus.FAILED.value == "failed"
    assert PlanStatus.REVISED.value == "revised"
    assert PlanStatus.CANCELLED.value == "cancelled"


def test_step_status_enum_values():
    assert StepStatus.PENDING.value == "pending"
    assert StepStatus.READY.value == "ready"
    assert StepStatus.RUNNING.value == "running"
    assert StepStatus.COMPLETED.value == "completed"
    assert StepStatus.FAILED.value == "failed"
    assert StepStatus.SKIPPED.value == "skipped"
    assert StepStatus.BLOCKED.value == "blocked"
