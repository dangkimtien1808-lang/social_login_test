"""Gợi ý & gửi trả lời.

Gợi ý hiện dùng mẫu theo từ khóa (đơn giản, dự đoán được). Có thể thay suggest_for_item bằng
mô hình AI — nhưng nên giữ bước người duyệt trước khi gửi cho nội dung sinh tự động.
"""
import logging

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.db import session_scope
from app.meta.errors import GraphAPIError, TransportError
from app.meta.graph_client import GraphClient
from app.meta.messaging import OutsideMessagingWindow, reply_to_comment, send_text_message
from app.models import InboxItem, MessengerThread, Page, Reply, ReplyTemplate
from app.services.audit import log_task
from app.services.tokens import TokenUnavailable, handle_graph_error_for_page, page_token
from app.utils.timeutil import utcnow

log = logging.getLogger(__name__)

MAX_AUTO_REPLIES_PER_RUN = 20  # giới hạn để không bị coi là spam


def suggest_for_item(db: Session, item: InboxItem) -> Reply | None:
    templates = db.scalars(
        select(ReplyTemplate).where(ReplyTemplate.is_active,
                                    or_(ReplyTemplate.page_id == item.page_id, ReplyTemplate.page_id.is_(None)))
    ).all()
    text = (item.text or "").casefold()
    # Ưu tiên mẫu riêng của Page trước mẫu dùng chung
    for tpl in sorted(templates, key=lambda t: t.page_id is None):
        if tpl.keyword.casefold() in text:
            reply = Reply(inbox_item_id=item.id, text=tpl.reply_text,
                          source="auto" if tpl.auto_send else "suggested",
                          status="queued" if tpl.auto_send else "suggested")
            db.add(reply)
            return reply
    return None


def send_reply(db: Session, client: GraphClient, reply: Reply, user_id: int | None = None) -> None:
    """Gửi một Reply; cập nhật status sent/failed và ghi log. Không raise lỗi nghiệp vụ."""
    item = reply.inbox_item
    page = db.get(Page, item.page_id)
    task = "reply_comment" if item.kind == "comment" else "send_message"
    try:
        token = page_token(page)
        if item.kind == "comment":
            fb_id = reply_to_comment(client, item.fb_item_id, token, reply.text)
        else:
            thread = db.scalar(select(MessengerThread).where(MessengerThread.page_id == page.id,
                                                             MessengerThread.psid == item.sender_id))
            fb_id = send_text_message(client, page.fb_page_id, token, item.sender_id, reply.text,
                                      thread.last_inbound_at if thread else None)
    except (OutsideMessagingWindow, TokenUnavailable, TransportError) as e:
        reply.status, reply.error = "failed", str(e)
        log_task(task, "error", page_id=page.id, detail=f"reply #{reply.id}", error=e)
    except GraphAPIError as e:
        handle_graph_error_for_page(page, e)
        reply.status, reply.error = "failed", e.hint()
        log_task(task, "error", page_id=page.id, detail=f"reply #{reply.id}", error=e)
    else:
        reply.status, reply.fb_reply_id, reply.sent_at, reply.error = "sent", fb_id, utcnow(), None
        reply.sent_by = user_id
        item.is_handled = True
        log_task(task, "success", page_id=page.id, detail=f"reply #{reply.id} → {fb_id}")


def send_queued_replies() -> None:
    """Worker: gửi các trả lời tự động (status='queued')."""
    with session_scope() as db:
        ids = db.scalars(select(Reply.id).where(Reply.status == "queued")
                         .order_by(Reply.created_at).limit(MAX_AUTO_REPLIES_PER_RUN)).all()
        claimed = [i for i in ids if db.execute(
            update(Reply).where(Reply.id == i, Reply.status == "queued").values(status="sending")).rowcount == 1]
    if not claimed:
        return
    with GraphClient() as client:
        for reply_id in claimed:
            with session_scope() as db:
                send_reply(db, client, db.get(Reply, reply_id))
