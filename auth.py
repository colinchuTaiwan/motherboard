"""
auth.py
-------
管理員認證模組。依賴：utils（間接）

提供：
- is_admin_logged_in()   : 檢查登入狀態
- check_admin_login()    : 帳密驗證含失敗鎖定
- render_sidebar_login() : 側邊欄登入 / 登出介面
"""

import logging
import time

import streamlit as st

logger = logging.getLogger(__name__)

_MAX_FAILURES: int = 5
_LOCK_SECONDS: int = 60


def is_admin_logged_in() -> bool:
    """回傳管理員登入狀態。"""
    return bool(st.session_state.get("admin_logged_in", False))


def _remaining_lock_seconds() -> float:
    """回傳鎖定剩餘秒數，未鎖定時回傳 0。"""
    locked_until = st.session_state.get("admin_locked_until")
    if locked_until is None:
        return 0.0
    return max(locked_until - time.time(), 0.0)


def check_admin_login(username: str, password: str) -> bool:
    """
    驗證管理員帳密，含 5 次失敗鎖定 60 秒機制。

    Args:
        username: 輸入帳號
        password: 輸入密碼

    Returns:
        True 表示驗證成功。
    """
    remaining = _remaining_lock_seconds()
    if remaining > 0:
        st.error(f"登入失敗次數過多，請稍後再試 🔒（剩餘 {int(remaining)} 秒）")
        return False

    try:
        correct_user: str = st.secrets["admin"]["username"]
        correct_pass: str = st.secrets["admin"]["password"]
    except KeyError:
        st.error("⚠️ 尚未設定管理員帳密，請在 Streamlit Secrets 中設定 [admin] 區塊。")
        return False

    if username == correct_user and password == correct_pass:
        st.session_state["admin_login_failures"] = 0
        st.session_state["admin_locked_until"] = None
        st.session_state["admin_logged_in"] = True
        return True

    failures = st.session_state.get("admin_login_failures", 0) + 1
    st.session_state["admin_login_failures"] = failures

    if failures >= _MAX_FAILURES:
        st.session_state["admin_locked_until"] = time.time() + _LOCK_SECONDS
        st.session_state["admin_login_failures"] = 0
        st.error(f"連續失敗 {_MAX_FAILURES} 次，帳號已鎖定 {_LOCK_SECONDS} 秒 🔒")
    else:
        st.error(f"帳號或密碼錯誤 🐰（還剩 {_MAX_FAILURES - failures} 次機會）")

    return False


def render_sidebar_login() -> None:
    """在 st.sidebar 渲染管理員登入 / 登出介面。"""
    with st.sidebar:
        st.markdown("---")
        st.markdown("### 🔐 管理員區域")

        if is_admin_logged_in():
            st.success("✅ 已登入管理員")
            if st.button("登出 👋", key="btn_logout", use_container_width=True):
                st.session_state["admin_logged_in"] = False
                st.session_state["admin_login_failures"] = 0
                st.session_state["admin_locked_until"] = None
                st.rerun()
        else:
            remaining = _remaining_lock_seconds()
            if remaining > 0:
                st.warning(f"🔒 帳號鎖定中，請等待 {int(remaining)} 秒")
                return

            with st.form(key="admin_login_form"):
                username = st.text_input("帳號", placeholder="管理員帳號")
                password = st.text_input("密碼", type="password", placeholder="密碼")
                submitted = st.form_submit_button("管理員登入 🔐", use_container_width=True)

            if submitted:
                if not username or not password:
                    st.error("請填寫帳號與密碼 🐰")
                elif check_admin_login(username, password):
                    st.success("登入成功 ✨")
                    st.rerun()
