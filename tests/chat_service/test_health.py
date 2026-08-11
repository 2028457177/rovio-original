"""chat_service 健康检查测试。"""
from tests.chat_service.conftest import chat_main  # noqa: F401


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "chat_service"
    # 测试环境无 Redis 连接
    assert body["redis"] in ("connected", "disconnected")


def test_openapi_docs(client):
    resp = client.get("/docs")
    assert resp.status_code == 200


def test_unknown_endpoint(client):
    resp = client.get("/api/nonexistent")
    assert resp.status_code == 404


def test_conversations_require_auth(client):
    """无 token 访问受保护端点应 401"""
    resp = client.get("/api/conversations")
    assert resp.status_code == 401


def test_invalid_token(client):
    resp = client.get(
        "/api/conversations",
        headers={"Authorization": "Bearer invalid.token.here"},
    )
    assert resp.status_code == 401
