"""DeepAgent Plan 数据结构 + 持久化。

Plan 是 DeepAgent 架构的一等公民：
- Planner 产出结构化 Plan（含 steps + 依赖关系）
- Executor 按 step 调度 SubAgent / Tool
- Reflector 评估结果，可修订 Plan
- 全程通过 SSE 推送给前端，可被用户观察 / 编辑

数据库表：plans / plan_steps（见 connection.py）
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional, List, Dict, Any

from AIRAGAgent.database.connection import get_db
from AIRAGAgent.utils.logger_handler import logger


# ═══════════════════════════════════════════════
# 状态枚举
# ═══════════════════════════════════════════════

class PlanStatus(str, Enum):
    PLANNING = "planning"          # 规划中
    EXECUTING = "executing"        # 执行中
    REFLECTING = "reflecting"      # 反思中
    COMPLETED = "completed"        # 全部完成
    FAILED = "failed"              # 失败
    REVISED = "revised"            # 被修订
    CANCELLED = "cancelled"        # 用户取消

    def __str__(self):
        """返回计划状态枚举值字符串（如 'planning'）。"""
        return self.value


class StepStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"                # 依赖已满足，可执行
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"            # 用户跳过 / 失败后跳过
    BLOCKED = "blocked"            # 依赖失败，无法执行

    def __str__(self):
        """返回状态枚举的字符串值。"""
        return self.value


# ═══════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════

@dataclass
class PlanStep:
    """Plan 中的一个步骤。

    依赖关系通过 depends_on（step_idx 列表）表达。
    同一层级的 step（无相互依赖）可并行执行。
    """
    step_idx: int                                  # 从 0 开始的序号，决定默认执行顺序
    description: str                               # 自然语言描述要做什么
    subagent: str = ""                             # 指定由哪个 SubAgent 执行；空表示由 Orchestrator 直接 LLM 回答
    depends_on: List[int] = field(default_factory=list)   # 依赖的 step_idx 列表
    status: str = StepStatus.PENDING.value
    result: str = ""                               # 执行结果文本
    attempts: int = 0                              # 已尝试次数
    error_msg: str = ""
    started_at: Optional[float] = None
    finished_at: Optional[float] = None

    # 内存中字段（不持久化）
    id: Optional[int] = None

    def to_dict(self) -> dict:
        """把步骤对象转为字典（供持久化/序列化使用）。"""
        return asdict(self)

    @classmethod
    def from_row(cls, row: dict) -> "PlanStep":
        """从数据库行记录构造 PlanStep（解析 depends_on 逗号分隔的步骤序号）。"""
        depends_on = []
        if row.get("depends_on"):
            try:
                depends_on = [int(x) for x in str(row["depends_on"]).split(",") if x.strip() != ""]
            except ValueError:
                depends_on = []
        return cls(
            id=row["id"],
            step_idx=row["step_idx"],
            description=row["description"],
            subagent=row.get("subagent", "") or "",
            depends_on=depends_on,
            status=row.get("status", StepStatus.PENDING.value),
            result=row.get("result", "") or "",
            attempts=row.get("attempts", 0) or 0,
            error_msg=row.get("error_msg", "") or "",
            started_at=row["started_at"].timestamp() if row.get("started_at") else None,
            finished_at=row["finished_at"].timestamp() if row.get("finished_at") else None,
        )


@dataclass
class Plan:
    """完整执行计划。

    status 流转：
        planning → executing → reflecting → completed/failed/revised
                                  ↑__________________|
                              (Reflector 决定修订时回到 executing)
    """
    id: str
    user_id: int
    session_id: str
    goal: str
    steps: List[PlanStep] = field(default_factory=list)
    status: str = PlanStatus.PLANNING.value
    final_answer: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        """把计划对象（含全部步骤）转为字典（供序列化/推送前端使用）。"""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "goal": self.goal,
            "status": self.status,
            "final_answer": self.final_answer,
            "steps": [s.to_dict() for s in self.steps],
            "created_at": self.created_at,
        }

    # ── 依赖解析工具 ──

    def get_step(self, step_idx: int) -> Optional[PlanStep]:
        """按步骤序号查找步骤，找不到返回 None。"""
        for s in self.steps:
            if s.step_idx == step_idx:
                return s
        return None

    def get_ready_steps(self) -> List[PlanStep]:
        """返回所有依赖已完成、且自身处于 pending 的 step（可并行执行）。"""
        ready = []
        completed_idxs = {s.step_idx for s in self.steps if s.status == StepStatus.COMPLETED.value}
        failed_idxs = {s.step_idx for s in self.steps if s.status in (StepStatus.FAILED.value, StepStatus.BLOCKED.value)}
        for s in self.steps:
            if s.status != StepStatus.PENDING.value:
                continue
            # 依赖全部完成
            if all(dep in completed_idxs for dep in s.depends_on):
                ready.append(s)
            # 依赖有失败 → 标记 blocked
            elif any(dep in failed_idxs for dep in s.depends_on):
                s.status = StepStatus.BLOCKED.value
                s.error_msg = "依赖步骤失败，无法执行"
        return ready

    def is_all_done(self) -> bool:
        """所有 step 都不在 pending/ready/running 状态。"""
        active = {StepStatus.PENDING.value, StepStatus.READY.value, StepStatus.RUNNING.value}
        return all(s.status not in active for s in self.steps)

    def has_failure(self) -> bool:
        """判断计划中是否有失败或被阻塞的步骤。"""
        return any(s.status in (StepStatus.FAILED.value, StepStatus.BLOCKED.value) for s in self.steps)


# ═══════════════════════════════════════════════
# 持久化 CRUD
# ═══════════════════════════════════════════════

def create_plan(user_id: int, session_id: str, goal: str, steps: List[PlanStep]) -> Plan:
    """创建 Plan 并持久化（含所有 step）。"""
    plan_id = f"plan_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
    plan = Plan(
        id=plan_id,
        user_id=user_id,
        session_id=session_id or "",
        goal=goal,
        steps=steps,
        status=PlanStatus.PLANNING.value,
    )
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO plans (id, user_id, session_id, goal, status) VALUES (%s, %s, %s, %s, %s)",
            (plan.id, plan.user_id, plan.session_id, plan.goal, plan.status),
        )
        for step in plan.steps:
            cursor.execute(
                """INSERT INTO plan_steps
                   (plan_id, step_idx, description, subagent, depends_on, status)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (
                    plan.id,
                    step.step_idx,
                    step.description,
                    step.subagent,
                    ",".join(str(x) for x in step.depends_on),
                    step.status,
                ),
            )
            step.id = cursor.lastrowid
        conn.commit()
    logger.info(f"[Plan] 创建 plan={plan_id} user={user_id} steps={len(steps)}")
    return plan


