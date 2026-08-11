"""用户管理 API（/api/admin/users 系列）。

覆盖：
- 用户列表（auth + user 资料合并）
- 用户会话查看（调 chat_service）
- 用户注销级联（user → chat → auth）
- 重置密码（密码长度校验 + 调 auth_service）
- 跨服务调用失败回退
"""


# ==================== 用户列表 ====================

def test_get_users_success(client, admin_headers, mock_service_state):
    """默认 mock：返回 2 个用户（1 admin + 1 user），资料合并后含 display_name。"""
    resp = client.get("/api/admin/users", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    users = resp.json()["users"]
    assert len(users) == 2
    alice = next(u for u in users if u["id"] == 2)
    assert alice["username"] == "alice"
    assert alice["display_name"] == "Alice"  # 来自 mock user_profile


def test_get_users_auth_service_fails(client, admin_headers, mock_service_state):
    """auth_service 拉取用户列表失败 → 502。"""
    mock_service_state["auth_users"] = (500, {"error": "auth 不可用"})
    resp = client.get("/api/admin/users", headers=admin_headers)
    assert resp.status_code == 502
    assert "error" in resp.json()


def test_get_users_user_service_fails_non_blocking(client, admin_headers, mock_service_state):
    """user_service 资料补全失败 → 不影响主流程，display_name 为空字符串。"""
    mock_service_state["user_profile"] = (500, {"error": "user 不可用"})
    resp = client.get("/api/admin/users", headers=admin_headers)
    assert resp.status_code == 200
    alice = next(u for u in resp.json()["users"] if u["id"] == 2)
    assert alice["display_name"] == ""
    assert alice["email"] == ""


# ==================== 用户会话 ====================

def test_get_user_conversations_success(client, admin_headers, mock_service_state):
    resp = client.get("/api/admin/users/2/conversations", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    convs = resp.json()["conversations"]
    assert len(convs) == 1
    assert convs[0]["id"] == "c1"


def test_get_user_conversations_chat_fails(client, admin_headers, mock_service_state):
    """chat_service 不可用 → 502。"""
    mock_service_state["chat_conversations"] = (500, {"error": "chat 不可用"})
    resp = client.get("/api/admin/users/2/conversations", headers=admin_headers)
    assert resp.status_code == 502


# ==================== 注销用户 ====================

def test_delete_user_success(client, admin_headers, mock_service_state):
    """级联清理：user → chat → auth 全成功 → 200。"""
    resp = client.post("/api/admin/users/2/delete", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "ok"


def test_delete_user_user_service_fails(client, admin_headers, mock_service_state):
    """user_service 清理失败 → 400，不继续调 auth。"""
    mock_service_state["user_delete"] = (400, {"error": "用户不存在"})
    resp = client.post("/api/admin/users/2/delete", headers=admin_headers)
    assert resp.status_code == 400
    # call_service 包装为 {"error": "user 返回 400", "detail": <原始 body>}
    assert "user" in resp.json()["error"]
    assert "400" in resp.json()["error"]


def test_delete_user_chat_cleanup_failure_non_blocking(client, admin_headers, mock_service_state):
    """chat_service 清理失败 → 仅告警，仍继续调 auth，最终 200。"""
    mock_service_state["chat_cleanup"] = (500, {"error": "chat 不可用"})
    resp = client.post("/api/admin/users/2/delete", headers=admin_headers)
    assert resp.status_code == 200


def test_delete_user_auth_fails(client, admin_headers, mock_service_state):
    """user/chat 成功但 auth 失败 → 400。"""
    mock_service_state["auth_delete"] = (400, {"error": "不能删除管理员"})
    resp = client.post("/api/admin/users/1/delete", headers=admin_headers)
    assert resp.status_code == 400
    # call_service 包装为 {"error": "auth 返回 400", "detail": <原始 body>}
    assert "auth" in resp.json()["error"]
    assert "400" in resp.json()["error"]


# ==================== 重置密码 ====================

def test_reset_password_success(client, admin_headers, mock_service_state):
    resp = client.post("/api/admin/users/2/reset-password",
                       headers=admin_headers, json={"password": "newpass123"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "ok"


def test_reset_password_rejects_short(client, admin_headers):
    """密码 < 6 字符 → 400，不调 auth。"""
    resp = client.post("/api/admin/users/2/reset-password",
                       headers=admin_headers, json={"password": "12345"})
    assert resp.status_code == 400
    assert "密码" in resp.json()["error"]


def test_reset_password_uses_default_when_missing(client, admin_headers, mock_service_state):
    """不传 password → 使用默认值 123456789（≥6 字符）。"""
    resp = client.post("/api/admin/users/2/reset-password", headers=admin_headers, json={})
    assert resp.status_code == 200


def test_reset_password_auth_fails(client, admin_headers, mock_service_state):
    mock_service_state["auth_reset_pwd"] = (400, {"error": "用户不存在"})
    resp = client.post("/api/admin/users/999/reset-password",
                       headers=admin_headers, json={"password": "newpass123"})
    assert resp.status_code == 400
    assert "auth" in resp.json()["error"]
    assert "400" in resp.json()["error"]
