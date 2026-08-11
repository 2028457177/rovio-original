"""管理员鉴权：所有 /api/admin/* 路由必须 admin 角色 JWT。

边界：
- 无 token → 401
- 普通用户 token → 403
- 管理员 token → 2xx
"""


def test_admin_endpoint_requires_token(client):
    resp = client.get("/api/admin/users")
    assert resp.status_code == 401


def test_admin_endpoint_rejects_normal_user(client, normal_headers):
    """普通用户 role=user 访问被拒。"""
    resp = client.get("/api/admin/users", headers=normal_headers)
    assert resp.status_code == 403


def test_admin_endpoint_accepts_admin(client, admin_headers):
    """管理员 role=admin 通过鉴权。"""
    resp = client.get("/api/admin/users", headers=admin_headers)
    assert resp.status_code == 200


def test_stats_overview_requires_admin(client, normal_headers):
    resp = client.get("/api/admin/stats/overview", headers=normal_headers)
    assert resp.status_code == 403


def test_stats_tools_requires_admin(client, normal_headers):
    resp = client.get("/api/admin/stats/tools", headers=normal_headers)
    assert resp.status_code == 403


def test_reset_password_requires_admin(client, normal_headers):
    resp = client.post("/api/admin/users/2/reset-password",
                       headers=normal_headers, json={"password": "newpass"})
    assert resp.status_code == 403
