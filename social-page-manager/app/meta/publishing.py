"""Đăng bài lên Page qua Pages API.

* Văn bản/link: POST /{page-id}/feed
* Ảnh:          POST /{page-id}/photos  (multipart 'source' hoặc 'url' công khai)
* Video:        POST graph-video.facebook.com/{page-id}/videos
                File lớn (>~1GB hoặc mạng chập chờn) nên dùng Resumable Upload API (upload_phase start/transfer/finish).

Ghi chú: Meta cũng hỗ trợ lịch "native" (published=false + scheduled_publish_time). App này dùng scheduler
riêng để kiểm soát retry/log thống nhất cho mọi loại bài; xem docs/01-architecture.md.
"""
import mimetypes
from pathlib import Path

from app.meta.graph_client import GraphClient


def publish_text(client: GraphClient, fb_page_id: str, token: str, message: str, link: str | None = None) -> str:
    data = {"message": message}
    if link:
        data["link"] = link
    return client.post(f"{fb_page_id}/feed", token, data=data)["id"]


def publish_photo(client: GraphClient, fb_page_id: str, token: str, file_path: str, caption: str = "") -> str:
    path = Path(file_path)
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    with path.open("rb") as fh:
        res = client.post(f"{fb_page_id}/photos", token, data={"message": caption, "published": "true"},
                          files={"source": (path.name, fh, mime)})
    return res.get("post_id") or res["id"]


def publish_video(client: GraphClient, fb_page_id: str, token: str, file_path: str, description: str = "") -> str:
    """Trả về video_id. Video được xử lý bất đồng bộ; trạng thái: GET /{video_id}?fields=status."""
    path = Path(file_path)
    mime = mimetypes.guess_type(path.name)[0] or "video/mp4"
    with path.open("rb") as fh:
        res = client.post(f"{fb_page_id}/videos", token, data={"description": description},
                          files={"source": (path.name, fh, mime)}, video=True)
    return res["id"]


def publish(client: GraphClient, fb_page_id: str, token: str, post_type: str, message: str,
            link: str | None, media_path: str | None) -> str:
    """Điều phối theo loại bài. Trả về ID đối tượng trên Facebook."""
    if post_type == "text":
        return publish_text(client, fb_page_id, token, message, link)
    if post_type == "photo":
        return publish_photo(client, fb_page_id, token, media_path or "", message)
    if post_type == "video":
        return publish_video(client, fb_page_id, token, media_path or "", message)
    raise ValueError(f"post_type không hỗ trợ: {post_type}")
