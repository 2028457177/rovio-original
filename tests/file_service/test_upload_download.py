"""Word 文件上传 / 下载（/api/upload-word, /api/download/{filename}）。

这两个端点无需 JWT（供前端通用下载链路）。重点测：格式校验、路径穿越防护、
不存在的文件、唯一文件名生成。
"""
import os


def _docx_bytes(content: bytes = b"PK\x03\x04fake-docx") -> bytes:
    return content


def test_upload_word_success(client):
    resp = client.post(
        "/api/upload-word",
        files={"file": ("report.docx", _docx_bytes(), "application/octet-stream")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["original_name"] == "report.docx"
    assert body["filename"].endswith(".docx")
    assert os.path.basename(body["server_path"]) == body["filename"]
    # 文件确实落盘
    assert os.path.exists(body["server_path"])


def test_upload_word_rejects_non_word(client):
    """非 .docx/.doc 后缀被拒。"""
    resp = client.post(
        "/api/upload-word",
        files={"file": ("evil.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 400
    assert "docx" in resp.json()["error"] or "doc" in resp.json()["error"]


def test_upload_word_rejects_pdf(client):
    resp = client.post(
        "/api/upload-word",
        files={"file": ("doc.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert resp.status_code == 400


def test_download_word_success(client):
    up = client.post(
        "/api/upload-word",
        files={"file": ("down.docx", _docx_bytes(b"payload-xyz"), "application/octet-stream")},
    ).json()
    fname = up["filename"]

    resp = client.get(f"/api/download/{fname}")
    assert resp.status_code == 200
    assert resp.content == b"payload-xyz"


def test_download_word_not_found(client):
    resp = client.get("/api/download/nonexistent.docx")
    assert resp.status_code == 404


def test_download_word_rejects_path_traversal(client):
    """路径穿越：路由层（{filename} 不跨段）与 basename/realpath 校验共同拦截。

    含编码斜杠的路径会被路由层直接 404；纯 ".." 文件名由 realpath 校验返回 400。
    """
    # %2f 解码后含 /，路由 {filename} 不匹配跨段 → 404
    resp = client.get("/api/download/..%2f..%2fsecret.docx")
    assert resp.status_code in (400, 404)
    # 客户端可能规范化 ../ 路径，导致落到其他路由 → 非 200 即可
    resp2 = client.get("/api/download/../secret")
    assert resp2.status_code in (400, 404)
