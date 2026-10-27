"""Page Insights API: GET /{page-id}/insights?metric=...&period=day&since=&until=

Lưu ý:
  * Dữ liệu trễ ~24-48 giờ và có thể được Meta điều chỉnh → nên lấy lại vài ngày gần nhất mỗi lần đồng bộ.
  * Khoảng since–until tối đa ~90 ngày cho mỗi request.
  * end_time của mỗi điểm là MỐC KẾT THÚC ngày (theo giờ Pacific), nên ngày thực = end_time - 1 ngày.
  * Tên metric thay đổi theo phiên bản; gọi TỪNG metric để một metric bị khai tử không làm hỏng cả lô.
"""
from datetime import date, datetime, time, timedelta, timezone

from app.meta.errors import ErrorKind, GraphAPIError
from app.meta.graph_client import GraphClient


def _unix(d: date) -> int:
    return int(datetime.combine(d, time.min, tzinfo=timezone.utc).timestamp())


def _end_time_to_date(end_time: str) -> date:
    return (datetime.strptime(end_time, "%Y-%m-%dT%H:%M:%S%z") - timedelta(days=1)).date()


def _to_number(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):  # một số metric trả về breakdown → cộng tổng
        return float(sum(v for v in value.values() if isinstance(v, (int, float))))
    return 0.0


def fetch_daily_metrics(client: GraphClient, fb_page_id: str, token: str, metrics: list[str],
                        since: date, until: date) -> tuple[list[tuple[str, date, float]], list[str]]:
    """Trả về (rows[(metric, date, value)], skipped[mô tả metric bị bỏ qua])."""
    rows: list[tuple[str, date, float]] = []
    skipped: list[str] = []
    for metric in metrics:
        try:
            body = client.get(f"{fb_page_id}/insights", token, metric=metric, period="day",
                              since=_unix(since), until=_unix(until + timedelta(days=1)))
        except GraphAPIError as e:
            if e.kind == ErrorKind.INVALID_REQUEST:
                skipped.append(f"{metric}: {e.message}")
                continue
            raise
        for series in body.get("data", []):
            for point in series.get("values", []):
                if "end_time" in point:
                    rows.append((series.get("name", metric), _end_time_to_date(point["end_time"]),
                                 _to_number(point.get("value"))))
    return rows, skipped


def fetch_follower_snapshot(client: GraphClient, fb_page_id: str, token: str) -> dict:
    """Số người theo dõi hiện tại — ổn định hơn metric insights, lưu mỗi ngày làm chuỗi thời gian."""
    return client.get(fb_page_id, token, fields="followers_count,fan_count")
