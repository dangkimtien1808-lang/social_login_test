"""Phân loại lỗi Graph API để quyết định: retry, tạm dừng, yêu cầu kết nối lại, hay bỏ.

Tham khảo: developers.facebook.com/docs/graph-api/guides/error-handling
"""
from enum import Enum


class ErrorKind(str, Enum):
    TOKEN_INVALID = "token_invalid"      # 190/102: token hết hạn, bị thu hồi, đổi mật khẩu...
    PERMISSION = "permission"            # 10, 200-299: thiếu quyền / chưa được duyệt
    RATE_LIMIT = "rate_limit"            # 4, 17, 32, 613, 8000x: vượt hạn mức
    TRANSIENT = "transient"              # 1, 2, is_transient, HTTP 5xx: thử lại được
    DUPLICATE = "duplicate"              # 506: đăng trùng nội dung
    POLICY_BLOCK = "policy_block"        # 368: bị chặn tạm thời do vi phạm chính sách/spam
    INVALID_REQUEST = "invalid_request"  # 100: tham số sai, metric không tồn tại...
    UNKNOWN = "unknown"


TOKEN_CODES = {102, 190}
RATE_LIMIT_CODES = {4, 17, 32, 613, 80001, 80002, 80003, 80004, 80005, 80006, 80008, 80009, 80014}
TRANSIENT_CODES = {1, 2}

# error_subcode của mã 190 → thông báo dễ hiểu cho người dùng
TOKEN_SUBCODE_HINTS = {
    458: "Người dùng đã gỡ app khỏi tài khoản.",
    459: "Tài khoản Facebook bị checkpoint — cần đăng nhập Facebook để xác minh.",
    460: "Người dùng đã đổi mật khẩu — cần kết nối lại.",
    463: "Token đã hết hạn — cần kết nối lại.",
    464: "Tài khoản chưa xác minh.",
    467: "Token không hợp lệ (đã đăng xuất hoặc bị thu hồi).",
    492: "Người dùng không còn quyền quản trị Page này.",
}


def classify(code: int | None, subcode: int | None, http_status: int | None, is_transient: bool) -> ErrorKind:
    if code in TOKEN_CODES:
        return ErrorKind.TOKEN_INVALID
    if code in RATE_LIMIT_CODES:
        return ErrorKind.RATE_LIMIT
    if code == 368:
        return ErrorKind.POLICY_BLOCK
    if code == 506:
        return ErrorKind.DUPLICATE
    if code == 10 or (code is not None and 200 <= code <= 299):
        return ErrorKind.PERMISSION
    if is_transient or code in TRANSIENT_CODES or (http_status is not None and http_status >= 500):
        return ErrorKind.TRANSIENT
    if code == 100 or http_status == 400:
        return ErrorKind.INVALID_REQUEST
    return ErrorKind.UNKNOWN


class GraphAPIError(Exception):
    """Graph API trả về object 'error' — yêu cầu đã đến Meta và bị từ chối (không có tác dụng phụ)."""

    def __init__(self, message: str, *, code: int | None = None, subcode: int | None = None,
                 http_status: int | None = None, fbtrace_id: str | None = None,
                 is_transient: bool = False, user_message: str | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.subcode = subcode
        self.http_status = http_status
        self.fbtrace_id = fbtrace_id
        self.is_transient = is_transient
        self.user_message = user_message
        self.kind = classify(code, subcode, http_status, is_transient)

    @classmethod
    def from_response(cls, http_status: int, body: dict) -> "GraphAPIError":
        err = body.get("error") or {}
        return cls(
            err.get("message") or f"HTTP {http_status}",
            code=err.get("code"),
            subcode=err.get("error_subcode"),
            http_status=http_status,
            fbtrace_id=err.get("fbtrace_id"),
            is_transient=bool(err.get("is_transient")),
            user_message=err.get("error_user_msg"),
        )

    @property
    def code_str(self) -> str:
        return f"{self.code}/{self.subcode}" if self.subcode else str(self.code)

    def hint(self) -> str:
        if self.kind == ErrorKind.TOKEN_INVALID:
            return TOKEN_SUBCODE_HINTS.get(self.subcode or 0, "Token không còn hợp lệ — cần kết nối lại.")
        return self.user_message or self.message

    def __str__(self) -> str:
        return f"[{self.kind.value} {self.code_str}] {self.message}"


class TransportError(Exception):
    """Lỗi mạng. request_sent=True nghĩa là yêu cầu CÓ THỂ đã được Meta xử lý (vd timeout khi chờ phản hồi)
    → với thao tác ghi (đăng bài) KHÔNG được tự retry, tránh đăng trùng."""

    def __init__(self, message: str, *, request_sent: bool):
        super().__init__(message)
        self.request_sent = request_sent
