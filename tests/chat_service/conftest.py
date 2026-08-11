"""chat_service 测试固件。

chat_service 依赖 AIRAGAgent.* 引擎（orchestrator / database / rate_limiter / task_queue），
直接 import 会拉起 LLM 客户端、SubAgent 注册表、Redis 连接等重量级初始化。

策略：
1. 在 import chat_service.main 之前，把所有 AIRAGAgent.* 子模块预注入 sys.modules 为 MagicMock
   —— 这样 `from AIRAGAgent.xxx import yyy` 都拿到 MagicMock，不会触发真实初始化
2. user_ip_var / user_lat_var / user_lon_var / user_id_var 用真实 ContextVar 替换
   —— main.py 的 /api/chat 端点会 .set() 这些变量，MagicMock 无法支持 .get() 返回真实值
3. lifespan 启动调用的 init_db / register_default_handlers / cleanup_old_daily_workspaces
   均为 MagicMock，自动 no-op
4. 每个测试通过 monkeypatch 替换 main 内的 agent_service 或 AIRAGAgent.database 函数
"""
import os
import sys
import contextvars
import importlib.util
from unittest.mock import MagicMock

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# ====== 1. 环境变量（必须在 import main 之前设置）======
os.environ.setdefault("MYSQL_HOST", "localhost")
os.environ.setdefault("MYSQL_PORT", "3307")
os.environ.setdefault("MYSQL_USER", "root")
os.environ["MYSQL_PASSWORD"] = os.environ.get("MYSQL_PASSWORD", "")
os.environ["DB_NAME"] = "lc_chat_test"
os.environ["CHAT_DB"] = "lc_chat_test"
os.environ.setdefault("JWT_SECRET_KEY", "lc-course-secret-key-2025")
os.environ.setdefault("JWT_TOKEN_EXPIRE_HOURS", "72")
os.environ.pop("ADMIN_ALLOWED_IPS", None)
# AIRAGAgent 配置文件目录（虽然走 MagicMock 不会真读，但 logger 初始化可能引用）
os.environ.setdefault("AGENT_HOME", PROJECT_ROOT)
# 把项目根加入 PYTHONPATH 以便 AIRAGAgent.* 真实包被发现（即便用 MagicMock 替换）
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ====== 2. 预注入 AIRAGAgent.* 为 MagicMock（必须在 import chat_service.main 之前）======
# 真实 ContextVar 替换 agent_tools 中的变量（main.py 端点会 .set()）
_real_user_ip_var = contextvars.ContextVar("user_ip", default="")
_real_user_lat_var = contextvars.ContextVar("user_lat", default=None)
_real_user_lon_var = contextvars.ContextVar("user_lon", default=None)
_real_user_id_var = contextvars.ContextVar("user_id", default=0)


def _build_agent_tools_mock():
    """agent_tools 模块需要真实的 ContextVar（main.py 端点会调 .set()）。"""
    m = MagicMock()
    m.user_ip_var = _real_user_ip_var
    m.user_lat_var = _real_user_lat_var
    m.user_lon_var = _real_user_lon_var
    m.user_id_var = _real_user_id_var
    return m


# AIRAGAgent 子模块清单（按依赖顺序）
_AIRAGAGENT_SUBMODULES = [
    "AIRAGAgent",
    "AIRAGAgent.agent",
    "AIRAGAgent.agent.orchestrator",
    "AIRAGAgent.agent.plan",
    "AIRAGAgent.agent.sub_agent",
    "AIRAGAgent.agent.tools",
    "AIRAGAgent.agent.tools.agent_tools",
    "AIRAGAgent.database",
    "AIRAGAgent.database.connection",
    "AIRAGAgent.infrastructure",
    "AIRAGAgent.infrastructure.rate_limiter",
    "AIRAGAgent.infrastructure.redis_client",
    "AIRAGAgent.infrastructure.session_cache",
    "AIRAGAgent.infrastructure.task_queue",
    "AIRAGAgent.utils",
    "AIRAGAgent.utils.paths",
    "AIRAGAgent.utils.config_handler",
    "AIRAGAgent.utils.logger_handler",
]

for mod_name in _AIRAGAGENT_SUBMODULES:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

