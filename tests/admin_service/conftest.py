"""admin_service 测试固件。

独立测试库 lc_admin_test，含 rate_limit_events / api_call_logs / tool_call_logs 三表。
跨服务调用（auth / user / chat）全部 mock，Redis pub/sub 订阅在启动时跳过。
"""
import os
import sys
import importlib.util

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# ====== 1. 环境变量（必须在 import main 之前设置）======
os.environ.setdefault("MYSQL_HOST", "localhost")
os.environ.setdefault("MYSQL_PORT", "3306")
os.environ.setdefault("MYSQL_USER", "root")
os.environ["MYSQL_PASSWORD"] = os.environ.get("MYSQL_PASSWORD", "")
os.environ["DB_NAME"] = "lc_admin_test"
os.environ["ADMIN_DB"] = "lc_admin_test"
os.environ.setdefault("JWT_SECRET_KEY", "lc-course-secret-key-2025")
os.environ.setdefault("JWT_TOKEN_EXPIRE_HOURS", "72")
os.environ.pop("ADMIN_ALLOWED_IPS", None)


# ====== 2. 加载 main（先 mock 掉 Redis 订阅，避免 lifespan 启动拉起后台线程）======
def _load_service_main(service_name: str, module_alias: str):
    service_dir = os.path.abspath(os.path.join(PROJECT_ROOT, "services", service_name))
    if service_dir not in sys.path:
        sys.path.insert(0, service_dir)
    for mod_name in list(sys.modules):
        if mod_name in ("core", "models") or mod_name.startswith("core.") or mod_name.startswith("models."):
            del sys.modules[mod_name]
    main_path = os.path.join(service_dir, "main.py")
    spec = importlib.util.spec_from_file_location(module_alias, main_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_alias] = module
    spec.loader.exec_module(module)
    return module


admin_main = _load_service_main("admin_service", "admin_service_main")
app = admin_main.app
models = admin_main.models

# main 未导入 create_access_token，从本服务 core.jwt_auth 取
import core.jwt_auth as _admin_jwt  # noqa: E402
create_access_token = _admin_jwt.create_access_token

import pymysql  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


# ====== 3. 测试库建表 SQL（与 migrations/versions/admin/0001_baseline.py 一致）======
SCHEMA_SQL = [
    """
    CREATE TABLE IF NOT EXISTS rate_limit_events (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        user_id BIGINT NOT NULL DEFAULT 0,
        ip VARCHAR(64) NOT NULL DEFAULT '',
        limit_type VARCHAR(20) NOT NULL DEFAULT 'chat',
        identifier VARCHAR(200) NOT NULL DEFAULT '',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_rl_type (limit_type),
        INDEX idx_rl_created (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS api_call_logs (
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
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS tool_call_logs (
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
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
]

TABLES = ["tool_call_logs", "api_call_logs", "rate_limit_events"]


def _admin_connect():
    return pymysql.connect(
        host=os.environ["MYSQL_HOST"],
        port=int(os.environ["MYSQL_PORT"]),
        user=os.environ["MYSQL_USER"],
        password=os.environ["MYSQL_PASSWORD"],
        charset="utf8mb4",
        autocommit=True,
    )


# ====== 4. 固件 ======

@pytest.fixture(scope="session")
def db_setup():
    conn = _admin_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "CREATE DATABASE IF NOT EXISTS lc_admin_test "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
            cur.execute("USE lc_admin_test")
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
            cur.execute("USE lc_admin_test")
            for tbl in TABLES:
                cur.execute(f"TRUNCATE TABLE {tbl}")
    finally:
        conn.close()
    yield


@pytest.fixture(autouse=True)
def mock_redis_pubsub(monkeypatch):
    """禁用 Redis pub/sub 订阅：lifespan 启动时不拉起后台订阅线程。

    /api/health 的 redis 字段保留真实状态（disconnected/connected）以验证健康检查逻辑。
    """
    monkeypatch.setattr(admin_main, "subscribe_events", lambda *a, **kw: None)


@pytest.fixture(autouse=True)
def mock_cross_service(monkeypatch):
    """屏蔽 admin_service → auth / user / chat 的跨服务调用。

    返回 _state 字典供 mock_service_state fixture 暴露给测试。
    """
    _state = {
        # auth_service /internal/auth/users
        "auth_users": (200, {"users": [
            {"id": 1, "username": "admin", "role": "admin",
             "created_at": "2026-07-01 10:00:00"},
            {"id": 2, "username": "alice", "role": "user",
             "created_at": "2026-08-01 10:00:00"},
        ]}),
        # user_service /internal/user/profile?user_id=X
        "user_profile": (200, {"profile": {
            "display_name": "Alice", "avatar_url": "", "email": "a@b.com"
        }}),
        # user_service DELETE /internal/user/{id}
        "user_delete": (200, {"status": "ok"}),
        # chat_service DELETE /internal/chat/users/{id}/cleanup
        "chat_cleanup": (200, {"status": "ok"}),
        # chat_service GET /internal/chat/users/{id}/conversations
        "chat_conversations": (200, {"conversations": [
            {"id": "c1", "title": "对话1", "message_count": 3}
        ]}),
        # auth_service POST /internal/auth/users/{id}/delete
        "auth_delete": (200, {"status": "ok"}),
        # auth_service POST /internal/auth/users/{id}/reset-password
        "auth_reset_pwd": (200, {"status": "ok"}),
    }

    async def _mock_call_service(service, method, path, token=None, **kwargs):
        # 按 (service, method, path 片段) 路由到对应 mock 状态
        key = None
        if service == "auth" and "/internal/auth/users" in path and path.endswith("/delete"):
            key = "auth_delete"
        elif service == "auth" and "/reset-password" in path:
            key = "auth_reset_pwd"
        elif service == "auth" and "/internal/auth/users" in path:
            key = "auth_users"
        elif service == "user" and "/profile" in path:
            key = "user_profile"
        elif service == "user" and method == "DELETE":
            key = "user_delete"
        elif service == "chat" and "/cleanup" in path:
            key = "chat_cleanup"
        elif service == "chat" and "/conversations" in path:
            key = "chat_conversations"

        if key is None:
            return {"error": f"未匹配的 mock 调用: {service} {method} {path}"}
        sc, body = _state[key]
        if sc >= 400:
            return {"error": f"{service} 返回 {sc}", "detail": body}
        return body

    monkeypatch.setattr(admin_main, "call_service", _mock_call_service)
    yield _state


@pytest.fixture
def mock_service_state(mock_cross_service):
    """暴露 mock 跨服务状态，测试可配置 auth/user/chat 返回。"""
    return mock_cross_service


@pytest.fixture
def admin_main_mod():
    """暴露 admin_service main 模块，供 test_events 直接调回调函数。"""
    return admin_main


@pytest.fixture
def models_mod():
    """暴露 admin_service models 模块。"""
    return models


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_token():
    return create_access_token(1, "admin", "admin")


@pytest.fixture
def admin_headers(admin_token):
    return _hdr(admin_token)


@pytest.fixture
def normal_token():
    return create_access_token(2, "alice", "user")


@pytest.fixture
def normal_headers(normal_token):
    return _hdr(normal_token)


@pytest.fixture
def make_token():
    def _make(user_id, username=None, role="user"):
        return create_access_token(user_id, username or f"user{user_id}", role)
    return _make


def make_headers(token: str) -> dict:
    return _hdr(token)
