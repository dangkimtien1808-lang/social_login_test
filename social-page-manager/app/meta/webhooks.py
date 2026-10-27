"""Xác thực và chuẩn hóa sự kiện Webhook của Page (object = 'page').

Field 'feed'     → entry[].changes[] (bình luận, bài, reaction...). App chỉ lấy comment mới.
Field 'messages' → entry[].messaging[] (tin nhắn Messenger).
"""
import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterator

from app.utils.timeutil import utcnow


def verify_signature(raw_body: bytes, signature_header: str | None, app_secret: str) -> bool:
    """So khớp X-Hub-Signature-256 = 'sha256=' + HMAC-SHA256(app_secret, raw body).
    Phải dùng body THÔ (bytes) — parse JSON rồi dump lại sẽ sai chữ ký."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header.split("=", 1)[1])


@dataclass
class InboundEvent:
    kind: str  # comment | message
    page_fb_id: str
    item_id: str
    sender_id: str
    sender_name: str
    text: str
    created_at: datetime
    post_id: str | None = None
    parent_id: str | None = None


def _from_unix(value: Any, millis: bool = False) -> datetime:
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return utcnow()
    return datetime.fromtimestamp(ts / 1000 if millis else ts, tz=timezone.utc)


def iter_events(payload: dict) -> Iterator[InboundEvent]:
    if payload.get("object") != "page":
        return
    for entry in payload.get("entry", []):
        page_id = str(entry.get("id", ""))

        for change in entry.get("changes", []):
            if change.get("field") != "feed":
                continue
            v = change.get("value", {})
            if v.get("item") != "comment" or v.get("verb") != "add" or not v.get("comment_id"):
                continue
            sender = v.get("from", {})
            if str(sender.get("id")) == page_id:
                continue  # bình luận của chính Page → bỏ qua để không tự trả lời mình (vòng lặp)
            yield InboundEvent(
                kind="comment", page_fb_id=page_id, item_id=v["comment_id"],
                sender_id=str(sender.get("id", "")), sender_name=sender.get("name", ""),
                text=v.get("message", ""), created_at=_from_unix(v.get("created_time")),
                post_id=v.get("post_id"), parent_id=v.get("parent_id"),
            )

        for m in entry.get("messaging", []):
            msg = m.get("message")
            if not msg or msg.get("is_echo") or not msg.get("mid"):
                continue  # echo = tin do chính Page gửi
            text = msg.get("text") or ("[tệp đính kèm]" if msg.get("attachments") else "")
            yield InboundEvent(
                kind="message", page_fb_id=page_id, item_id=msg["mid"],
                sender_id=str(m.get("sender", {}).get("id", "")), sender_name="",
                text=text, created_at=_from_unix(m.get("timestamp"), millis=True),
            )
