"""课表 API（/api/user/schedule, /api/user/schedule/start-date, /api/schedules/{filename}）。

upload_schedule 用 pandas 预校验 Excel 列名（header=2, index_col=0, 需含 星期一~星期天），
故需构造合法 xlsx。
"""
import io

from openpyxl import Workbook


def _make_schedule_xlsx() -> bytes:
    """构造合法课表 xlsx：第 3 行（header=2）为 星期一~星期天。"""
    wb = Workbook()
    ws = wb.active
    # row 0 / 1：标题行（pandas header=2 跳过）
    ws.append(["课表标题"])
    ws.append(["备注行"])
    # row 2：header（index_col=0 + 星期一~星期天）
    ws.append(["节次", "星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期天"])
    # row 3：一行数据
    ws.append(["1", "语文", "数学", "英语", "物理", "化学", "休息", "休息"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_upload_schedule_success(client, user_headers):
    xlsx = _make_schedule_xlsx()
    resp = client.post(
        "/api/user/schedule",
        headers=user_headers,
        files={"file": ("s.xlsx", xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"start_date": "2026-09-01"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    assert body["start_date"] == "2026-09-01"
    assert body["schedule_url"].startswith("/api/schedules/schedule_3001.xlsx")


def test_upload_schedule_requires_auth(client):
    resp = client.post("/api/user/schedule", files={"file": ("s.xlsx", b"x")}, data={"start_date": "2026-09-01"})
    assert resp.status_code == 401


def test_upload_schedule_rejects_bad_ext(client, user_headers):
    resp = client.post(
        "/api/user/schedule",
        headers=user_headers,
        files={"file": ("s.csv", b"a,b", "text/csv")},
        data={"start_date": "2026-09-01"},
    )
    assert resp.status_code == 400


def test_upload_schedule_rejects_bad_date(client, user_headers):
    resp = client.post(
        "/api/user/schedule",
        headers=user_headers,
        files={"file": ("s.xlsx", _make_schedule_xlsx(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"start_date": "2026/09/01"},
    )
    assert resp.status_code == 400


def test_upload_schedule_rejects_too_large(client, user_headers):
    big = b"\x00" * (2 * 1024 * 1024 + 1)
    resp = client.post(
        "/api/user/schedule",
        headers=user_headers,
        files={"file": ("s.xlsx", big,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"start_date": "2026-09-01"},
    )
    assert resp.status_code == 400


def test_upload_schedule_rejects_missing_columns(client, user_headers):
    """Excel 缺少星期列被拒。"""
    wb = Workbook()
    ws = wb.active
    ws.append(["标题"])
    ws.append(["备注"])
    ws.append(["节次", "周一", "周二"])  # 列名不对
    ws.append(["1", "语文", "数学"])
    buf = io.BytesIO()
    wb.save(buf)
    resp = client.post(
        "/api/user/schedule",
        headers=user_headers,
        files={"file": ("s.xlsx", buf.getvalue(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"start_date": "2026-09-01"},
    )
    assert resp.status_code == 400
    assert "星期" in resp.json()["error"]


def test_get_schedule_settings_empty(client, user_headers):
    resp = client.get("/api/user/schedule", headers=user_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["uploaded"] is False
    assert body["file_path"] is None


def test_get_schedule_after_upload(client, user_headers):
    client.post(
        "/api/user/schedule",
        headers=user_headers,
        files={"file": ("s.xlsx", _make_schedule_xlsx(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"start_date": "2026-09-01"},
    )
    resp = client.get("/api/user/schedule", headers=user_headers)
    body = resp.json()
    assert body["uploaded"] is True
    assert body["start_date"] == "2026-09-01"
    assert body["schedule_url"] == "/api/schedules/schedule_3001.xlsx"


def test_update_start_date_only(client, user_headers):
    resp = client.patch(
        "/api/user/schedule/start-date",
        headers=user_headers,
        json={"start_date": "2026-09-10"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["start_date"] == "2026-09-10"


def test_update_start_date_bad_format(client, user_headers):
    resp = client.patch(
        "/api/user/schedule/start-date",
        headers=user_headers,
        json={"start_date": "2026/09/10"},
    )
    assert resp.status_code == 400


def test_update_start_date_clear(client, user_headers):
    """start_date=null 清除日期。"""
    resp = client.patch(
        "/api/user/schedule/start-date",
        headers=user_headers,
        json={"start_date": None},
    )
    assert resp.status_code == 200


def test_delete_schedule(client, user_headers):
    client.post(
        "/api/user/schedule",
        headers=user_headers,
        files={"file": ("s.xlsx", _make_schedule_xlsx(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"start_date": "2026-09-01"},
    )
    resp = client.delete("/api/user/schedule", headers=user_headers)
    assert resp.status_code == 200
    # 删除后查询应为空
    body = client.get("/api/user/schedule", headers=user_headers).json()
    assert body["uploaded"] is False


def test_serve_schedule(client, user_headers):
    client.post(
        "/api/user/schedule",
        headers=user_headers,
        files={"file": ("s.xlsx", _make_schedule_xlsx(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"start_date": "2026-09-01"},
    )
    resp = client.get("/api/schedules/schedule_3001.xlsx")
    assert resp.status_code == 200
    assert len(resp.content) > 0


def test_serve_schedule_not_found(client):
    resp = client.get("/api/schedules/nope.xlsx")
    assert resp.status_code == 404


def test_serve_schedule_rejects_traversal(client):
    resp = client.get("/api/schedules/..%2fevil.xlsx")
    assert resp.status_code in (400, 404)
