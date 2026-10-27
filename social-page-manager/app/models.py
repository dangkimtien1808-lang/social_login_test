"""ORM models. Giải thích chi tiết từng bảng: docs/03-database.md.

Quy ước: mọi cột thời gian lưu UTC (timezone-aware). Chuyển sang giờ địa phương chỉ khi hiển thị.
"""
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import get_settings
from app.db import Base
from app.utils.timeutil import utcnow


class User(Base):
    """Người dùng app = tài khoản Facebook đã đăng nhập qua OAuth."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    fb_user_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # app-scoped ID
    name: Mapped[str] = mapped_column(String(255), default="")
    user_token_enc: Mapped[str | None] = mapped_column(Text)  # long-lived user token, đã mã hóa
    user_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    data_access_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    granted_scopes: Mapped[str] = mapped_column(Text, default="")  # CSV
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    page_links: Mapped[list["UserPage"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Page(Base):
    """Fanpage đã kết nối. Một Page có thể được nhiều user (admin) cùng quản lý."""

    __tablename__ = "pages"

    id: Mapped[int] = mapped_column(primary_key=True)
    fb_page_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    category: Mapped[str] = mapped_column(String(255), default="")
    page_token_enc: Mapped[str | None] = mapped_column(Text)  # page access token, đã mã hóa
    token_status: Mapped[str] = mapped_column(String(20), default="valid")  # valid | invalid | missing
    token_error: Mapped[str | None] = mapped_column(Text)
    token_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    webhook_subscribed: Mapped[bool] = mapped_column(Boolean, default=False)
    timezone: Mapped[str] = mapped_column(String(64), default=lambda: get_settings().default_timezone)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user_links: Mapped[list["UserPage"]] = relationship(back_populates="page", cascade="all, delete-orphan")


class UserPage(Base):
    """Quan hệ N-N user ↔ page, kèm 'tasks' Meta trả về (CREATE_CONTENT, MODERATE, MESSAGING, ANALYZE...)."""

    __tablename__ = "user_pages"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), primary_key=True)
    tasks: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="page_links")
    page: Mapped[Page] = relationship(back_populates="user_links")


class ScheduledPost(Base):
    """Bài đăng theo lịch. Vòng đời trạng thái: xem docs/03-database.md."""

    __tablename__ = "scheduled_posts"
    __table_args__ = (Index("ix_posts_due", "status", "scheduled_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    post_type: Mapped[str] = mapped_column(String(10))  # text | photo | video
    message: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str | None] = mapped_column(String(2048))
    media_path: Mapped[str | None] = mapped_column(String(1024))
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # scheduled | publishing | published | failed | uncertain | cancelled
    status: Mapped[str] = mapped_column(String(20), default="scheduled")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fb_post_id: Mapped[str | None] = mapped_column(String(128))
    last_error: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    page: Mapped[Page] = relationship()


class WebhookEvent(Base):
    """Payload webhook thô — phục vụ audit/debug. Nên xóa sau ~30 ngày."""

    __tablename__ = "webhook_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    object: Mapped[str] = mapped_column(String(32), default="")
    payload: Mapped[dict] = mapped_column(JSON)
    items_created: Mapped[int] = mapped_column(Integer, default=0)


class InboxItem(Base):
    """Bình luận hoặc tin nhắn đến, đã chuẩn hóa từ webhook."""

    __tablename__ = "inbox_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(10))  # comment | message
    fb_item_id: Mapped[str] = mapped_column(String(128), unique=True)  # comment_id hoặc message mid → chống trùng
    fb_post_id: Mapped[str | None] = mapped_column(String(128))
    parent_id: Mapped[str | None] = mapped_column(String(128))
    sender_id: Mapped[str] = mapped_column(String(64))  # PSID (message) hoặc ID người bình luận
    sender_name: Mapped[str] = mapped_column(String(255), default="")
    text: Mapped[str] = mapped_column(Text, default="")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    is_handled: Mapped[bool] = mapped_column(Boolean, default=False)

    page: Mapped[Page] = relationship()
    replies: Mapped[list["Reply"]] = relationship(back_populates="inbox_item", cascade="all, delete-orphan")


class MessengerThread(Base):
    """Theo dõi thời điểm người dùng nhắn gần nhất → xác định cửa sổ 24 giờ."""

    __tablename__ = "messenger_threads"
    __table_args__ = (UniqueConstraint("page_id", "psid"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"))
    psid: Mapped[str] = mapped_column(String(64))
    last_inbound_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReplyTemplate(Base):
    """Mẫu trả lời theo từ khóa. page_id NULL = áp dụng cho mọi Page."""

    __tablename__ = "reply_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    page_id: Mapped[int | None] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"))
    keyword: Mapped[str] = mapped_column(String(255))
    reply_text: Mapped[str] = mapped_column(Text)
    auto_send: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Reply(Base):
    """Câu trả lời (gợi ý hoặc đã gửi) cho một InboxItem."""

    __tablename__ = "replies"

    id: Mapped[int] = mapped_column(primary_key=True)
    inbox_item_id: Mapped[int] = mapped_column(ForeignKey("inbox_items.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(10))  # suggested | manual | auto
    status: Mapped[str] = mapped_column(String(12), default="suggested")  # suggested|queued|sent|failed|dismissed
    fb_reply_id: Mapped[str | None] = mapped_column(String(128))
    sent_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    inbox_item: Mapped[InboxItem] = relationship(back_populates="replies")


class InsightDaily(Base):
    """Một giá trị metric cho một Page trong một ngày (dạng 'long', dễ thêm metric mới)."""

    __tablename__ = "insights_daily"
    __table_args__ = (UniqueConstraint("page_id", "metric", "date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), index=True)
    metric: Mapped[str] = mapped_column(String(100))
    date: Mapped[date] = mapped_column(Date)
    value: Mapped[float] = mapped_column(Float)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class TaskLog(Base):
    """Nhật ký mọi tác vụ: đăng bài, trả lời, đồng bộ insights, OAuth, kiểm tra token..."""

    __tablename__ = "task_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    task_type: Mapped[str] = mapped_column(String(50), index=True)
    page_id: Mapped[int | None] = mapped_column(ForeignKey("pages.id", ondelete="SET NULL"), index=True)
    status: Mapped[str] = mapped_column(String(10))  # success | error | warning
    detail: Mapped[str] = mapped_column(Text, default="")
    error_code: Mapped[str | None] = mapped_column(String(32))
    fb_trace_id: Mapped[str | None] = mapped_column(String(64))
    duration_ms: Mapped[int | None] = mapped_column(Integer)


class DeletionRequest(Base):
    """Yêu cầu xóa dữ liệu từ Meta Data Deletion Callback (bắt buộc với app public)."""

    __tablename__ = "deletion_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    fb_user_id: Mapped[str] = mapped_column(String(64))
    confirmation_code: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="completed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
