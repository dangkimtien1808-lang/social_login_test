"""Job đăng bài theo lịch.

Cơ chế "claim" bằng UPDATE có điều kiện (status='scheduled' → 'publishing') đảm bảo mỗi bài chỉ được
một worker xử lý, kể cả khi chạy nhiều worker (an toàn trên cả SQLite lẫn PostgreSQL).

Bảng quyết định khi lỗi:
  RATE_LIMIT / TRANSIENT       → lên lịch lại với backoff (tối đa MAX_ATTEMPTS)
  TransportError chưa gửi       → lên lịch lại
  TransportError ĐÃ gửi (timeout) → 'uncertain': có thể đã đăng → người dùng kiểm tra rồi bấm thử lại
  TOKEN_INVALID                 → đánh dấu Page invalid, bài 'failed'
  PERMISSION / INVALID / POLICY / DUPLICATE → 'failed' (retry không giúp gì)
"""
import logging
from datetime import timedelta

from sqlalchemy import or_, select, update

from app.db import session_scope
from app.meta.errors import ErrorKind, GraphAPIError, TransportError
from app.meta.graph_client import GraphClient
from app.meta.publishing import publish
from app.models import Page, ScheduledPost
from app.services.audit import log_task, timed
from app.services.tokens import TokenUnavailable, handle_graph_error_for_page, page_token
from app.utils.timeutil import utcnow

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
BACKOFF_SECONDS = [60, 300, 900, 1800, 3600]
STUCK_AFTER = timedelta(minutes=15)


def _claim_due(limit: int = 10) -> list[int]:
    now = utcnow()
    claimed: list[int] = []
    with session_scope() as db:
        candidates = db.scalars(
            select(ScheduledPost.id)
            .where(ScheduledPost.status == "scheduled", ScheduledPost.scheduled_at <= now,
                   or_(ScheduledPost.next_attempt_at.is_(None), ScheduledPost.next_attempt_at <= now))
            .order_by(ScheduledPost.scheduled_at)
            .limit(limit)
        ).all()
        for post_id in candidates:
            res = db.execute(
                update(ScheduledPost)
                .where(ScheduledPost.id == post_id, ScheduledPost.status == "scheduled")
                .values(status="publishing", claimed_at=now, attempts=ScheduledPost.attempts + 1)
            )
            if res.rowcount == 1:
                claimed.append(post_id)
    return claimed


def _reschedule(post: ScheduledPost, err: Exception, client: GraphClient) -> None:
    if post.attempts >= MAX_ATTEMPTS:
        post.status = "failed"
        post.last_error = f"Hết số lần thử ({MAX_ATTEMPTS}): {err}"
        return
    delay = BACKOFF_SECONDS[min(post.attempts - 1, len(BACKOFF_SECONDS) - 1)]
    if isinstance(err, GraphAPIError) and err.kind == ErrorKind.RATE_LIMIT:
        delay = max(delay, client.regain_seconds())
    post.status = "scheduled"
    post.next_attempt_at = utcnow() + timedelta(seconds=delay)
    post.last_error = str(err)


def publish_one(post_id: int, client: GraphClient) -> None:
    with session_scope() as db, timed() as t:
        post = db.get(ScheduledPost, post_id)
        page = db.get(Page, post.page_id)
        try:
            token = page_token(page)
            fb_id = publish(client, page.fb_page_id, token, post.post_type, post.message, post.link, post.media_path)
        except TokenUnavailable as e:
            post.status, post.last_error = "failed", str(e)
            log_task("publish_post", "error", page_id=page.id, detail=f"post #{post.id}", error=e, duration_ms=t.ms)
        except GraphAPIError as e:
            handle_graph_error_for_page(page, e)
            if e.kind in (ErrorKind.RATE_LIMIT, ErrorKind.TRANSIENT):
                _reschedule(post, e, client)
            else:
                post.status, post.last_error = "failed", str(e)
            log_task("publish_post", "error", page_id=page.id, detail=f"post #{post.id} → {post.status}",
                     error=e, duration_ms=t.ms)
        except TransportError as e:
            if e.request_sent:
                post.status = "uncertain"
                post.last_error = f"{e} — có thể đã đăng; kiểm tra Page trước khi thử lại."
            else:
                _reschedule(post, e, client)
            log_task("publish_post", "error", page_id=page.id, detail=f"post #{post.id} → {post.status}",
                     error=e, duration_ms=t.ms)
        except (OSError, ValueError) as e:  # file media mất, post_type sai...
            post.status, post.last_error = "failed", str(e)
            log_task("publish_post", "error", page_id=page.id, detail=f"post #{post.id}", error=e, duration_ms=t.ms)
        else:
            post.status, post.fb_post_id, post.published_at, post.last_error = "published", fb_id, utcnow(), None
            log_task("publish_post", "success", page_id=page.id, detail=f"post #{post.id} → {fb_id}", duration_ms=t.ms)


def publish_due_posts() -> None:
    """Chạy mỗi 30 giây bởi worker."""
    ids = _claim_due()
    if not ids:
        return
    with GraphClient() as client:
        for post_id in ids:
            try:
                publish_one(post_id, client)
            except Exception:
                log.exception("Lỗi không mong đợi khi đăng post #%s", post_id)
            if client.usage_pct() >= 90:
                log.warning("Gần chạm hạn mức — dừng lượt này, các bài còn lại xử lý ở lượt sau")
                break


def recover_stuck_posts() -> None:
    """Worker chết giữa chừng → bài kẹt ở 'publishing'. Không biết đã đăng hay chưa → 'uncertain'."""
    cutoff = utcnow() - STUCK_AFTER
    with session_scope() as db:
        res = db.execute(
            update(ScheduledPost)
            .where(ScheduledPost.status == "publishing", ScheduledPost.claimed_at < cutoff)
            .values(status="uncertain", last_error="Worker dừng giữa chừng khi đăng — hãy kiểm tra Page.")
        )
        if res.rowcount:
            log_task("recover_stuck", "warning", detail=f"{res.rowcount} bài chuyển sang 'uncertain'")