# agent_tools 替换为带真实 ContextVar 的版本
sys.modules["AIRAGAgent.agent.tools.agent_tools"] = _build_agent_tools_mock()


# ====== 3. 加载 chat_service main ======
def _load_service_main(service_name: str, module_alias: str):
    service_dir = os.path.abspath(os.path.join(PROJECT_ROOT, "services", service_name))
    if service_dir not in sys.path:
        sys.path.insert(0, service_dir)
    for mod_name in list(sys.modules):
        if mod_name in ("core", "models", "agent", "db_patch") or \
           mod_name.startswith("core.") or mod_name.startswith("models.") or \
           mod_name == "agent" or mod_name == "db_patch":
            # 不清理 agent / db_patch（chat_service 特有），因为 sys.modules 里的
            # agent 模块是其他服务的（如 user_service_main），不会冲突
            if mod_name in ("core", "models") or mod_name.startswith("core.") or mod_name.startswith("models."):
                del sys.modules[mod_name]
    main_path = os.path.join(service_dir, "main.py")
    spec = importlib.util.spec_from_file_location(module_alias, main_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_alias] = module
    spec.loader.exec_module(module)
    return module


chat_main = _load_service_main("chat_service", "chat_service_main")
app = chat_main.app

# 从本服务 core.jwt_auth 取 create_access_token
import core.jwt_auth as _chat_jwt  # noqa: E402
create_access_token = _chat_jwt.create_access_token

import pymysql  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


