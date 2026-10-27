"""Giải mã 'signed_request' Meta gửi tới Deauthorize Callback và Data Deletion Callback."""
import base64
import hashlib
import hmac
import json


def _b64url_decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def parse_signed_request(signed_request: str, app_secret: str) -> dict | None:
    """Trả về payload (có 'user_id') nếu chữ ký hợp lệ, ngược lại None."""
    try:
        encoded_sig, payload = signed_request.split(".", 1)
        sig = _b64url_decode(encoded_sig)
        data = json.loads(_b64url_decode(payload))
    except (ValueError, json.JSONDecodeError):
        return None
    if str(data.get("algorithm", "")).upper() != "HMAC-SHA256":
        return None
    expected = hmac.new(app_secret.encode(), payload.encode(), hashlib.sha256).digest()
    return data if hmac.compare_digest(sig, expected) else None
