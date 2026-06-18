"""
firebase_service.py
-------------------
Firebase Realtime Database 資料存取模組。
依賴：utils

使用 firebase_admin.db（Realtime Database），
與 civics_app.py 相同的初始化模式。

提供：
- init_firebase()           : 初始化 Firebase（cache_resource）
- track_visitor()           : 訪客人數原子累加
- get_messages()            : 取得留言列表（分頁）
- get_total_message_count() : 取得留言總數
- create_message()          : 新增留言
- hide_message()            : 隱藏留言
- unhide_message()          : 取消隱藏
- delete_message()          : 刪除留言
- is_duplicate_message()    : 重複留言檢查
- get_announcements()       : 取得公告（前台）
- get_all_announcements()   : 取得全部公告（管理員）
- create_announcement()     : 新增公告
- update_announcement()     : 修改公告
- delete_announcement()     : 刪除公告
- toggle_announcement()     : 切換公告啟用狀態
"""

import logging
import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import firebase_admin
import streamlit as st
from firebase_admin import credentials
from firebase_admin import db as firebase_db

from utils import get_client_ip_hash, sanitize_input

logger = logging.getLogger(__name__)

# Realtime Database 路徑
_PATH_MESSAGES: str = "motherboard/messages"
_PATH_ANNOUNCEMENTS: str = "motherboard/announcements"
_PATH_VISITORS: str = "motherboard/visitor_counts"


# ─── Firebase 初始化 ───────────────────────────────────────────────────────────

@st.cache_resource
def init_firebase():
    """
    初始化 Firebase Admin SDK（Realtime Database）。
    與 civics_app.py 相同模式，使用 st.secrets["firebase"]。
    cache_resource 確保全生命週期只初始化一次。

    Secrets 需包含 database_url 欄位：
        [firebase]
        database_url = "https://your-project-default-rtdb.firebaseio.com"
        ...其餘 Service Account 欄位

    Returns:
        firebase_admin App 實例
    """
    if firebase_admin._apps:
        return firebase_admin.get_app()

    s = st.secrets["firebase"]
    cert_dict = {
        "type":                        s["type"],
        "project_id":                  s["project_id"],
        "private_key_id":              s["private_key_id"],
        "private_key":                 s["private_key"].replace("\\n", "\n"),
        "client_email":                s["client_email"],
        "client_id":                   s["client_id"],
        "auth_uri":                    s["auth_uri"],
        "token_uri":                   s["token_uri"],
        "client_x509_cert_url":        s.get("client_x509_cert_url", ""),
        "auth_provider_x509_cert_url": s.get("auth_provider_x509_cert_url", ""),
    }
    cred = credentials.Certificate(cert_dict)
    return firebase_admin.initialize_app(
        cred, {"databaseURL": s["database_url"]}
    )


def _get_db() -> Any:
    """確保 Firebase 已初始化並回傳 db 模組。"""
    init_firebase()
    return firebase_db


# ─── 訪客計數 ──────────────────────────────────────────────────────────────────

def track_visitor(site_id: str) -> int:
    """
    使用原子 transaction 累加訪客人數。
    同一 Session 只計數一次（透過 session_state["counted"] 控制）。

    Args:
        site_id: 站台識別碼，對應 Realtime DB 路徑 visitor_counts/{site_id}

    Returns:
        目前累計訪客數；失敗時回傳 0。
    """
    try:
        db = _get_db()
        ref = db.reference(f"{_PATH_VISITORS}/{site_id}")

        def increment(current):
            return (current or 0) + 1

        if "counted" not in st.session_state:
            count = ref.transaction(increment)
            st.session_state["counted"] = True
            return count or 0
        else:
            v = ref.get()
            return v if v is not None else 0
    except Exception as exc:
        logger.warning("track_visitor 失敗：%s", exc)
        return 0


# ─── 留言 CRUD ─────────────────────────────────────────────────────────────────

def get_total_message_count() -> int:
    """
    取得可見留言（is_hidden == False）總數。

    Realtime DB 沒有 Count API，透過讀取所有留言的 is_hidden 欄位計算。
    資料量大時建議改用獨立計數節點。

    Returns:
        留言總數；失敗時回傳 0。
    """
    try:
        db = _get_db()
        # 只讀取 is_hidden 欄位，減少流量
        data = db.reference(_PATH_MESSAGES).get(shallow=False)
        if not data:
            return 0
        return sum(
            1 for v in data.values()
            if isinstance(v, dict) and not v.get("is_hidden", False)
        )
    except Exception as exc:
        logger.warning("get_total_message_count 失敗：%s", exc)
        return 0


