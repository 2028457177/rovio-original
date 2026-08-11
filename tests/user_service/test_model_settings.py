"""模型设置 API（/api/user/model, /internal/user/model-config）。"""


def test_get_model_settings_empty(client, user_headers):
    resp = client.get("/api/user/model", headers=user_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is False
    assert body["base_url"] == ""
    assert body["model_name"] == ""


def test_save_model_settings(client, user_headers):
    resp = client.put("/api/user/model", headers=user_headers, json={
        "base_url": "https://api.deepseek.com",
        "api_key": "sk-abcd1234wxyz",
        "model_name": "deepseek-chat",
    })
    assert resp.status_code == 200, resp.text
    settings = resp.json()["settings"]
    assert settings["configured"] is True
    assert settings["base_url"] == "https://api.deepseek.com"
    assert settings["model_name"] == "deepseek-chat"
    # api_key 脱敏
    assert settings["api_key"] == "sk-a****wxyz"
    assert "abcd1234" not in settings["api_key"]


def test_save_model_requires_auth(client):
    resp = client.put("/api/user/model", json={
        "base_url": "https://x.com", "model_name": "m",
    })
    assert resp.status_code == 401


def test_save_model_rejects_bad_base_url(client, user_headers):
    resp = client.put("/api/user/model", headers=user_headers, json={
        "base_url": "ftp://x.com", "model_name": "m",
    })
    assert resp.status_code == 400


def test_save_model_rejects_empty_model_name(client, user_headers):
    resp = client.put("/api/user/model", headers=user_headers, json={
        "base_url": "https://x.com", "model_name": "  ",
    })
    assert resp.status_code == 400


def test_clear_model_settings(client, user_headers):
    client.put("/api/user/model", headers=user_headers, json={
        "base_url": "https://x.com", "api_key": "sk-abc", "model_name": "m",
    })
    resp = client.delete("/api/user/model", headers=user_headers)
    assert resp.status_code == 200
    body = client.get("/api/user/model", headers=user_headers).json()
    assert body["configured"] is False


def test_internal_model_config_forbidden_without_header(client, user_headers):
    """内部接口需 X-Internal-Call: 1 头，否则 403。"""
    # 先保存配置
    client.put("/api/user/model", headers=user_headers, json={
        "base_url": "https://x.com", "api_key": "sk-secret", "model_name": "m",
    })
    resp = client.get("/internal/user/model-config?user_id=3001")
    assert resp.status_code == 403


def test_internal_model_config_returns_raw_key(client, user_headers):
    """带 X-Internal-Call 头时返回未脱敏 api_key（供 AI 模型层调用）。"""
    client.put("/api/user/model", headers=user_headers, json={
        "base_url": "https://x.com", "api_key": "sk-secret-key", "model_name": "m",
    })
    resp = client.get("/internal/user/model-config?user_id=3001",
                      headers={"X-Internal-Call": "1"})
    assert resp.status_code == 200
    cfg = resp.json()["config"]
    assert cfg["api_key"] == "sk-secret-key"


def test_internal_model_config_not_configured(client):
    """未配置完整时返回 None。"""
    resp = client.get("/internal/user/model-config?user_id=9999",
                      headers={"X-Internal-Call": "1"})
    assert resp.status_code == 200
    assert resp.json()["config"] is None
