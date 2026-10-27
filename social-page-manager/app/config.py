"""Cấu hình đọc từ biến môi trường / file .env (pydantic-settings)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# Quyền xin khi đăng nhập. Xem docs/02-permissions-app-review.md cho lý do từng quyền.
DEFAULT_SCOPES = [
    "pages_show_list",          # liệt kê Page user quản lý
    "pages_read_engagement",    # đọc nội dung/tương tác Page, cần cho nhiều endpoint khác
    "pages_manage_posts",       # tạo/sửa/xóa bài đăng
    "pages_manage_metadata",    # đăng ký webhook cho Page (subscribed_apps)
    "pages_read_user_content",  # đọc bình luận của người dùng trên Page
    "pages_manage_engagement",  # trả lời bình luận
    "pages_messaging",          # gửi tin nhắn Messenger thay mặt Page
    "read_insights",            # Page Insights
]

# Tên metric Insights thay đổi theo thời gian (Meta đã khai tử nhiều metric "impressions").
# Luôn đối chiếu với tài liệu Page Insights hiện hành; metric không hợp lệ sẽ bị bỏ qua và ghi log.
DEFAULT_INSIGHTS_METRICS = [
    "page_media_view",
    "page_total_media_view_unique",
    "page_post_engagements",
    "page_daily_follows_unique",
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_base_url: str = "http://localhost:8000"
    session_secret: str

    meta_app_id: str
    meta_app_secret: str
    meta_graph_version: str = "v24.0"
    meta_login_config_id: str = ""
    meta_webhook_verify_token: str

    token_encryption_keys: str  # danh sách khóa Fernet, phân tách bằng dấu phẩy

    database_url: str = "sqlite:///./spm.db"
    media_dir: str = "./media"
    default_timezone: str = "Asia/Taipei"

    oauth_scopes: list[str] = DEFAULT_SCOPES
    insights_metrics: list[str] = DEFAULT_INSIGHTS_METRICS
    webhook_fields: str = "feed,messages"

    @property
    def oauth_redirect_uri(self) -> str:
        return f"{self.app_base_url.rstrip('/')}/auth/callback"

    @property
    def is_https(self) -> bool:
        return self.app_base_url.startswith("https://")


@lru_cache
def get_settings() -> Settings:
    return Settings()
