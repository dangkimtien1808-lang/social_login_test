"""Trả lời bình luận và gửi tin nhắn Messenger.

Quy tắc Messenger Platform:
  * Chỉ nhắn được cho người ĐÃ nhắn Page trước (PSID có được từ webhook).
  * Trong 24 giờ kể từ tin nhắn gần nhất của người dùng: gửi tự do (messaging_type=RESPONSE).
  * Ngoài 24 giờ: chỉ được dùng message tag hợp lệ (vd HUMAN_AGENT — tối đa 7 ngày, cần xin quyền riêng)
    và TUYỆT ĐỐI không gửi nội dung quảng cáo. App này chặn cứng ngoài cửa sổ 24 giờ.
"""
import json
from datetime import datetime, timedelta

from app.meta.graph_client import GraphClient
from app.utils.timeutil import ensure_utc, utcnow

MESSENGER_WINDOW = timedelta(hours=24)


class OutsideMessagingWindow(Exception):
    pass


def within_window(last_inbound_at: datetime | None, now: datetime | None = None) -> bool:
    last = ensure_utc(last_inbound_at)
    if last is None:
        return False
    return (now or utcnow()) - last < MESSENGER_WINDOW


def send_text_message(client: GraphClient, fb_page_id: str, token: str, psid: str, text: str,
                      last_inbound_at: datetime | None, now: datetime | None = None) -> str:
    if not within_window(last_inbound_at, now):
        raise OutsideMessagingWindow("Đã quá 24 giờ kể từ tin nhắn cuối của khách — không thể gửi tin thường.")
    res = client.post(f"{fb_page_id}/messages", token, data={
        "recipient": json.dumps({"id": psid}),
        "messaging_type": "RESPONSE",
        "message": json.dumps({"text": text}),
    })
    return res.get("message_id", "")


def reply_to_comment(client: GraphClient, comment_id: str, token: str, text: str) -> str:
    """Trả lời công khai dưới bình luận (pages_manage_engagement)."""
    return client.post(f"{comment_id}/comments", token, data={"message": text})["id"]
