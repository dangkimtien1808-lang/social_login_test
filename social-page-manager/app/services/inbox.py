"""Chuyển sự kiện webhook thành InboxItem. KHÔNG gọi Graph API ở đây → webhook phản hồi nhanh."""
import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.meta.webhooks import InboundEvent
from app.models import InboxItem, MessengerThread, Page
from app.services.replies import suggest_for_item
from app.utils.timeutil import ensure_utc

log = logging.getLogger(__name__)


def ingest_event(db: Session, event: InboundEvent) -> InboxItem | None:
    page = db.scalar(select(Page).where(Page.fb_page_id == event.page_fb_id, Page.is_active))
    if page is None:
        log.warning("Webhook cho Page chưa kết nối: %s", event.page_fb_id)
        return None

    # Meta có thể gửi lặp một sự kiện → fb_item_id UNIQUE để chống trùng
    if db.scalar(select(InboxItem.id).where(InboxItem.fb_item_id == event.item_id)):
        return None

    item = InboxItem(page_id=page.id, kind=event.kind, fb_item_id=event.item_id, fb_post_id=event.post_id,
                     parent_id=event.parent_id, sender_id=event.sender_id, sender_name=event.sender_name,
                     text=event.text, received_at=event.created_at)
    try:
        with db.begin_nested():  # savepoint: hai request đồng thời cùng sự kiện
            db.add(item)
            db.flush()
    except IntegrityError:
        return None

    if event.kind == "message":
        _touch_thread(db, page.id, event)
    suggest_for_item(db, item)
    return item


def _touch_thread(db: Session, page_id: int, event: InboundEvent) -> None:
    thread = db.scalar(select(MessengerThread).where(MessengerThread.page_id == page_id,
                                                     MessengerThread.psid == event.sender_id))
    if thread is None:
        db.add(MessengerThread(page_id=page_id, psid=event.sender_id, last_inbound_at=event.created_at))
    elif ensure_utc(thread.last_inbound_at) < event.created_at:
        thread.last_inbound_at = event.created_at