def load_plan(plan_id: str) -> Optional[Plan]:
    """从 DB 加载 Plan（含所有 step）。"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, user_id, session_id, goal, status, final_answer, created_at FROM plans WHERE id = %s",
            (plan_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        cursor.execute(
            "SELECT * FROM plan_steps WHERE plan_id = %s ORDER BY step_idx ASC",
            (plan_id,),
        )
        steps = [PlanStep.from_row(r) for r in cursor.fetchall()]
        return Plan(
            id=row["id"],
            user_id=row["user_id"],
            session_id=row.get("session_id", "") or "",
            goal=row["goal"],
            steps=steps,
            status=row["status"],
            final_answer=row.get("final_answer", "") or "",
            created_at=row["created_at"].timestamp() if row.get("created_at") else time.time(),
        )


def update_step_status(plan_id: str, step_idx: int, status: str,
                       result: str = None, error_msg: str = None,
                       increment_attempts: bool = False) -> None:
    """更新单个 step 的状态。"""
    sets = ["status = %s"]
    params: list = [status]
    if result is not None:
        sets.append("result = %s")
        params.append(result)
    if error_msg is not None:
        sets.append("error_msg = %s")
        params.append(error_msg)
    if status == "running":
        sets.append("started_at = CURRENT_TIMESTAMP")
    if status in ("completed", "failed", "skipped", "blocked"):
        sets.append("finished_at = CURRENT_TIMESTAMP")
    if increment_attempts:
        sets.append("attempts = attempts + 1")

    params.append(plan_id)
    params.append(step_idx)
    sql = f"UPDATE plan_steps SET {', '.join(sets)} WHERE plan_id = %s AND step_idx = %s"
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(sql, tuple(params))
        conn.commit()


def replace_plan_steps(plan_id: str, new_steps: List[PlanStep]) -> None:
    """修订 Plan 时整体替换 step 列表（保留 plan 行，清空旧 step，写入新 step）。"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM plan_steps WHERE plan_id = %s", (plan_id,))
        for step in new_steps:
            cursor.execute(
                """INSERT INTO plan_steps
                   (plan_id, step_idx, description, subagent, depends_on, status)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (
                    plan_id,
                    step.step_idx,
                    step.description,
                    step.subagent,
                    ",".join(str(x) for x in step.depends_on),
                    step.status,
                ),
            )
            step.id = cursor.lastrowid
        cursor.execute(
            "UPDATE plans SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (PlanStatus.EXECUTING.value, plan_id),
        )
        conn.commit()
    logger.info(f"[Plan] 修订 plan={plan_id} 新步骤数={len(new_steps)}")


def update_plan_status(plan_id: str, status: str, final_answer: str = None) -> None:
    """更新计划的整体状态，可附带最终答案（超长自动截断到 65000 字符）。"""
    sets = ["status = %s", "updated_at = CURRENT_TIMESTAMP"]
    params: list = [status]
    if final_answer is not None:
        sets.append("final_answer = %s")
        params.append(final_answer[:65000] if final_answer else "")
    params.append(plan_id)
    sql = f"UPDATE plans SET {', '.join(sets)} WHERE id = %s"
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(sql, tuple(params))
        conn.commit()


def get_session_plan(session_id: str) -> Optional[Plan]:
    """取会话最近一个未完成 / 最后一个 plan。"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id FROM plans WHERE session_id = %s
               ORDER BY (status IN ('planning', 'executing', 'reflecting', 'revised')) DESC,
                        created_at DESC LIMIT 1""",
            (session_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return load_plan(row["id"])


def list_user_plans(user_id: int, limit: int = 20) -> List[dict]:
    """查询指定用户最近的计划列表（默认 20 条），返回格式化后的字典列表。"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id, session_id, goal, status, created_at, updated_at
               FROM plans WHERE user_id = %s ORDER BY updated_at DESC LIMIT %s""",
            (user_id, limit),
        )
        rows = cursor.fetchall()
        return [
            {
                "id": r["id"],
                "session_id": r.get("session_id", "") or "",
                "goal": r["goal"],
                "status": r["status"],
                "created_at": r["created_at"].strftime("%Y-%m-%d %H:%M:%S") if r.get("created_at") else "",
                "updated_at": r["updated_at"].strftime("%Y-%m-%d %H:%M:%S") if r.get("updated_at") else "",
            }
            for r in rows
        ]
