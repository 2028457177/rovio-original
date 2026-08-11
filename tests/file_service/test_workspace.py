"""AI 工作区文件浏览（/api/file/list, /api/file/download, /api/file/preview）。

这三个端点均需 JWT，且按 user_id 隔离到 workspace/{user_id}/。
重点测：鉴权、路径穿越、用户隔离、隐藏目录过滤、目录优先排序、文件下载/预览。
"""
import os


def _write_file(path: str, content: bytes = b"hello") -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)
    return path


def _hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ───────────────────────── 鉴权 ─────────────────────────

def test_list_requires_auth(client):
    resp = client.get("/api/file/list")
    assert resp.status_code == 401


def test_download_requires_auth(client):
    resp = client.get("/api/file/download?path=a.txt")
    assert resp.status_code == 401


def test_preview_requires_auth(client):
    resp = client.get("/api/file/preview?path=a.txt")
    assert resp.status_code == 401


def test_list_invalid_token(client):
    resp = client.get("/api/file/list", headers={"Authorization": "Bearer not-a-jwt"})
    assert resp.status_code == 401


# ───────────────────────── 列表 ─────────────────────────

def test_list_empty_root(client, user_headers, workspace_root):
    resp = client.get("/api/file/list", headers=user_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # 根目录：target.relative_to(base) 返回 Path('.')，故 path/parent 均为 "."
    assert body["path"] in ("", ".")
    assert body["entries"] == []


def test_list_lists_files_and_dirs(client, user_headers, workspace_root):
    _write_file(os.path.join(workspace_root, "a.txt"), b"aaa")
    _write_file(os.path.join(workspace_root, "sub", "b.md"), b"bbb")

    resp = client.get("/api/file/list", headers=user_headers)
    body = resp.json()
    names = [e["name"] for e in body["entries"]]
    assert set(names) == {"a.txt", "sub"}
    # 目录优先
    dirs = [e for e in body["entries"] if e["is_dir"]]
    files = [e for e in body["entries"] if not e["is_dir"]]
    assert body["entries"].index(dirs[0]) < body["entries"].index(files[0])


def test_list_entry_metadata(client, user_headers, workspace_root):
    _write_file(os.path.join(workspace_root, "pic.PNG"), b"\x89PNG")
    resp = client.get("/api/file/list", headers=user_headers)
    entry = resp.json()["entries"][0]
    assert entry["name"] == "pic.PNG"
    assert entry["ext"] == ".png"
    assert entry["is_image"] is True
    assert entry["is_text"] is False
    assert entry["size"] == 4
    assert "mtime" in entry
    assert entry["path"] == "pic.PNG"


def test_list_subdir_parent(client, user_headers, workspace_root):
    _write_file(os.path.join(workspace_root, "sub", "c.txt"), b"c")
    resp = client.get("/api/file/list?path=sub", headers=user_headers)
    body = resp.json()
    assert body["path"] == "sub"
    # Path("sub").parent == Path(".")，故 parent 为 "."
    assert body["parent"] in ("", ".")
    assert body["entries"][0]["name"] == "c.txt"


def test_list_hidden_dirs_filtered(client, user_headers, workspace_root):
    """dotfile 目录（含 .playwright）必须被隐藏。"""
    _write_file(os.path.join(workspace_root, ".playwright", "bin.txt"), b"x")
    _write_file(os.path.join(workspace_root, ".cache", "y"), b"y")
    _write_file(os.path.join(workspace_root, "visible.txt"), b"v")

    resp = client.get("/api/file/list", headers=user_headers)
    names = [e["name"] for e in resp.json()["entries"]]
    assert names == ["visible.txt"]


def test_list_nonexistent_path(client, user_headers):
    resp = client.get("/api/file/list?path=no_such_dir", headers=user_headers)
    assert resp.status_code == 400


def test_list_path_is_file_not_dir(client, user_headers, workspace_root):
    _write_file(os.path.join(workspace_root, "afile.txt"), b"x")
    resp = client.get("/api/file/list?path=afile.txt", headers=user_headers)
    assert resp.status_code == 400


# ───────────────────────── 路径穿越 ─────────────────────────

def test_list_rejects_traversal(client, user_headers):
    resp = client.get("/api/file/list?path=../../etc", headers=user_headers)
    assert resp.status_code == 400


def test_list_rejects_dotdot_in_subpath(client, user_headers, workspace_root):
    _write_file(os.path.join(workspace_root, "ok.txt"), b"x")
    # sub/../ok 应被拒（.. 分段）
    resp = client.get("/api/file/list?path=sub/..", headers=user_headers)
    assert resp.status_code == 400


def test_download_rejects_traversal(client, user_headers):
    resp = client.get("/api/file/download?path=../../etc/passwd", headers=user_headers)
    assert resp.status_code == 404


# ───────────────────────── 用户隔离 ─────────────────────────

def test_user_isolation(client, make_token, workspace_root):
    """用户 A 的文件对用户 B 不可见、不可下载。"""
    other_root = os.path.join(os.environ["WORKSPACE_DIR"], "2002")
    _write_file(os.path.join(workspace_root, "mine.txt"), b"mine")
    _write_file(os.path.join(other_root, "theirs.txt"), b"theirs")

    token_a = make_token(2001, "a")
    token_b = make_token(2002, "b")

    # A 看不到 B 的文件
    resp_a = client.get("/api/file/list", headers=_hdr(token_a))
    names_a = [e["name"] for e in resp_a.json()["entries"]]
    assert names_a == ["mine.txt"]

    resp_b = client.get("/api/file/list", headers=_hdr(token_b))
    names_b = [e["name"] for e in resp_b.json()["entries"]]
    assert names_b == ["theirs.txt"]

    # A 直接请求 B 的文件路径 → 路径不在 A 的工作区，404
    dl = client.get("/api/file/download?path=theirs.txt", headers=_hdr(token_a))
    assert dl.status_code == 404


# ───────────────────────── 下载 / 预览 ─────────────────────────

def test_download_file(client, user_headers, workspace_root):
    _write_file(os.path.join(workspace_root, "data.csv"), b"a,b\n1,2")
    resp = client.get("/api/file/download?path=data.csv", headers=user_headers)
    assert resp.status_code == 200
    assert resp.content == b"a,b\n1,2"
    assert "text/plain" in resp.headers.get("content-type", "")


def test_download_image(client, user_headers, workspace_root):
    _write_file(os.path.join(workspace_root, "img.jpg"), b"\xff\xd8\xff")
    resp = client.get("/api/file/download?path=img.jpg", headers=user_headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"


def test_download_nonexistent(client, user_headers):
    resp = client.get("/api/file/download?path=ghost.txt", headers=user_headers)
    assert resp.status_code == 404


def test_download_directory(client, user_headers, workspace_root):
    os.makedirs(os.path.join(workspace_root, "adir"), exist_ok=True)
    resp = client.get("/api/file/download?path=adir", headers=user_headers)
    assert resp.status_code == 400


def test_preview_inline(client, user_headers, workspace_root):
    _write_file(os.path.join(workspace_root, "note.md"), b"# title")
    resp = client.get("/api/file/preview?path=note.md", headers=user_headers)
    assert resp.status_code == 200
    assert resp.content == b"# title"
    # inline 预览：Content-Disposition 含 inline
    cd = resp.headers.get("content-disposition", "")
    assert "inline" in cd


def test_preview_binary_octet_stream(client, user_headers, workspace_root):
    _write_file(os.path.join(workspace_root, "blob.bin"), b"\x00\x01\x02")
    resp = client.get("/api/file/preview?path=blob.bin", headers=user_headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/octet-stream"
