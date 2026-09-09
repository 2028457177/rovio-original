"""user_service 测试固件。

独立测试库 lc_user_test，含 user_profiles / user_schedules / user_models 三表。
UPLOAD_DIR 重定向到临时目录，避免污染真实 uploads/。
跨服务调用（auth / chat）全部 mock。
"""
import os
import sys
import shutil
import tempfile

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# ====== 1. 环境变量（必须在 import main 之前设置）======
_tmp_root = tempfile.mkdtemp(prefix="lc_user_test_")
os.environ["UPLOAD_DIR"] = os.path.join(_tmp_root, "uploads")
os.environ.setdefault("MYSQL_HOST", "localhost")
os.environ.setdefault("MYSQL_PORT", "3306")
os.environ.setdefault("MYSQL_USER", "root")
os.environ["MYSQL_PASSWORD"] = os.environ.get("MYSQL_PASSWORD", "")
os.environ["DB_NAME"] = "lc_user_test"
os.environ["USER_DB"] = "lc_user_test"
os.environ.setdefault("JWT_SECRET_KEY", "lc-course-secret-key-2025")
os.environ.setdefault("JWT_TOKEN_EXPIRE_HOURS", "72")
os.environ.pop("ADMIN_ALLOWED_IPS", None)


# ====== 2. 加载 main ======
import importlib.util  # noqa: E402


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


user_main = _load_service_main("user_service", "user_service_main")
app = user_main.app
models = user_main.models

# user main 未导入 create_access_token，从本服务 core.jwt_auth 取
import core.jwt_auth as _user_jwt  # noqa: E402
create_access_token = _user_jwt.create_access_token

import pymysql  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


# ====== 3. 测试库建表 SQL（与 migrations/versions/user/0001_baseline.py 一致）======
SCHEMA_SQL = [
    """
    CREATE TABLE IF NOT EXISTS user_profiles (
        user_id BIGINT PRIMARY KEY,
        display_name VARCHAR(100) NOT NULL DEFAULT '',
        email VARCHAR(100) NOT NULL DEFAULT '',
        avatar_url VARCHAR(255) NOT NULL DEFAULT '',
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS user_schedules (
        user_id BIGINT PRIMARY KEY,
        file_path VARCHAR(255) NOT NULL DEFAULT '',
        start_date DATE NULL,
        parsed_courses JSON NULL,
        uploaded_at DATETIME NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS user_models (
        user_id BIGINT PRIMARY KEY,
        base_url VARCHAR(500) NOT NULL DEFAULT '',
        api_key VARCHAR(500) NOT NULL DEFAULT '',
        model_name VARCHAR(200) NOT NULL DEFAULT '',
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
]

TABLES = ["user_models", "user_schedules", "user_profiles"]


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
                "CREATE DATABASE IF NOT EXISTS lc_user_test "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
            cur.execute("USE lc_user_test")
            for sql in SCHEMA_SQL:
                cur.execute(sql)
            # 旧测试库可能没有 parsed_courses 列（0002 迁移前建的），补齐
            cur.execute(
                "SELECT COUNT(*) AS n FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = 'lc_user_test' AND TABLE_NAME = 'user_schedules' "
                "AND COLUMN_NAME = 'parsed_courses'"
            )
            if cur.fetchone()["n"] == 0:
                cur.execute(
                    "ALTER TABLE user_schedules ADD COLUMN parsed_courses JSON NULL AFTER start_date"
                )
    finally:
        conn.close()
    yield


@pytest.fixture(autouse=True)
def db_clean(db_setup):
    conn = _admin_connect()
    try:
        with conn.cursor() as cur:
            cur.execute("USE lc_user_test")
            for tbl in TABLES:
                cur.execute(f"TRUNCATE TABLE {tbl}")
    finally:
        conn.close()
    # 同步清理临时 UPLOAD_DIR，避免跨测试残留
    for sub in ("avatars", "schedules"):
        d = os.path.join(os.environ["UPLOAD_DIR"], sub)
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
    yield


@pytest.fixture(autouse=True)
def mock_cross_service(monkeypatch):
    """屏蔽 user_service → auth / chat 的跨服务调用。

    用可配置的 MockServiceClient 替换，测试可通过设置
    _mock_responses 来控制返回。
    """

    class _MockResponse:
        def __init__(self, status_code=200, json_data=None, text=""):
            self.status_code = status_code
            self._json = json_data if json_data is not None else {"status": "ok"}
            self.text = text or ""

        def json(self):
            return self._json

    _state = {"auth_delete": (200, {"status": "ok"}),
              "chat_cleanup": (200, {"status": "ok"})}

    class _MockServiceClient:
        def __init__(self, service, token=None, timeout=None):
            self.service = service
            self.token = token

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, path, **kwargs):
            if self.service == "auth" and "/delete" in path:
                sc, jd = _state["auth_delete"]
                return _MockResponse(sc, jd)
            return _MockResponse(200, {"status": "ok"})

        async def delete(self, path, **kwargs):
            if self.service == "chat":
                sc, jd = _state["chat_cleanup"]
                return _MockResponse(sc, jd)
            return _MockResponse(200, {"status": "ok"})

        async def get(self, path, **kwargs):
            return _MockResponse(200, {"status": "ok"})

    monkeypatch.setattr(user_main, "ServiceClient", _MockServiceClient)
    # 暴露状态字典，供测试调整
    yield _state


@pytest.fixture
def mock_service_state(mock_cross_service):
    """暴露 mock 跨服务状态，测试可配置 auth/chat 返回。"""
    return mock_cross_service


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def user_token():
    return create_access_token(3001, "normal_user", "user")


@pytest.fixture
def user_headers(user_token):
    return _hdr(user_token)


@pytest.fixture
def make_token():
    def _make(user_id, username=None, role="user"):
        return create_access_token(user_id, username or f"user{user_id}", role)
    return _make


def make_headers(token: str) -> dict:
    return _hdr(token)
