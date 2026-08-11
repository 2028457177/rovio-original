"""AIRAGAgent.utils.paths 路径工具测试。

注意：paths.py 会在 import 时创建 PROJECT_ROOT/uploads 和 PROJECT_ROOT/workspace。
为避免污染真实项目目录，测试用 monkeypatch 把 WORKSPACE_DIR 重定向到 tmp_path。
"""
import shutil
from datetime import date, timedelta
from pathlib import Path

import pytest

from AIRAGAgent.utils import paths


def test_get_user_workspace_creates_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "WORKSPACE_DIR", tmp_path)
    ws = paths.get_user_workspace(123)
    assert ws == tmp_path / "123"
    assert ws.exists()
    assert ws.is_dir()


def test_get_user_workspace_empty_id_defaults_to_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "WORKSPACE_DIR", tmp_path)
    ws = paths.get_user_workspace(None)
    assert ws == tmp_path / "0"
    assert ws.exists()


def test_get_user_workspace_zero_id(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "WORKSPACE_DIR", tmp_path)
    ws = paths.get_user_workspace(0)
    assert ws == tmp_path / "0"


def test_get_daily_workspace_today(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "WORKSPACE_DIR", tmp_path)
    today = date.today()
    daily = paths.get_daily_workspace(456)
    expected = tmp_path / "456" / today.strftime("%Y%m%d")
    assert daily == expected
    assert daily.exists()


def test_get_daily_workspace_specific_day(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "WORKSPACE_DIR", tmp_path)
    day = date(2026, 7, 15)
    daily = paths.get_daily_workspace(789, day)
    assert daily == tmp_path / "789" / "20260715"
    assert daily.exists()


def test_get_screenshot_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "WORKSPACE_DIR", tmp_path)
    day = date(2026, 8, 1)
    ss = paths.get_screenshot_dir(100, day)
    assert ss == tmp_path / "100" / "20260801" / "screenshots"
    assert ss.exists()


def test_get_screenshot_dir_default_today(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "WORKSPACE_DIR", tmp_path)
    today = date.today()
    ss = paths.get_screenshot_dir(200)
    assert ss == tmp_path / "200" / today.strftime("%Y%m%d") / "screenshots"


# ═══════════════════════════════════════════════
# cleanup_old_daily_workspaces
# ═══════════════════════════════════════════════

def test_cleanup_removes_old_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "WORKSPACE_DIR", tmp_path)
    # 用户 1 的目录
    user_dir = tmp_path / "1"
    user_dir.mkdir()

    # 35 天前的目录（应被删）
    old_date = date.today() - timedelta(days=35)
    old_dir = user_dir / old_date.strftime("%Y%m%d")
    old_dir.mkdir()
    (old_dir / "file.txt").write_text("old")

    # 今天的目录（应保留）
    today_dir = user_dir / date.today().strftime("%Y%m%d")
    today_dir.mkdir()

    # 10 天前的目录（30 天阈值内，应保留）
    recent_date = date.today() - timedelta(days=10)
    recent_dir = user_dir / recent_date.strftime("%Y%m%d")
    recent_dir.mkdir()

    removed = paths.cleanup_old_daily_workspaces(max_days=30)
    assert removed == 1
    assert not old_dir.exists()
    assert today_dir.exists()
    assert recent_dir.exists()


def test_cleanup_keeps_non_date_dirs(tmp_path, monkeypatch):
    """非 8 位数字命名的目录不应被清理"""
    monkeypatch.setattr(paths, "WORKSPACE_DIR", tmp_path)
    user_dir = tmp_path / "2"
    user_dir.mkdir()
    # 非日期目录
    (user_dir / "screenshots").mkdir()
    (user_dir / "custom").mkdir()
    # 过期日期目录
    old = user_dir / "20200101"
    old.mkdir()

    removed = paths.cleanup_old_daily_workspaces(max_days=30)
    assert removed == 1
    assert (user_dir / "screenshots").exists()
    assert (user_dir / "custom").exists()
    assert not old.exists()


def test_cleanup_ignores_dot_underscore_dirs(tmp_path, monkeypatch):
    """以 . 或 _ 开头的目录跳过"""
    monkeypatch.setattr(paths, "WORKSPACE_DIR", tmp_path)
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "_temp").mkdir()
    removed = paths.cleanup_old_daily_workspaces()
    assert removed == 0


def test_cleanup_invalid_date_format_skipped(tmp_path, monkeypatch):
    """8 位数字但非有效日期的目录跳过"""
    monkeypatch.setattr(paths, "WORKSPACE_DIR", tmp_path)
    user_dir = tmp_path / "3"
    user_dir.mkdir()
    (user_dir / "20261345").mkdir()  # 13 月不存在
    removed = paths.cleanup_old_daily_workspaces()
    assert removed == 0
    assert (user_dir / "20261345").exists()


def test_cleanup_custom_max_days(tmp_path, monkeypatch):
    """自定义 max_days 阈值"""
    monkeypatch.setattr(paths, "WORKSPACE_DIR", tmp_path)
    user_dir = tmp_path / "4"
    user_dir.mkdir()
    # 3 天前
    d3 = user_dir / (date.today() - timedelta(days=3)).strftime("%Y%m%d")
    d3.mkdir()
    # 1 天前
    d1 = user_dir / (date.today() - timedelta(days=1)).strftime("%Y%m%d")
    d1.mkdir()

    # 阈值 2 天：3 天前的删，1 天前的留
    removed = paths.cleanup_old_daily_workspaces(max_days=2)
    assert removed == 1
    assert not d3.exists()
    assert d1.exists()


def test_cleanup_empty_workspace(tmp_path, monkeypatch):
    """空 workspace 不报错"""
    monkeypatch.setattr(paths, "WORKSPACE_DIR", tmp_path)
    removed = paths.cleanup_old_daily_workspaces()
    assert removed == 0


def test_cleanup_boundary_exactly_30_days(tmp_path, monkeypatch):
    """恰好 30 天前的目录应被保留（< cutoff 才删）"""
    monkeypatch.setattr(paths, "WORKSPACE_DIR", tmp_path)
    user_dir = tmp_path / "5"
    user_dir.mkdir()
    boundary = user_dir / (date.today() - timedelta(days=30)).strftime("%Y%m%d")
    boundary.mkdir()
    removed = paths.cleanup_old_daily_workspaces(max_days=30)
    assert removed == 0
    assert boundary.exists()


def test_cleanup_boundary_31_days(tmp_path, monkeypatch):
    """31 天前的目录应被删"""
    monkeypatch.setattr(paths, "WORKSPACE_DIR", tmp_path)
    user_dir = tmp_path / "6"
    user_dir.mkdir()
    old = user_dir / (date.today() - timedelta(days=31)).strftime("%Y%m%d")
    old.mkdir()
    removed = paths.cleanup_old_daily_workspaces(max_days=30)
    assert removed == 1
    assert not old.exists()
