"""内部接口（/internal/user/profile, /internal/user/delete, /internal/user/{user_id}）。

供 auth_service 注册时创建资料 / 注销时清理 user 数据。
"""


def test_internal_create_profile(client):
    resp = client.post("/internal/user/profile", json={"user_id": 3001, "display_name": "新用户"})
    assert resp.status_code == 200, resp.text
    # 创建后可查到
    profile = client.get("/internal/user/profile?user_id=3001").json()["profile"]
    assert profile["display_name"] == "新用户"


def test_internal_create_profile_idempotent(client):
    """INSERT IGNORE：重复创建不报错。"""
    client.post("/internal/user/profile", json={"user_id": 3001, "display_name": "A"})
    resp = client.post("/internal/user/profile", json={"user_id": 3001, "display_name": "B"})
    assert resp.status_code == 200
    # 第二次 INSERT IGNORE 不覆盖原值
    profile = client.get("/internal/user/profile?user_id=3001").json()["profile"]
    assert profile["display_name"] == "A"


def test_internal_delete_user_by_query(client, user_headers):
    """POST /internal/user/delete?user_id=X 清理 user 数据。"""
    # 先写入资料 + 模型配置
    client.patch("/api/user/profile", headers=user_headers, json={"display_name": "待删"})
    client.put("/api/user/model", headers=user_headers, json={
        "base_url": "https://x.com", "api_key": "k", "model_name": "m"})

    resp = client.post("/internal/user/delete?user_id=3001")
    assert resp.status_code == 200
    # 资料已清
    profile = client.get("/internal/user/profile?user_id=3001").json()["profile"]
    assert profile["display_name"] == ""


def test_internal_delete_user_by_path(client, user_headers):
    """DELETE /internal/user/{user_id} 清理 user 数据。"""
    client.patch("/api/user/profile", headers=user_headers, json={"display_name": "待删2"})

    resp = client.delete("/internal/user/3001")
    assert resp.status_code == 200
    profile = client.get("/internal/user/profile?user_id=3001").json()["profile"]
    assert profile["display_name"] == ""