def get_messages(page_number: int, page_size: int = 50) -> list[dict]:
    """
    取得前台留言列表（僅 is_hidden == False），依 created_at 降序，支援分頁。

    Realtime DB 不支援 offset，改為讀取全部後在 Python 端排序切片。
    資料量大時建議改用 Firestore。

    Args:
        page_number: 頁碼（從 1 開始）
        page_size: 每頁筆數

    Returns:
        dict 列表，含 id、name、content、created_at。
    """
    try:
        db = _get_db()
        data = db.reference(_PATH_MESSAGES).get()
        if not data:
            return []

        messages = [
            {"id": k, **v}
            for k, v in data.items()
            if isinstance(v, dict) and not v.get("is_hidden", False)
        ]
        messages.sort(key=lambda x: x.get("created_at", ""), reverse=True)

        start = (page_number - 1) * page_size
        return messages[start: start + page_size]
    except Exception as exc:
        logger.exception("get_messages 失敗：%s", exc)
        st.error("讀取留言失敗，請稍後再試 🐰")
        return []


def get_admin_messages(page_number: int, page_size: int = 20) -> tuple[list[dict], int]:
    """
    取得管理員後台留言列表（含隱藏），依 created_at 降序，支援分頁。

    Args:
        page_number: 頁碼（從 1 開始）
        page_size: 每頁筆數

    Returns:
        (留言列表, 總筆數) tuple。
    """
    try:
        db = _get_db()
        data = db.reference(_PATH_MESSAGES).get()
        if not data:
            return [], 0

        messages = [
            {"id": k, **v}
            for k, v in data.items()
            if isinstance(v, dict)
        ]
        messages.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        total = len(messages)

        start = (page_number - 1) * page_size
        return messages[start: start + page_size], total
    except Exception as exc:
        logger.exception("get_admin_messages 失敗：%s", exc)
        st.error("讀取留言失敗，請稍後再試 🐰")
        return [], 0


def is_duplicate_message(name: str, content: str, seconds: int = 60) -> bool:
    """
    檢查 60 秒內是否有相同暱稱 + 相同內容的留言。

    Args:
        name: 暱稱
        content: 內容
        seconds: 時間窗口（秒）

    Returns:
        True 表示重複。
    """
    try:
        db = _get_db()
        data = db.reference(_PATH_MESSAGES).get()
        if not data:
            return False

        cutoff = (
            datetime.now(tz=timezone.utc) - timedelta(seconds=seconds)
        ).isoformat()

        for v in data.values():
            if not isinstance(v, dict):
                continue
            if (
                v.get("name") == name
                and v.get("content") == content
                and v.get("created_at", "") >= cutoff
            ):
                return True
        return False
    except Exception as exc:
        logger.warning("is_duplicate_message 失敗（保守放行）：%s", exc)
        return False


def create_message(name: str, content: str) -> bool:
    """
    新增留言至 Realtime Database。

    Args:
        name: 暱稱
        content: 留言內容

    Returns:
        True 表示成功。
    """
    try:
        db = _get_db()
        ip_hash = get_client_ip_hash()
        now = datetime.now(tz=timezone.utc).isoformat()

        db.reference(_PATH_MESSAGES).push({
            "name": sanitize_input(name),
            "content": sanitize_input(content),
            "created_at": now,
            "updated_at": now,
            "is_hidden": False,
            "ip_hash": ip_hash,
        })
        return True
    except Exception as exc:
        logger.exception("create_message 失敗：%s", exc)
        st.error("留言送出失敗，請稍後再試 🐰")
        return False


def hide_message(message_id: str) -> bool:
    """隱藏指定留言。"""
    return _update_message(message_id, {"is_hidden": True}, "hide_message")


def unhide_message(message_id: str) -> bool:
    """取消隱藏指定留言。"""
    return _update_message(message_id, {"is_hidden": False}, "unhide_message")


def delete_message(message_id: str) -> bool:
    """永久刪除指定留言。"""
    try:
        _get_db().reference(f"{_PATH_MESSAGES}/{message_id}").delete()
        return True
    except Exception as exc:
        logger.exception("delete_message 失敗：%s", exc)
        st.error("刪除失敗，請稍後再試 🐰")
        return False


