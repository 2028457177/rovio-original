"""注销账号（/api/user/account）。

调用 auth_service 删除认证记录（mock）→ 成功则清理 user 数据 + 调 chat_service（mock，失败不阻塞）。
httpx 的 TestClient.delete() 不支持 json body，统一用 client.request("DELETE", ...) 发请求体。
"""


def test_delete_account_success(client, user_headers, mock_service_state):
    # 默认 mock 返回 200
    resp = client.request("DELETE", "/api/user/account", headers=user_headers, json={"password": "123456"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "ok"


def test_delete_account_requires_auth(client):
    resp = client.request("DELETE", "/api/user/account", json={"password": "123456"})
    assert resp.status_code == 401


def test_delete_account_auth_service_fails(client, user_headers, mock_service_state):
    """auth_service 返回非 200 → 400。"""
    mock_service_state["auth_delete"] = (400, {"error": "不能删除管理员"})
    resp = client.request("DELETE", "/api/user/account", headers=user_headers, json={"password": "123456"})
    assert resp.status_code == 400
    assert "管理员" in resp.json()["error"]


def test_delete_account_cleans_user_data(client, user_headers, mock_service_state):
    """注销后 user 侧数据（资料/模型配置）被清理。"""
    client.patch("/api/user/profile", headers=user_headers, json={"display_name": "即将注销"})
    client.put("/api/user/model", headers=user_headers, json={
        "base_url": "https://x.com", "api_key": "k", "model_name": "m"})

    resp = client.request("DELETE", "/api/user/account", headers=user_headers, json={"password": "123456"})
    assert resp.status_code == 200
    profile = client.get("/internal/user/profile?user_id=3001").json()["profile"]
    assert profile["display_name"] == ""


def test_delete_account_chat_cleanup_failure_non_blocking(client, user_headers, mock_service_state):
    """chat_service 清理失败不阻塞注销（仍返回 200）。"""
    mock_service_state["chat_cleanup"] = (500, {"error": "chat 不可用"})
    resp = client.request("DELETE", "/api/user/account", headers=user_headers, json={"password": "123456"})
    assert resp.status_code == 200
