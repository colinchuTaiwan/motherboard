"""
app.py
------
🌸 可愛留言板主程式（Firebase Realtime Database 版）
依賴：utils、auth、firebase_service
"""

import logging
import math
import time
import uuid

import streamlit as st

from auth import is_admin_logged_in, render_sidebar_login
from firebase_service import (
    clamp_page,
    compute_total_pages,
    create_announcement,
    create_message,
    delete_announcement,
    delete_message,
    get_admin_messages,
    get_announcements,
    get_all_announcements,
    get_messages,
    get_total_message_count,
    hide_message,
    is_duplicate_message,
    toggle_announcement,
    track_visitor,
    unhide_message,
    update_announcement,
    upload_image,
    validate_image,
)
from utils import format_datetime_tw, sanitize_input

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_PAGE_SIZE_FRONT: int = 50
_PAGE_SIZE_ADMIN: int = 20
_POST_COOLDOWN_SECONDS: int = 10
_MAX_CONTENT_LENGTH: int = 300
_SITE_ID: str = "message_board_main"


# ─── Session 初始化 ────────────────────────────────────────────────────────────

def init_app_states() -> None:
    """
    集中初始化所有 Session State。
    必須在最頂部呼叫。

    user_session_id：自行生成的 UUID，作為 IP fallback 來源。
    禁止依賴 Streamlit 內部 _session_id。
    """
    defaults = {
        "user_session_id": uuid.uuid4().hex,
        "current_page": 1,
        "admin_current_page": 1,
        "admin_logged_in": False,
        "admin_login_failures": 0,
        "admin_locked_until": None,
        "last_post_time": None,
        "counted": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


# ─── CSS ───────────────────────────────────────────────────────────────────────

def inject_css() -> None:
    """注入可愛粉色系 CSS 樣式。"""
    st.markdown("""
    <style>
    /* ── 整體背景：米白暖色，像舊木地板的溫度 ── */
    .stApp { background-color: #FAF6F1; }

    /* ── 主標題 ── */
    .main-title {
        text-align: center; font-size: 2.3rem; font-weight: 800;
        color: #5C3D2E; margin-bottom: 0.2rem; letter-spacing: 0.03em;
    }
    .main-subtitle {
        text-align: center; color: #A07855;
        font-size: 0.95rem; margin-bottom: 0.5rem;
    }
    .visitor-badge {
        text-align: center; color: #B08060;
        font-size: 0.85rem; margin-bottom: 1.2rem;
    }

    /* ── 公告卡片：溫暖的黃褐色系 ── */
    .announcement-card {
        background: linear-gradient(135deg, #FFF8ED, #FDEFD8);
        border-left: 5px solid #C8864A; border-radius: 12px;
        padding: 1rem 1.25rem; margin-bottom: 0.75rem;
        box-shadow: 0 2px 8px rgba(160,100,60,0.10);
    }
    .announcement-title { font-size:1.05rem; font-weight:700; color:#7B4F2E; margin-bottom:0.3rem; }
    .announcement-content { color:#555; font-size:0.92rem; line-height:1.65; white-space:pre-wrap; }
    .announcement-meta { font-size:0.78rem; color:#B08050; margin-top:0.4rem; opacity:0.8; }

    /* ── 留言卡片：白底，木質邊框感 ── */
    .message-card {
        background: #FFFDF9; border-radius: 14px;
        padding: 1rem 1.25rem; margin-bottom: 0.85rem;
        box-shadow: 0 2px 8px rgba(140,90,50,0.08);
        border: 1px solid #EDD9C0; transition: box-shadow 0.2s, transform 0.15s;
    }
    .message-card:hover {
        box-shadow: 0 4px 14px rgba(140,90,50,0.14);
        transform: translateY(-1px);
    }
    .message-name { font-weight:700; color:#7B4F2E; font-size:0.95rem; }
    .message-content { color:#3D2B1F; font-size:0.92rem; margin:0.35rem 0; line-height:1.7; white-space:pre-wrap; word-break:break-word; }
    .message-time { font-size:0.75rem; color:#C4A882; }

    /* ── 分頁 / 區塊標題 / 空白提示 ── */
    .pager-info { text-align:center; color:#A07855; font-size:0.88rem; margin:0.5rem 0; }
    .section-header { font-size:1.1rem; font-weight:700; color:#6B4226; margin:1rem 0 0.5rem; }
    .empty-hint { text-align:center; color:#C4A882; font-size:0.95rem; padding:1.5rem; }

    /* ── 輸入框：米色底、暖棕邊框 ── */
    div[data-testid="stTextInput"] input,
    div[data-testid="stTextArea"] textarea {
        border-radius: 10px; border: 1.5px solid #D9BFA0; background: #FFFDF9;
        color: #3D2B1F;
    }
    div[data-testid="stTextInput"] input:focus,
    div[data-testid="stTextArea"] textarea:focus {
        border-color: #C8864A; box-shadow: 0 0 0 2px rgba(200,134,74,0.18);
    }

    /* ── 按鈕：圓角、暖棕系 ── */
    div[data-testid="stButton"] > button {
        border-radius: 10px; font-weight: 600;
    }
    div[data-testid="stButton"] > button[kind="primary"] {
        background: linear-gradient(135deg, #C8864A, #A0622E);
        border: none; color: white;
    }
    div[data-testid="stButton"] > button[kind="primary"]:hover {
        background: linear-gradient(135deg, #D9935A, #B0723E);
    }

    /* ── Sidebar：溫暖米色 ── */
    section[data-testid="stSidebar"] { background: #F5EDE0; }
    </style>
    """, unsafe_allow_html=True)


# ─── 公告區 ────────────────────────────────────────────────────────────────────

def render_announcements() -> None:
    """渲染前台公告區（僅顯示 is_active == True）。"""
    with st.expander("📋 家裡公告", expanded=True):
        announcements = get_announcements()
        if not announcements:
            st.markdown('<div class="empty-hint">目前沒有公告 🏡</div>', unsafe_allow_html=True)
            return
        for ann in announcements:
            st.markdown(f"""
            <div class="announcement-card">
                <div class="announcement-title">📌 {ann.get("title", "")}</div>
                <div class="announcement-content">{ann.get("content", "")}</div>
                <div class="announcement-meta">🕐 更新時間：{format_datetime_tw(ann.get("updated_at", ""))}</div>
            </div>
            """, unsafe_allow_html=True)


# ─── 留言輸入 ──────────────────────────────────────────────────────────────────

def render_post_form() -> None:
    """
    渲染留言輸入表單，含選填圖片上傳。
    圖片在表單外用 file_uploader 處理（避免 Streamlit form 限制），
    送出時一併上傳至 Firebase Storage。
    """
    st.markdown('<div class="section-header">✏️ 留下你的話</div>', unsafe_allow_html=True)

    with st.form(key="post_form", clear_on_submit=True):
        name = st.text_input("你的名字 🏷️", placeholder="叫我什麼都好～", max_chars=30)
        content = st.text_area(
            f"想說的話（最多 {_MAX_CONTENT_LENGTH} 字）",
            placeholder="有什麼想跟大家分享的嗎？🍵",
            max_chars=_MAX_CONTENT_LENGTH,
            height=120,
        )
        uploaded_file = st.file_uploader(
            "附上一張圖片（選填）🖼️",
            type=["jpg", "jpeg", "png", "gif", "webp"],
            help="支援 JPG、PNG、GIF、WebP，最大 5 MB",
        )
        submitted = st.form_submit_button("留下足跡 🏠", use_container_width=True, type="primary")

    if submitted:
        _handle_post(name, content, uploaded_file)


def _handle_post(name: str, content: str, uploaded_file) -> None:
    """
    處理留言送出：驗證 → 圖片上傳 → 寫入 DB。

    圖片上傳失敗時提示使用者，但不阻止純文字留言送出。

    Args:
        name: 暱稱
        content: 留言內容
        uploaded_file: st.file_uploader 物件（可為 None）
    """
    name = sanitize_input(name)
    content = sanitize_input(content)

    if not name:
        st.warning("名字不可空白喔 🏷️")
        return
    if not content:
        st.warning("想說的話不可空白喔 🍵")
        return
    if len(content) > _MAX_CONTENT_LENGTH:
        st.warning(f"字數不可超過 {_MAX_CONTENT_LENGTH} 字喔")
        return

    # 驗證圖片格式與大小
    if uploaded_file is not None:
        ok, err_msg = validate_image(uploaded_file)
        if not ok:
            st.warning(err_msg)
            return

    # 10 秒冷卻
    last_post = st.session_state.get("last_post_time")
    if last_post is not None:
        elapsed = time.time() - last_post
        if elapsed < _POST_COOLDOWN_SECONDS:
            remaining = math.ceil(_POST_COOLDOWN_SECONDS - elapsed)
            st.warning(f"慢慢來，稍等一下再留言 🍵（還需等待 {remaining} 秒）")
            return

    # 60 秒重複檢查
    if is_duplicate_message(name, content, seconds=60):
        st.warning("你剛才已經留過相同的話了，稍後再試吧 🏠")
        return

    # 上傳圖片（選填）
    image_url: str | None = None
    if uploaded_file is not None:
        with st.spinner("圖片上傳中... 🖼️"):
            image_url = upload_image(uploaded_file)
        if image_url is None:
            # upload_image 內部已顯示錯誤，這裡直接返回
            return

    if create_message(name, content, image_url):
        st.session_state["last_post_time"] = time.time()
        st.session_state["current_page"] = 1
        st.success("已留下你的足跡 🏠")
        st.rerun()


# ─── 留言列表 ──────────────────────────────────────────────────────────────────

def render_messages() -> None:
    """渲染前台留言列表，含分頁與越界校正。"""
    st.markdown('<div class="section-header">🏡 大家說的話</div>', unsafe_allow_html=True)

    total_count = get_total_message_count()
    total_pages = compute_total_pages(total_count, _PAGE_SIZE_FRONT)
    clamp_page("current_page", total_pages)
    current_page = st.session_state["current_page"]

    st.markdown(
        f'<div class="pager-info">'
        f"總留言數：{total_count} ｜ 第 {current_page} 頁 / 共 {total_pages} 頁 ｜ 每頁 {_PAGE_SIZE_FRONT} 筆"
        f"</div>",
        unsafe_allow_html=True,
    )

    _render_pager("current_page", current_page, total_pages, "front_page_input")
    st.divider()

    messages = get_messages(current_page, _PAGE_SIZE_FRONT)
    if not messages:
        st.markdown('<div class="empty-hint">還沒有人留言，來當第一個吧 🏠</div>', unsafe_allow_html=True)
        return

    for msg in messages:
        st.markdown(f"""
        <div class="message-card">
            <div class="message-name">🏷️ {msg.get("name", "訪客")}</div>
            <div class="message-content">{msg.get("content", "")}</div>
            <div class="message-time">🕐 {format_datetime_tw(msg.get("created_at", ""))}</div>
        </div>
        """, unsafe_allow_html=True)
        # 若有附圖則顯示（在卡片外用 st.image 渲染，支援點擊放大）
        if msg.get("image_url"):
            st.image(msg["image_url"], use_container_width=False, width=360)


# ─── 分頁控制 ──────────────────────────────────────────────────────────────────

def _render_pager(
    session_key: str,
    current_page: int,
    total_pages: int,
    input_key: str,
) -> None:
    """
    渲染上一頁 / 跳頁輸入框 / 下一頁。
    number_input 使用獨立 key，避免與按鈕衝突。
    """
    col_prev, col_input, col_next = st.columns([1, 2, 1])

    with col_prev:
        if st.button("上一頁 🐾", key=f"btn_prev_{session_key}",
                     disabled=(current_page <= 1), use_container_width=True):
            st.session_state[session_key] = current_page - 1
            st.rerun()

    with col_input:
        st.number_input(
            "頁碼", min_value=1, max_value=total_pages,
            value=current_page, step=1,
            key=input_key, label_visibility="collapsed",
        )

    with col_next:
        if st.button("下一頁 🐾", key=f"btn_next_{session_key}",
                     disabled=(current_page >= total_pages), use_container_width=True):
            st.session_state[session_key] = current_page + 1
            st.rerun()

    # 同步 number_input 跳頁
    input_val = st.session_state.get(input_key, 1)
    if input_val != st.session_state[session_key]:
        st.session_state[session_key] = input_val
        st.rerun()


# ─── 管理員後台 ────────────────────────────────────────────────────────────────

def render_admin_panel() -> None:
    """渲染管理員後台（留言管理 + 公告管理）。"""
    st.divider()
    st.markdown("## 🛠️ 管理員後台")
    tab_msg, tab_ann = st.tabs(["💬 留言管理", "📢 公告管理"])

    with tab_msg:
        _render_admin_messages()
    with tab_ann:
        _render_admin_announcements()


def _render_admin_messages() -> None:
    """管理員留言管理頁（隱藏 / 取消隱藏 / 刪除）。"""
    st.markdown("### 💬 留言管理")
    messages, total_count = get_admin_messages(
        st.session_state["admin_current_page"], _PAGE_SIZE_ADMIN
    )
    total_pages = compute_total_pages(total_count, _PAGE_SIZE_ADMIN)
    clamp_page("admin_current_page", total_pages)
    current_page = st.session_state["admin_current_page"]

    st.markdown(
        f'<div class="pager-info">'
        f"總留言數：{total_count} ｜ 第 {current_page} 頁 / 共 {total_pages} 頁"
        f"</div>",
        unsafe_allow_html=True,
    )
    _render_pager("admin_current_page", current_page, total_pages, "admin_page_input")
    st.divider()

    if not messages:
        st.markdown('<div class="empty-hint">目前沒有留言 🌸</div>', unsafe_allow_html=True)
        return

    for msg in messages:
        msg_id = msg["id"]
        is_hidden = msg.get("is_hidden", False)
        status = "🙈 隱藏中" if is_hidden else "✅ 顯示中"
        fade = "opacity:0.5;" if is_hidden else ""

        image_url = msg.get("image_url")
        st.markdown(f"""
        <div class="message-card" style="{fade}">
            <div class="message-name">🏷️ {msg.get("name","訪客")}
                <span style="font-size:0.75rem;color:#888;margin-left:0.5rem;">{status}</span>
            </div>
            <div class="message-content">{msg.get("content","")}</div>
            <div class="message-time">🕐 {format_datetime_tw(msg.get("created_at",""))}</div>
        </div>
        """, unsafe_allow_html=True)
        if image_url:
            st.image(image_url, width=200, caption="附圖")

        col_hide, col_del = st.columns(2)
        with col_hide:
            if is_hidden:
                if st.button("取消隱藏 👁️", key=f"unhide_{msg_id}", use_container_width=True):
                    if unhide_message(msg_id):
                        st.success("已取消隱藏 ✨")
                        st.rerun()
            else:
                if st.button("隱藏留言 🙈", key=f"hide_{msg_id}", use_container_width=True):
                    if hide_message(msg_id):
                        st.success("已隱藏 ✨")
                        st.rerun()
        with col_del:
            confirmed = st.checkbox("確認刪除", key=f"confirm_{msg_id}")
            if confirmed:
                if st.button("永久刪除 🗑️", key=f"delete_{msg_id}", use_container_width=True):
                    # 刪除留言時一併清理 Storage 圖片
                    if delete_message(msg_id, image_url):
                        st.success("已刪除 ✨")
                        st.rerun()


def _render_admin_announcements() -> None:
    """管理員公告管理頁（新增 / 修改 / 刪除 / 啟停用）。"""
    st.markdown("### 📢 公告管理")

    with st.expander("➕ 新增公告", expanded=False):
        with st.form("form_add_ann"):
            t = st.text_input("標題", max_chars=100)
            c = st.text_area("內容", height=80)
            s = st.number_input("排序值（越小越前面）", value=0, step=1)
            if st.form_submit_button("新增公告 ✨", use_container_width=True):
                if not t.strip():
                    st.warning("標題不可空白 🐰")
                elif not c.strip():
                    st.warning("內容不可空白 🐰")
                elif create_announcement(t, c, int(s)):
                    st.success("新增成功 ✨")
                    st.rerun()

    st.divider()
    anns = get_all_announcements()
    if not anns:
        st.markdown('<div class="empty-hint">目前沒有公告 🌸</div>', unsafe_allow_html=True)
        return

    for ann in anns:
        ann_id = ann["id"]
        is_active = ann.get("is_active", False)
        label = "✅ 啟用中" if is_active else "⏸️ 停用中"
        icon = "📌" if is_active else "📋"

        with st.expander(f"{icon} {ann.get('title','（無標題）')} ｜ {label}", expanded=False):
            with st.form(f"form_edit_ann_{ann_id}"):
                et = st.text_input("標題", value=ann.get("title", ""), max_chars=100)
                ec = st.text_area("內容", value=ann.get("content", ""), height=80)
                es = st.number_input("排序值", value=int(ann.get("sort_order", 0)), step=1)

                c1, c2, c3 = st.columns(3)
                with c1:
                    if st.form_submit_button("儲存 💾", use_container_width=True):
                        if not et.strip():
                            st.warning("標題不可空白 🐰")
                        elif update_announcement(ann_id, et, ec, int(es)):
                            st.success("已更新 ✨")
                            st.rerun()
                with c2:
                    toggle_label = "停用 ⏸️" if is_active else "啟用 ▶️"
                    if st.form_submit_button(toggle_label, use_container_width=True):
                        if toggle_announcement(ann_id, not is_active):
                            st.success("已切換 ✨")
                            st.rerun()
                with c3:
                    if st.form_submit_button("刪除 🗑️", use_container_width=True):
                        if delete_announcement(ann_id):
                            st.success("已刪除 ✨")
                            st.rerun()

            st.caption(f"🕐 最後更新：{format_datetime_tw(ann.get('updated_at',''))}")


# ─── 主程式 ────────────────────────────────────────────────────────────────────

def main() -> None:
    """應用程式主入口。"""
    st.set_page_config(
        page_title="🏠 可愛的家",
        page_icon="🏠",
        layout="centered",
        initial_sidebar_state="auto",
    )

    init_app_states()
    inject_css()

    # 訪客計數（同 civics_app.py 模式）
    visitor_count = track_visitor(_SITE_ID)

    render_sidebar_login()

    st.markdown(
        '<div class="main-title">🏠 可愛的家</div>'
        '<div class="main-subtitle">這裡是我們溫暖的小角落，歡迎留下你的足跡 🍵</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="visitor-badge">🚪 累計到訪：{visitor_count} 人次</div>',
        unsafe_allow_html=True,
    )

    render_announcements()
    st.divider()
    render_post_form()
    st.divider()
    render_messages()

    if is_admin_logged_in():
        render_admin_panel()


if __name__ == "__main__":
    main()
