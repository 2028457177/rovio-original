"""健康检查烟雾测试。"""


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "file_service"
    assert "redis" in body
