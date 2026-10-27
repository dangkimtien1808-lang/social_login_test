"""Tạo/cập nhật User và đồng bộ danh sách Page sau OAuth."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.meta import oauth
from app.meta.errors import GraphAPIError
from app.meta.graph_client import GraphClient
from app.models import Page, User, UserPage
from app.security.crypto import encrypt_token
from app.services.audit import log_task
from app.services.tokens import touch_user_tokens
from app.utils.timeutil import utcnow


def upsert_user(db: Session, me: dict, long_lived_token: str, token_info: dict) -> User:
    user = db.scalar(select(User).where(User.fb_user_id == me["id"]))
    if user is None:
        user = User(fb_user_id=me["id"])
        db.add(user)
    user.name = me.get("name", "")
    user.user_token_enc = encrypt_token(long_lived_token)
    user.is_active = True
    touch_user_tokens(db, user, token_info)
    db.flush()
    return user


def sync_pages(db: Session, client: GraphClient, user: User, user_token: str) -> list[Page]:
    """Lấy /me/accounts, lưu page token (mã hóa), đăng ký webhook, gỡ liên kết Page user không còn quản lý."""
    remote = oauth.get_managed_pages(client, user_token)
    seen_ids: set[int] = set()
    pages: list[Page] = []

    for item in remote:
        page = db.scalar(select(Page).where(Page.fb_page_id == item["id"]))
        if page is None:
            page = Page(fb_page_id=item["id"])
            db.add(page)
        page.name = item.get("name", "")
        page.category = item.get("category", "")
        page.page_token_enc = encrypt_token(item["access_token"])
        page.token_status, page.token_error, page.token_checked_at = "valid", None, utcnow()
        page.is_active = True
        db.flush()

        link = db.get(UserPage, (user.id, page.id))
        if link is None:
            link = UserPage(user_id=user.id, page_id=page.id)
            db.add(link)
        link.tasks = ",".join(item.get("tasks", []))

        try:
            page.webhook_subscribed = oauth.subscribe_page_webhooks(client, page.fb_page_id, item["access_token"])
        except GraphAPIError as e:
            page.webhook_subscribed = False
            log_task("webhook_subscribe", "error", page_id=page.id, error=e)

        seen_ids.add(page.id)
        pages.append(page)

    # User mất quyền admin ở Page nào đó → gỡ liên kết để không thao tác được nữa
    for link in list(user.page_links):
        if link.page_id not in seen_ids:
            db.delete(link)
            log_task("page_unlinked", "warning", page_id=link.page_id, detail=f"User {user.name} không còn quản lý Page")

    db.flush()
    return pages