# ====== 4. 测试库建表 SQL（与 migrations/versions/chat/0001_baseline.py 一致）======
SCHEMA_SQL = [
    """CREATE TABLE IF NOT EXISTS conversations (
        id VARCHAR(100) PRIMARY KEY,
        user_id BIGINT NOT NULL DEFAULT 0,
        title VARCHAR(255) NOT NULL DEFAULT '',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        is_deleted TINYINT NOT NULL DEFAULT 0,
        pinned TINYINT NOT NULL DEFAULT 0,
        starred TINYINT NOT NULL DEFAULT 0,
        folder VARCHAR(100) NOT NULL DEFAULT '',
        parent_conversation_id VARCHAR(100) NOT NULL DEFAULT '',
        branch_point_message_id BIGINT NOT NULL DEFAULT 0,
        INDEX idx_conv_user (user_id),
        INDEX idx_conv_user_pinned (user_id, pinned),
        INDEX idx_conv_parent (parent_conversation_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
    """CREATE TABLE IF NOT EXISTS messages (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        conversation_id VARCHAR(100) NOT NULL,
        role VARCHAR(20) NOT NULL,
        content TEXT NOT NULL,
        extra_json TEXT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_conv_created (conversation_id, created_at),
        INDEX idx_msg_content (content(100))
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
    """CREATE TABLE IF NOT EXISTS message_feedback (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        user_id BIGINT NOT NULL,
        conversation_id VARCHAR(100) NOT NULL,
        message_id BIGINT NULL,
        message_role VARCHAR(20) NOT NULL DEFAULT 'assistant',
        message_content TEXT NOT NULL,
        feedback VARCHAR(20) NOT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uk_user_conv_role (user_id, conversation_id, message_role),
        INDEX idx_feedback_type (feedback),
        INDEX idx_feedback_user (user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
    """CREATE TABLE IF NOT EXISTS api_call_logs (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        user_id BIGINT NOT NULL DEFAULT 0,
        session_id VARCHAR(100) NOT NULL DEFAULT '',
        ip VARCHAR(64) NOT NULL DEFAULT '',
        endpoint VARCHAR(50) NOT NULL DEFAULT 'chat',
        duration_ms INT NOT NULL DEFAULT 0,
        prompt_tokens INT NOT NULL DEFAULT 0,
        completion_tokens INT NOT NULL DEFAULT 0,
        total_tokens INT NOT NULL DEFAULT 0,
        is_success TINYINT NOT NULL DEFAULT 1,
        error_msg VARCHAR(1000) NOT NULL DEFAULT '',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_api_user (user_id),
        INDEX idx_api_created (created_at),
        INDEX idx_api_success (is_success)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
    """CREATE TABLE IF NOT EXISTS tool_call_logs (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        user_id BIGINT NOT NULL DEFAULT 0,
        session_id VARCHAR(100) NOT NULL DEFAULT '',
        tool_name VARCHAR(100) NOT NULL DEFAULT '',
        duration_ms INT NOT NULL DEFAULT 0,
        is_success TINYINT NOT NULL DEFAULT 1,
        error_msg VARCHAR(1000) NOT NULL DEFAULT '',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_tool_name (tool_name),
        INDEX idx_tool_user (user_id),
        INDEX idx_tool_created (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
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
    """CREATE TABLE IF NOT EXISTS user_memories (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        user_id BIGINT NOT NULL,
        memory_type VARCHAR(30) NOT NULL DEFAULT 'fact',
        key_name VARCHAR(200) NOT NULL DEFAULT '',
        value TEXT NOT NULL,
        source VARCHAR(100) NOT NULL DEFAULT 'agent',
        confidence DECIMAL(3,2) NOT NULL DEFAULT 1.00,
        is_active TINYINT NOT NULL DEFAULT 1,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_user_key (user_id, key_name),
        INDEX idx_mem_user (user_id, is_active),
        INDEX idx_mem_type (memory_type),
        INDEX idx_mem_key (user_id, key_name)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
    """CREATE TABLE IF NOT EXISTS artifacts (
        id VARCHAR(64) PRIMARY KEY,
        user_id BIGINT NOT NULL,
        session_id VARCHAR(100) NOT NULL DEFAULT '',
        plan_id VARCHAR(64) NOT NULL DEFAULT '',
        step_idx INT NULL,
        type VARCHAR(30) NOT NULL DEFAULT 'doc',
        title VARCHAR(255) NOT NULL DEFAULT '',
        content_ref VARCHAR(500) NOT NULL DEFAULT '',
        mime_type VARCHAR(100) NOT NULL DEFAULT '',
        version INT NOT NULL DEFAULT 1,
        parent_id VARCHAR(64) NOT NULL DEFAULT '',
        meta JSON NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_art_user (user_id),
        INDEX idx_art_session (session_id),
        INDEX idx_art_plan (plan_id),
        INDEX idx_art_type (type)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
]

TABLES = ["artifacts", "user_memories", "plan_steps", "plans",
          "tool_call_logs", "api_call_logs", "message_feedback", "messages",
          "conversations"]


def _admin_connect():
    return pymysql.connect(
        host=os.environ["MYSQL_HOST"],
        port=int(os.environ["MYSQL_PORT"]),
        user=os.environ["MYSQL_USER"],
        password=os.environ["MYSQL_PASSWORD"],
        charset="utf8mb4",
        autocommit=True,
    )


# ====== 5. 固件 ======

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
            for sql in SCHEMA_SQL:
                cur.execute(sql)
    finally:
        conn.close()
    yield


@pytest.fixture(autouse=True)
def db_clean(db_setup):
    conn = _admin_connect()
    try:
        with conn.cursor() as cur:
            cur.execute("USE lc_chat_test")
            # plan_steps 有外键指向 plans，禁用 FK 检查后 TRUNCATE
            cur.execute("SET FOREIGN_KEY_CHECKS=0")
            for tbl in TABLES:
                cur.execute(f"TRUNCATE TABLE {tbl}")
            cur.execute("SET FOREIGN_KEY_CHECKS=1")
    finally:
        conn.close()
    yield


@pytest.fixture(autouse=True)
def mock_pubsub(monkeypatch):
    """禁用 Redis 事件发布（chat_service 在埋点时调 publish_event）。"""
    monkeypatch.setattr(chat_main, "publish_event", lambda *a, **kw: False)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def user_token():
    return create_access_token(4001, "chatter", "user")


@pytest.fixture
def user_headers(user_token):
    return _hdr(user_token)


@pytest.fixture
def admin_token():
    return create_access_token(1, "admin", "admin")


@pytest.fixture
def admin_headers(admin_token):
    return _hdr(admin_token)


@pytest.fixture
def make_token():
    def _make(user_id, username=None, role="user"):
        return create_access_token(user_id, username or f"user{user_id}", role)
    return _make


def make_headers(token: str) -> dict:
    return _hdr(token)
