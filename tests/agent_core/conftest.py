"""AIRAGAgent 核心（plan / rate_limiter / paths / sub_agent registry）测试固件。

策略：
1. 重依赖模块（langchain / AIRAGAgent.model.factory / database.connection / redis_client）
   预注入 MagicMock，避免拉起 LLM 客户端、Redis 连接、MySQL 连接池
2. logger_handler / path_tool 是轻量纯 Python，直接放行真实导入
3. plan.py / rate_limiter.py / paths.py 本身是测试目标，需真实导入——
   通过先 mock 它们的重依赖，再 import 它们本体来实现
4. SubAgentRegistry 测试：跳过 build_agent（需 LLM），只测注册 / 查询等纯字典操作
"""
import os
import sys
from unittest.mock import MagicMock, patch

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ====== 1. 预注入重依赖为 MagicMock ======
# 注意：agent_core 需要真实的 plan / sub_agent / orchestrator / paths / rate_limiter 模块，
# 因此这些模块不 mock；只 mock langchain / LLM 工厂 / middleware 等重依赖。
# ⚠️ 不要和 chat_service 测试在同一 pytest 进程中运行——
#    chat_service conftest 会把 AIRAGAgent.* 全部 mock 掉，导致 agent_core 拿不到真实模块。
#    CI 中用独立 pytest 命令分别运行（--cov-append 累积覆盖率）。
_HEAVY_MODULES = [
    # langchain 全家桶（sub_agent.py 导入）
    "langchain",
    "langchain.agents",
    "langchain.agents.middleware",
    "langchain.agents.middleware.tool_call_limit",
    # AIRAGAgent LLM 工厂
    "AIRAGAgent.model",
    "AIRAGAgent.model.factory",
    # middleware（sub_agent 导入）
    "AIRAGAgent.agent.tools",
    "AIRAGAgent.agent.tools.middleware",
    "AIRAGAgent.agent.tools.agent_tools",
    "AIRAGAgent.agent.tools.artifact_tools",
    # sub_agents 包（orchestrator __init__ 导入 register_all_subagents）
    "AIRAGAgent.agent.sub_agents",
    "AIRAGAgent.agent.sub_agents.builtin",
    # prompt_loader（sub_agent 导入）
    "AIRAGAgent.utils.prompt_loader",
]
for mod_name in _HEAVY_MODULES:
    if mod_name not in sys.modules or isinstance(sys.modules.get(mod_name), MagicMock):
        sys.modules[mod_name] = MagicMock()

# agent_tools 需要真实 ContextVar（部分代码引用 user_id_var 等）
import contextvars
_real_user_id_var = contextvars.ContextVar("user_id", default=0)
_real_user_ip_var = contextvars.ContextVar("user_ip", default="")
sys.modules["AIRAGAgent.agent.tools.agent_tools"].user_id_var = _real_user_id_var
sys.modules["AIRAGAgent.agent.tools.agent_tools"].user_ip_var = _real_user_ip_var
sys.modules["AIRAGAgent.agent.tools.artifact_tools"].current_plan_id_var = contextvars.ContextVar("plan_id", default="")
sys.modules["AIRAGAgent.agent.tools.artifact_tools"].current_session_id_var = contextvars.ContextVar("session_id", default="")
sys.modules["AIRAGAgent.agent.tools.artifact_tools"].current_step_idx_var = contextvars.ContextVar("step_idx", default=-1)

# ====== 2. Mock AIRAGAgent.database.connection（plan.py / models.py 依赖）======
import pymysql
from pymysql.cursors import DictCursor

_db_config = {
    "host": os.environ.get("MYSQL_HOST", "localhost"),
    "port": int(os.environ.get("MYSQL_PORT", "3307")),
    "user": os.environ.get("MYSQL_USER", "root"),
    "password": os.environ.get("MYSQL_PASSWORD", ""),
    "database": "lc_chat_test",
    "charset": "utf8mb4",
    "cursorclass": DictCursor,
    "autocommit": True,
}


def _real_get_db():
    """测试用真实 MySQL 连接（lc_chat_test 库，schema 由 chat_service conftest 建好）。

    plan 持久化测试需要真实 DB 验证 CRUD；rate_limiter / paths 测试不调 get_db。
    """
    return _RealDbCtx()


class _RealDbCtx:
    def __enter__(self):
        self.conn = pymysql.connect(**_db_config)
        return self.conn

    def __exit__(self, *exc):
        self.conn.close()


_db_conn_mod = MagicMock()
_db_conn_mod.get_db = _real_get_db
_db_conn_mod.mysql_conf = {"database": "lc_chat_test"}
sys.modules["AIRAGAgent.database.connection"] = _db_conn_mod