def _update_message(message_id: str, fields: dict, context: str) -> bool:
    """更新留言欄位（內部輔助）。"""
    try:
        fields["updated_at"] = datetime.now(tz=timezone.utc).isoformat()
        _get_db().reference(f"{_PATH_MESSAGES}/{message_id}").update(fields)
        return True
    except Exception as exc:
        logger.exception("%s 失敗：%s", context, exc)
        st.error("操作失敗，請稍後再試 🐰")
        return False


# ─── 公告 CRUD ─────────────────────────────────────────────────────────────────

def get_announcements() -> list[dict]:
    """
    取得前台公告（is_active == True），依 sort_order 升序。

    Returns:
        dict 列表。
    """
    try:
        data = _get_db().reference(_PATH_ANNOUNCEMENTS).get()
        if not data:
            return []
        anns = [
            {"id": k, **v}
            for k, v in data.items()
            if isinstance(v, dict) and v.get("is_active", False)
        ]
        anns.sort(key=lambda x: x.get("sort_order", 0))
        return anns
    except Exception as exc:
        logger.exception("get_announcements 失敗：%s", exc)
        st.error("讀取公告失敗，請稍後再試 🐰")
        return []


def get_all_announcements() -> list[dict]:
    """取得所有公告（含停用），供管理員使用。"""
    try:
        data = _get_db().reference(_PATH_ANNOUNCEMENTS).get()
        if not data:
            return []
        anns = [{"id": k, **v} for k, v in data.items() if isinstance(v, dict)]
        anns.sort(key=lambda x: x.get("sort_order", 0))
        return anns
    except Exception as exc:
        logger.exception("get_all_announcements 失敗：%s", exc)
        st.error("讀取公告列表失敗，請稍後再試 🐰")
        return []


def create_announcement(title: str, content: str, sort_order: int = 0) -> bool:
    """新增公告。"""
    try:
        now = datetime.now(tz=timezone.utc).isoformat()
        _get_db().reference(_PATH_ANNOUNCEMENTS).push({
            "title": sanitize_input(title),
            "content": sanitize_input(content),
            "is_active": True,
            "sort_order": sort_order,
            "created_at": now,
            "updated_at": now,
        })
        return True
    except Exception as exc:
        logger.exception("create_announcement 失敗：%s", exc)
        st.error("新增公告失敗，請稍後再試 🐰")
        return False


def update_announcement(
    ann_id: str, title: str, content: str, sort_order: int
) -> bool:
    """修改公告內容與排序。"""
    try:
        _get_db().reference(f"{_PATH_ANNOUNCEMENTS}/{ann_id}").update({
            "title": sanitize_input(title),
            "content": sanitize_input(content),
            "sort_order": sort_order,
            "updated_at": datetime.now(tz=timezone.utc).isoformat(),
        })
        return True
    except Exception as exc:
        logger.exception("update_announcement 失敗：%s", exc)
        st.error("更新公告失敗，請稍後再試 🐰")
        return False


def delete_announcement(ann_id: str) -> bool:
    """永久刪除公告。"""
    try:
        _get_db().reference(f"{_PATH_ANNOUNCEMENTS}/{ann_id}").delete()
        return True
    except Exception as exc:
        logger.exception("delete_announcement 失敗：%s", exc)
        st.error("刪除公告失敗，請稍後再試 🐰")
        return False


def toggle_announcement(ann_id: str, is_active: bool) -> bool:
    """切換公告啟用狀態。"""
    try:
        _get_db().reference(f"{_PATH_ANNOUNCEMENTS}/{ann_id}").update({
            "is_active": is_active,
            "updated_at": datetime.now(tz=timezone.utc).isoformat(),
        })
        return True
    except Exception as exc:
        logger.exception("toggle_announcement 失敗：%s", exc)
        st.error("切換公告狀態失敗，請稍後再試 🐰")
        return False


# ─── 分頁輔助 ──────────────────────────────────────────────────────────────────

def compute_total_pages(total_count: int, page_size: int) -> int:
    """計算總頁數，最少為 1。"""
    if page_size <= 0:
        return 1
    return max(math.ceil(total_count / page_size), 1)


def clamp_page(session_key: str, total_pages: int) -> None:
    """
    若當前頁碼超出總頁數，強制修正並觸發 rerun。
    防止刪除最後一筆後出現空頁面。
    """
    safe_total = max(total_pages, 1)
    if st.session_state.get(session_key, 1) > safe_total:
        st.session_state[session_key] = safe_total
        st.rerun()
