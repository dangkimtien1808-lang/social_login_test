"""Job đồng bộ Insights hằng ngày vào bảng insights_daily."""
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import session_scope
from app.meta.errors import ErrorKind, GraphAPIError, TransportError
from app.meta.graph_client import GraphClient
from app.meta.insights import fetch_daily_metrics, fetch_follower_snapshot
from app.models import InsightDaily, Page
from app.services.audit import log_task, timed
from app.services.tokens import TokenUnavailable, handle_graph_error_for_page, page_token
from app.utils.timeutil import utcnow

LOOKBACK_DAYS = 3  # lấy lại vài ngày vì Meta có thể cập nhật số liệu trễ


def _upsert(db: Session, page_id: int, metric: str, day: date, value: float) -> None:
    row = db.scalar(select(InsightDaily).where(InsightDaily.page_id == page_id, InsightDaily.metric == metric,
                                               InsightDaily.date == day))
    if row is None:
        db.add(InsightDaily(page_id=page_id, metric=metric, date=day, value=value))
    else:
        row.value = value


def sync_page_insights(db: Session, client: GraphClient, page: Page, days: int = LOOKBACK_DAYS) -> int:
    token = page_token(page)
    today = utcnow().date()
    rows, skipped = fetch_daily_metrics(client, page.fb_page_id, token, get_settings().insights_metrics,
                                        since=today - timedelta(days=days), until=today - timedelta(days=1))
    for metric, day, value in rows:
        _upsert(db, page.id, metric, day, value)

    snap = fetch_follower_snapshot(client, page.fb_page_id, token)
    if "followers_count" in snap:
        _upsert(db, page.id, "followers_count", today, float(snap["followers_count"]))
    if skipped:
        log_task("sync_insights", "warning", page_id=page.id, detail="Metric bị bỏ qua: " + "; ".join(skipped))
    return len(rows)


def sync_all_insights(days: int = LOOKBACK_DAYS) -> None:
    """Worker gọi mỗi ngày. Có thể gọi với days=90 để backfill lần đầu."""
    with session_scope() as db:
        page_ids = db.scalars(select(Page.id).where(Page.is_active, Page.token_status == "valid")).all()
    with GraphClient() as client:
        for page_id in page_ids:
            with session_scope() as db, timed() as t:
                page = db.get(Page, page_id)
                try:
                    n = sync_page_insights(db, client, page, days)
                    log_task("sync_insights", "success", page_id=page_id, detail=f"{n} điểm dữ liệu", duration_ms=t.ms)
                except (TokenUnavailable, TransportError) as e:
                    log_task("sync_insights", "error", page_id=page_id, error=e, duration_ms=t.ms)
                except GraphAPIError as e:
                    handle_graph_error_for_page(page, e)
                    log_task("sync_insights", "error", page_id=page_id, error=e, duration_ms=t.ms)
                    if e.kind == ErrorKind.RATE_LIMIT:
                        break  # dừng, để lượt sau
