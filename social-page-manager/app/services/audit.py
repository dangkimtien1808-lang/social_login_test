"""Ghi log tác vụ vào bảng task_logs (và logger Python).

Dùng session RIÊNG để log vẫn được lưu kể cả khi transaction của nghiệp vụ bị rollback.
"""
import logging
import time
from contextlib import contextmanager
from typing import Iterator

from app.db import session_scope
from app.meta.errors import GraphAPIError
from app.models import TaskLog
from app.utils.redact import redact

log = logging.getLogger("spm.audit")


def log_task(task_type: str, status: str, *, page_id: int | None = None, detail: str = "",
             error: Exception | None = None, duration_ms: int | None = None) -> None:
    error_code = trace_id = None
    if isinstance(error, GraphAPIError):
        error_code, trace_id = error.code_str, error.fbtrace_id
        detail = f"{detail} | {error}" if detail else str(error)
    elif error is not None:
        detail = f"{detail} | {type(error).__name__}: {error}" if detail else f"{type(error).__name__}: {error}"
    detail = redact(detail)[:4000]

    level = logging.ERROR if status == "error" else logging.WARNING if status == "warning" else logging.INFO
    log.log(level, "%s page=%s %s %s", task_type, page_id, status, detail)
    try:
        with session_scope() as db:
            db.add(TaskLog(task_type=task_type, status=status, page_id=page_id, detail=detail,
                           error_code=error_code, fb_trace_id=trace_id, duration_ms=duration_ms))
    except Exception:  # không để lỗi ghi log làm hỏng nghiệp vụ
        log.exception("Không ghi được task_log")


class Timer:
    def __init__(self) -> None:
        self.start = time.perf_counter()

    @property
    def ms(self) -> int:
        return int((time.perf_counter() - self.start) * 1000)


@contextmanager
def timed() -> Iterator[Timer]:
    yield Timer()
