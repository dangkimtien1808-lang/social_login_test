"""Xóa token/secret khỏi chuỗi trước khi ghi log — phòng hờ thư viện nhúng URL vào thông báo lỗi."""
import re

_PATTERNS = [
    re.compile(r"(access_token|appsecret_proof|client_secret|fb_exchange_token|input_token)=[^&\s\"']+", re.I),
]


def redact(text: str) -> str:
    for pattern in _PATTERNS:
        text = pattern.sub(r"\1=***", text)
    return text
