"""Mã hóa token khi lưu DB (Fernet = AES-128-CBC + HMAC-SHA256, có xác thực toàn vẹn).

- Khóa nằm ngoài DB (biến môi trường / secret manager / KMS) → lộ DB không lộ token.
- MultiFernet hỗ trợ xoay khóa: khóa đầu tiên dùng để mã hóa, các khóa sau chỉ để giải mã dữ liệu cũ.
  Sau khi thêm khóa mới, chạy rotate_all() (hoặc re-encrypt dần) rồi gỡ khóa cũ.
"""
from functools import lru_cache

from cryptography.fernet import Fernet, MultiFernet

from app.config import get_settings


@lru_cache
def _cipher() -> MultiFernet:
    keys = [k.strip() for k in get_settings().token_encryption_keys.split(",") if k.strip()]
    if not keys:
        raise RuntimeError("TOKEN_ENCRYPTION_KEYS chưa được cấu hình")
    return MultiFernet([Fernet(k) for k in keys])


def encrypt_token(plain: str) -> str:
    return _cipher().encrypt(plain.encode()).decode()


def decrypt_token(encrypted: str) -> str:
    return _cipher().decrypt(encrypted.encode()).decode()


def rotate_token(encrypted: str) -> str:
    """Mã hóa lại bằng khóa mới nhất."""
    return _cipher().rotate(encrypted.encode()).decode()
