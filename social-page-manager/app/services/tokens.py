"""Truy xuất token đã giải mã và xử lý vòng đời token (hết hạn, bị thu hồi)."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import session_scope
from app.meta import oauth
from app.meta.errors import ErrorKind, GraphAPIError
from app.meta.graph_client import GraphClient
from app.models import Page, User
from app.security.crypto import decrypt_token
from app.services.audit import log_task
from app.utils.timeutil import ensure_utc, utcnow


class TokenUnavailable(Exception):
    pass


def page_token(page: Page) -> str:
    if page.token_status != "valid" or not page.page_token_enc:
        raise TokenUnavailable(f"Token của Page '{page.name}' không khả dụng ({page.token_status}) — hãy kết nối lại.")
    return decrypt_token(page.page_token_enc)


def user_token(user: User) -> str:
    if not user.user_token_enc:
        raise TokenUnavailable("Chưa có user token — hãy đăng nhập lại.")
    return decrypt_token(user.user_token_enc)


def mark_page_token_invalid(page: Page, err: Exception) -> None:
    """Gọi khi gặp lỗi 190: ngừng mọi tác vụ của Page cho tới khi admin kết nối lại."""
    page.token_status = "invalid"
    page.token_error = err.hint() if isinstance(err, GraphAPIError) else str(err)
    page.token_checked_at = utcnow()
    log_task("token_invalidated", "error", page_id=page.id, error=err)


def handle_graph_error_for_page(page: Page, err: GraphAPIError) -> None:
    if err.kind == ErrorKind.TOKEN_INVALID:
        mark_page_token_invalid(page, err)


def ts_to_dt(ts: int | None) -> datetime | None:
    """debug_token trả 0 khi 'không bao giờ hết hạn'."""
    return datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None


def check_token_health() -> None:
    """Job hằng ngày: debug_token từng Page; cảnh báo user sắp hết hạn data access (90 ngày)."""
    with session_scope() as db, GraphClient() as client:
        for page in db.scalars(select(Page).where(Page.is_active, Page.page_token_enc.is_not(None))):
            try:
                info = oauth.debug_token(client, decrypt_token(page.page_token_enc))
            except GraphAPIError as e:
                log_task("token_health", "warning", page_id=page.id, error=e)
                continue
            page.token_checked_at = utcnow()
            if not info.get("is_valid"):
                page.token_status = "invalid"
                page.token_error = (info.get("error") or {}).get("message", "Token không hợp lệ")
                log_task("token_health", "error", page_id=page.id, detail=page.token_error)
            elif page.token_status != "valid":
                page.token_status, page.token_error = "valid", None

        soon = utcnow() + timedelta(days=14)
        for user in db.scalars(select(User).where(User.is_active)):
            expiries = [ensure_utc(d) for d in (user.user_token_expires_at, user.data_access_expires_at) if d]
            if expiries and min(expiries) < soon:
                log_task("token_health", "warning",
                         detail=f"User {user.name} cần đăng nhập lại trước {min(expiries):%Y-%m-%d} để gia hạn token")


def touch_user_tokens(db: Session, user: User, info: dict) -> None:
    user.user_token_expires_at = ts_to_dt(info.get("expires_at"))
    user.data_access_expires_at = ts_to_dt(info.get("data_access_expires_at"))
    user.granted_scopes = ",".join(info.get("scopes", []))
