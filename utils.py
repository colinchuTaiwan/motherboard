"""
utils.py
--------
共用工具函式模組。無內部依賴。

提供：
- sanitize_input()      : 清理使用者輸入
- format_datetime_tw()  : datetime 字串 → 台灣時間格式
- get_client_ip_hash()  : 取得 IP SHA256 雜湊（含 fallback）
"""

import hashlib
import logging
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import streamlit as st

logger = logging.getLogger(__name__)

_TW_TZ = ZoneInfo("Asia/Taipei")


def sanitize_input(text: str) -> str:
    """
    清理使用者輸入字串。
    - strip 前後空白
    - 移除 ASCII 控制字元（保留 \\t=9、\\n=10）
    - 保留中文、標點、emoji
    - 不做 HTML escape（Streamlit 已處理）

    Args:
        text: 原始輸入

    Returns:
        清理後字串
    """
    if not isinstance(text, str):
        return ""
    text = text.strip()
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", text)
    return text


def format_datetime_tw(iso_str: str) -> str:
    """
    將 ISO 格式時間字串轉換為台灣時間（UTC+8）顯示字串。

    Args:
        iso_str: datetime.isoformat() 產生的字串

    Returns:
        例如「2024-01-15 14:30:00」；失敗時回傳原字串。
    """
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_TW_TZ).strftime("%Y-%m-%d %H:%M:%S")
    except Exception as exc:
        logger.warning("format_datetime_tw 失敗：%s", exc)
        return iso_str


def get_client_ip_hash() -> str:
    """
    取得 client IP 的 SHA256 雜湊。
    Streamlit Cloud 環境可能取得 proxy IP，fallback 使用 session UUID。
    禁止儲存原始 IP。

    Returns:
        64 字元 SHA256 十六進位字串
    """
    ip: str = ""
    try:
        headers = st.context.headers
        forwarded = headers.get("X-Forwarded-For", "")
        if forwarded:
            ip = forwarded.split(",")[0].strip()
        if not ip:
            ip = headers.get("X-Real-IP", "").strip()
    except Exception:
        pass

    if not ip:
        session_uuid = st.session_state.get("user_session_id", "unknown")
        ip = f"session:{session_uuid}"

    return hashlib.sha256(ip.encode("utf-8")).hexdigest()
