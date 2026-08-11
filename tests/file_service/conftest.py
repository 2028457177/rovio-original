"""file_service 测试固件。

file_service 无独立数据库（文件系统即存储），故只需把 UPLOAD_DIR / WORKSPACE_DIR
重定向到临时目录，避免污染真实 uploads/ 与 workspace/。
"""
import os
import sys
import shutil
import tempfile

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# ====== 1. 环境变量（必须在 import main 之前设置）======
_tmp_root = tempfile.mkdtemp(prefix="lc_file_test_")
os.environ["UPLOAD_DIR"] = os.path.join(_tmp_root, "uploads")
os.environ["WORKSPACE_DIR"] = os.path.join(_tmp_root, "workspace")
os.environ.setdefault("JWT_SECRET_KEY", "lc-course-secret-key-2025")
os.environ.setdefault("JWT_TOKEN_EXPIRE_HOURS", "72")
os.environ.pop("ADMIN_ALLOWED_IPS", None)


# ====== 2. 加载 main（唯一模块名，清理陈旧 core 缓存）======
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


file_main = _load_service_main("file_service", "file_service_main")
app = file_main.app

# file main 未导入 create_access_token，从本服务 core.jwt_auth 取
import core.jwt_auth as _file_jwt  # noqa: E402
create_access_token = _file_jwt.create_access_token

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


# ====== 3. 固件 ======

@pytest.fixture(autouse=True)
def clean_workspace():
    """每个测试前清空临时 UPLOAD_DIR / WORKSPACE_DIR，保证测试间隔离。"""
    for d in (os.environ["UPLOAD_DIR"], os.environ["WORKSPACE_DIR"]):
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d, exist_ok=True)
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def user_token():
    """普通用户 JWT（user_id=2001）。"""
    return create_access_token(2001, "normal_user", "user")


@pytest.fixture
def other_user_token():
    """另一个普通用户 JWT（user_id=2002），用于测试用户隔离。"""
    return create_access_token(2002, "other_user", "user")


@pytest.fixture
def user_headers(user_token):
    return _hdr(user_token)


@pytest.fixture
def make_token():
    """工厂：为指定 user_id 签发 token。"""
    def _make(user_id, username=None, role="user"):
        return create_access_token(user_id, username or f"user{user_id}", role)
    return _make


@pytest.fixture
def workspace_root():
    """返回 user_id=2001 的工作区根目录（已由 main 创建）。"""
    return os.path.join(os.environ["WORKSPACE_DIR"], "2001")
