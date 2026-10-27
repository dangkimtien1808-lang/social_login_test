"""Tiện ích thời gian. SQLite trả về datetime 'naive' kể cả khi khai báo timezone=True,
nên mọi phép so sánh phải đi qua ensure_utc()."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def local_to_utc(naive_local: datetime, tz_name: str) -> datetime:
    """'2026-10-20T09:00' nhập theo giờ của Page (vd Asia/Taipei) → UTC."""
    return naive_local.replace(tzinfo=ZoneInfo(tz_name)).astimezone(timezone.utc)


def utc_to_local(dt: datetime | None, tz_name: str) -> datetime | None:
    dt = ensure_utc(dt)
    return dt.astimezone(ZoneInfo(tz_name)) if dt else None
