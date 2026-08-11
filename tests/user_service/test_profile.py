"""用户资料 API（/api/user/profile, /api/user/avatar, /api/avatars/{filename}）。"""
import os


def test_update_profile_requires_auth(client):
    resp = client.patch("/api/user/profile", json={"display_name": "x"})
    assert resp.status_code == 401


def test_update_profile_display_name(client, user_headers):
    resp = client.patch("/api/user/profile", headers=user_headers,
                        json={"display_name": "小明", "email": "x@y.com"})
    assert resp.status_code == 200, resp.text
    user = resp.json()["user"]
    assert user["display_name"] == "小明"
    assert user["email"] == "x@y.com"


def test_update_profile_rejects_empty_display_name(client, user_headers):
    """display_name 传空字符串被拒。"""
    resp = client.patch("/api/user/profile", headers=user_headers,
                        json={"display_name": "   "})
    assert resp.status_code == 400


def test_update_profile_only_email(client, user_headers):
    """仅更新 email，display_name 不传。"""
    resp = client.patch("/api/user/profile", headers=user_headers, json={"email": "a@b.com"})
    assert resp.status_code == 200
    assert resp.json()["user"]["email"] == "a@b.com"


def test_get_profile_internal(client):
    """内部接口：查询用户资料（不存在返回默认值）。"""
    resp = client.get("/internal/user/profile?user_id=3001")
    assert resp.status_code == 200
    profile = resp.json()["profile"]
    assert profile["display_name"] == ""
    assert profile["email"] == ""
    assert profile["avatar_url"] == ""


def test_upload_avatar_success(client, user_headers):
    resp = client.post(
        "/api/user/avatar",
        headers=user_headers,
        files={"avatar": ("a.png", b"\x89PNG\r\n", "image/png")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    assert body["avatar_url"].startswith("/api/avatars/avatar_3001_")


def test_upload_avatar_rejects_bad_type(client, user_headers):
    resp = client.post(
        "/api/user/avatar",
        headers=user_headers,
        files={"avatar": ("a.bmp", b"BM", "image/bmp")},
    )
    assert resp.status_code == 400


def test_upload_avatar_too_large(client, user_headers):
    big = b"\x00" * (5 * 1024 * 1024 + 1)
    resp = client.post(
        "/api/user/avatar",
        headers=user_headers,
        files={"avatar": ("a.png", big, "image/png")},
    )
    assert resp.status_code == 400


def test_serve_avatar(client, user_headers):
    up = client.post(
        "/api/user/avatar",
        headers=user_headers,
        files={"avatar": ("a.png", b"\x89PNG\r\n", "image/png")},
    ).json()
    fname = up["avatar_url"].split("/")[-1]

    resp = client.get(f"/api/avatars/{fname}")
    assert resp.status_code == 200
    assert resp.content == b"\x89PNG\r\n"


def test_serve_avatar_not_found(client):
    resp = client.get("/api/avatars/nope.png")
    assert resp.status_code == 404


def test_serve_avatar_rejects_traversal(client):
    resp = client.get("/api/avatars/..%2fevil.png")
    assert resp.status_code in (400, 404)
