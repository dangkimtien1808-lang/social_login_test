"""Client mỏng cho Graph API.

Trách nhiệm:
  * Gắn access_token + appsecret_proof vào mọi request có token.
  * Chuẩn hóa lỗi thành GraphAPIError / TransportError.
  * Retry có backoff + jitter CHỈ với lỗi an toàn để thử lại.
  * Đọc header hạn mức (X-App-Usage, X-Business-Use-Case-Usage...) để biết sắp bị throttle.

Không log URL đầy đủ (chứa token). Logger 'httpx' bị hạ xuống WARNING trong app.main.
"""
import hashlib
import hmac
import json
import logging
import random
import time
from typing import Any, Iterator

import httpx

from app.config import get_settings
from app.meta.errors import ErrorKind, GraphAPIError, TransportError

log = logging.getLogger(__name__)

USAGE_HEADERS = ("x-app-usage", "x-page-usage", "x-business-use-case-usage")


class GraphClient:
    def __init__(self, timeout: float = 60.0, max_retries: int = 3):
        s = get_settings()
        self.base_url = f"https://graph.facebook.com/{s.meta_graph_version}"
        # Upload video dùng host riêng
        self.video_url = f"https://graph-video.facebook.com/{s.meta_graph_version}"
        self._secret = s.meta_app_secret.encode()
        self.max_retries = max_retries
        self._http = httpx.Client(timeout=httpx.Timeout(timeout, connect=10.0))
        self.last_usage: dict[str, Any] = {}

    # --- vòng đời -------------------------------------------------------
    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "GraphClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # --- tiện ích -------------------------------------------------------
    def appsecret_proof(self, token: str) -> str:
        """HMAC-SHA256(app_secret, token). Bật 'Require App Secret' trong App Dashboard để Meta
        từ chối mọi call thiếu proof → token bị lộ cũng không dùng được từ nơi khác."""
        return hmac.new(self._secret, token.encode(), hashlib.sha256).hexdigest()

    def get(self, path: str, token: str | None = None, **params: Any) -> dict:
        return self.request("GET", path, token, params=params)

    def post(self, path: str, token: str | None = None, data: dict | None = None,
             files: dict | None = None, video: bool = False) -> dict:
        return self.request("POST", path, token, data=data, files=files, video=video)

    # --- lõi -------------------------------------------------------------
    def request(self, method: str, path: str, token: str | None = None, *, params: dict | None = None,
                data: dict | None = None, files: dict | None = None, video: bool = False,
                app_token: bool = False) -> dict:
        url = f"{self.video_url if video else self.base_url}/{path.lstrip('/')}"
        params = dict(params or {})
        data = dict(data or {})

        auth: dict[str, str] = {}
        if token:
            auth["access_token"] = token
            if not app_token:
                auth["appsecret_proof"] = self.appsecret_proof(token)
        # GET: token trong query; POST: token trong body (không nằm trong URL/log của proxy)
        (params if method == "GET" else data).update(auth)

        idempotent = method == "GET"
        attempt = 0
        while True:
            err: Exception
            try:
                resp = self._http.request(method, url, params=params or None, data=data or None, files=files)
            except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                err = TransportError(f"{type(e).__name__}: không kết nối được Graph API", request_sent=False)
            except httpx.TransportError as e:
                err = TransportError(f"{type(e).__name__}: mất kết nối khi chờ phản hồi", request_sent=True)
            else:
                self._record_usage(resp)
                body = self._parse(resp)
                if resp.is_success and "error" not in body:
                    return body
                err = GraphAPIError.from_response(resp.status_code, body)

            if not self._should_retry(err, idempotent, files is not None) or attempt >= self.max_retries:
                raise err
            delay = min(30.0, 2 ** attempt) + random.uniform(0, 1)  # exponential backoff + jitter
            log.warning("Graph %s %s lỗi (%s), thử lại sau %.1fs", method, path, err, delay)
            time.sleep(delay)
            attempt += 1

    @staticmethod
    def _should_retry(err: Exception, idempotent: bool, has_files: bool) -> bool:
        if has_files:
            return False  # stream file đã bị đọc; để scheduler retry ở cấp cao hơn
        if isinstance(err, TransportError):
            # Chưa gửi được → luôn an toàn. Đã gửi → chỉ retry nếu là GET.
            return (not err.request_sent) or idempotent
        if isinstance(err, GraphAPIError):
            # Rate limit KHÔNG retry ngay (sẽ làm tình hình tệ hơn) — để caller lên lịch lại.
            return err.kind == ErrorKind.TRANSIENT
        return False

    @staticmethod
    def _parse(resp: httpx.Response) -> dict:
        try:
            body = resp.json()
        except ValueError:
            return {} if resp.is_success else {"error": {"message": resp.text[:300]}}
        return body if isinstance(body, dict) else {"data": body}

    # --- hạn mức ---------------------------------------------------------
    def _record_usage(self, resp: httpx.Response) -> None:
        for header in USAGE_HEADERS:
            raw = resp.headers.get(header)
            if not raw:
                continue
            try:
                self.last_usage[header] = json.loads(raw)
            except ValueError:
                continue
        pct = self.usage_pct()
        if pct >= 80:
            log.warning("Hạn mức Graph API đã dùng %.0f%% — nên giảm tần suất gọi", pct)

    def usage_pct(self) -> float:
        """% cao nhất trong các chỉ số call_count / total_cputime / total_time."""
        values: list[float] = []
        for header, usage in self.last_usage.items():
            if header == "x-business-use-case-usage":
                # {"<page_id>": [{"type": "pages", "call_count": 5, ...}]}
                for entries in usage.values():
                    for e in entries:
                        values += [e.get(k, 0) for k in ("call_count", "total_cputime", "total_time")]
            else:
                values += [usage.get(k, 0) for k in ("call_count", "total_cputime", "total_time")]
        return float(max(values, default=0))

    def regain_seconds(self) -> int:
        """Ước tính số giây đến khi hết bị throttle (BUC header trả về phút)."""
        minutes = 0
        for entries in self.last_usage.get("x-business-use-case-usage", {}).values():
            for e in entries:
                minutes = max(minutes, int(e.get("estimated_time_to_regain_access", 0)))
        return minutes * 60

    # --- phân trang -----------------------------------------------------
    def paginate(self, path: str, token: str, max_pages: int = 50, **params: Any) -> Iterator[dict]:
        for _ in range(max_pages):
            body = self.get(path, token, **params)
            yield from body.get("data", [])
            paging = body.get("paging", {})
            after = paging.get("cursors", {}).get("after")
            if not after or "next" not in paging:
                return
            params["after"] = after