# ====== 3. Mock redis_client（rate_limiter 依赖）======
class FakeRedis:
    """简易 Redis 桩：支持 zadd/zcard/zremrangebyscore/expire/pipeline/delete。"""
    def __init__(self):
        self._data = {}  # key -> sorted dict {member: score}

    def pipeline(self):
        return _FakePipe(self)

    def delete(self, key):
        return self._data.pop(key, None) is not None

    def _zadd(self, key, mapping):
        if key not in self._data:
            self._data[key] = {}
        for member, score in mapping.items():
            self._data[key][str(member)] = float(score)

    def _zcard(self, key):
        return len(self._data.get(key, {}))

    def _zremrangebyscore(self, key, min_s, max_s):
        if key not in self._data:
            return 0
        before = len(self._data[key])
        self._data[key] = {
            m: s for m, s in self._data[key].items()
            if not (min_s <= s <= max_s)
        }
        return before - len(self._data[key])

    def _expire(self, key, seconds):
        pass  # 测试不关心过期


class _FakePipe:
    def __init__(self, redis):
        self.redis = redis
        self._cmds = []

    def zremrangebyscore(self, key, min_s, max_s):
        self._cmds.append(("zremrangebyscore", key, min_s, max_s))

    def zcard(self, key):
        self._cmds.append(("zcard", key))

    def zadd(self, key, mapping):
        self._cmds.append(("zadd", key, mapping))

    def expire(self, key, seconds):
        self._cmds.append(("expire", key, seconds))

    def execute(self):
        results = []
        for cmd in self._cmds:
            op = cmd[0]
            if op == "zremrangebyscore":
                results.append(self.redis._zremrangebyscore(cmd[1], cmd[2], cmd[3]))
            elif op == "zcard":
                results.append(self.redis._zcard(cmd[1]))
            elif op == "zadd":
                self.redis._zadd(cmd[1], cmd[2])
                results.append(1)
            elif op == "expire":
                self.redis._expire(cmd[1], cmd[2])
                results.append(True)
        self._cmds = []
        return results


_fake_redis = FakeRedis()

_redis_mod = MagicMock()
_redis_mod.get_redis_client.return_value = _fake_redis
_redis_mod.is_redis_available.return_value = True
sys.modules["AIRAGAgent.infrastructure.redis_client"] = _redis_mod

# ====== 4. Mock config_handler（rate_limiter 读 redis_conf）======
_config_mod = MagicMock()
_config_mod.redis_conf = {
    "rate_limit": {
        "chat": {"max_requests": 3, "window_seconds": 60},
        "tool": {"max_requests": 30, "window_seconds": 60},
    }
}
sys.modules["AIRAGAgent.utils.config_handler"] = _config_mod

# ====== 5. 测试库 schema（plan 持久化测试需要）======
import pytest  # noqa: E402

SCHEMA_SQL = [
    """CREATE TABLE IF NOT EXISTS plans (
        id VARCHAR(64) PRIMARY KEY,
        user_id BIGINT NOT NULL DEFAULT 0,
        session_id VARCHAR(100) NOT NULL DEFAULT '',
        goal TEXT NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'planning',
        final_answer TEXT,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_plan_user (user_id),
        INDEX idx_plan_session (session_id),
        INDEX idx_plan_status (status)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
    """CREATE TABLE IF NOT EXISTS plan_steps (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        plan_id VARCHAR(64) NOT NULL,
        step_idx INT NOT NULL,
        description TEXT NOT NULL,
        subagent VARCHAR(50) NOT NULL DEFAULT '',
        depends_on VARCHAR(255) NOT NULL DEFAULT '',
        status VARCHAR(20) NOT NULL DEFAULT 'pending',
        result TEXT,
        attempts INT NOT NULL DEFAULT 0,
        error_msg TEXT,
        started_at DATETIME NULL,
        finished_at DATETIME NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_step_plan (plan_id),
        INDEX idx_step_status (status),
        CONSTRAINT fk_step_plan FOREIGN KEY (plan_id) REFERENCES plans(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
]


def _admin_connect():
    return pymysql.connect(
        host=_db_config["host"],
        port=_db_config["port"],
        user=_db_config["user"],
        password=_db_config["password"],
        charset="utf8mb4",
        autocommit=True,
    )


@pytest.fixture(scope="session")
def db_setup():
    conn = _admin_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "CREATE DATABASE IF NOT EXISTS lc_chat_test "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
            cur.execute("USE lc_chat_test")
            cur.execute("SET FOREIGN_KEY_CHECKS=0")
            for sql in SCHEMA_SQL:
                cur.execute(sql)
            cur.execute("SET FOREIGN_KEY_CHECKS=1")
    finally:
        conn.close()
    yield


@pytest.fixture(autouse=True)
def db_clean(db_setup):
    conn = _admin_connect()
    try:
        with conn.cursor() as cur:
            cur.execute("USE lc_chat_test")
            cur.execute("SET FOREIGN_KEY_CHECKS=0")
            cur.execute("TRUNCATE TABLE plan_steps")
            cur.execute("TRUNCATE TABLE plans")
            cur.execute("SET FOREIGN_KEY_CHECKS=1")
    finally:
        conn.close()
    yield


@pytest.fixture(autouse=True)
def reset_fake_redis():
    """每个测试前清空 fake redis 数据。"""
    _fake_redis._data.clear()
    # RateLimiterFactory 是单例缓存，需重置以读到新 config
    import AIRAGAgent.infrastructure.rate_limiter as rl
    rl.RateLimiterFactory._instances.clear()
    yield
    _fake_redis._data.clear()
