from playwright.sync_api import sync_playwright, Error as PlaywrightError
from datetime import datetime
import csv
import os
import sys

# Cong cu nghien cuu cho MOT tai khoan TikTok ca nhan:
# tu dong lướt trang For You va ghi lai nhung video thuat toan de xuat vao file CSV.
#   python tiktok_feed_logger.py          -> lướt 50 video, moi video xem 8 giay
#   python tiktok_feed_logger.py 100 10   -> lướt 100 video, moi video xem 10 giay
# Dung profile cua acc1 (profiles/tiktok). Neu chua dang nhap, hay dang nhap tay trong cua so.

PROFILE_DIR = "profiles/tiktok"
OUT_DIR = "feed_logs"
FIELDS = ["seen_at", "video_id", "author", "nickname", "desc", "hashtags",
          "duration_s", "music", "plays", "likes", "comments", "shares", "created_at"]


def is_logged_in(context):
    return any(c["name"] == "sessionid" and c["value"]
               for c in context.cookies("https://www.tiktok.com"))


def wait_for_login(context, page, timeout_s=300):
    # Cho nguoi dung tu dang nhap; dung neu cua so bi dong
    try:
        for _ in range(timeout_s // 2):
            if page.is_closed():
                return False
            if is_logged_in(context):
                return True
            page.wait_for_timeout(2000)
    except PlaywrightError:
        pass  # cua so/trinh duyet bi dong giua chung
    return False


def to_row(item):
    # 1 video trong JSON cua TikTok -> 1 dong CSV
    author = item.get("author") or {}
    stats = item.get("stats") or {}
    created = item.get("createTime")
    return {
        "seen_at": datetime.now().isoformat(timespec="seconds"),
        "video_id": item.get("id"),
        "author": author.get("uniqueId"),
        "nickname": author.get("nickname"),
        "desc": item.get("desc"),
        "hashtags": " ".join("#" + c["title"] for c in item.get("challenges") or [] if c.get("title")),
        "duration_s": (item.get("video") or {}).get("duration"),
        "music": (item.get("music") or {}).get("title"),
        "plays": stats.get("playCount"),
        "likes": stats.get("diggCount"),
        "comments": stats.get("commentCount"),
        "shares": stats.get("shareCount"),
        "created_at": datetime.fromtimestamp(int(created)).isoformat() if created else None,
    }


def run(max_videos, watch_s):
    os.makedirs(OUT_DIR, exist_ok=True)
    out_file = os.path.join(OUT_DIR, f"foryou_{datetime.now():%Y%m%d_%H%M%S}.csv")
    seen = set()

    with sync_playwright() as p, open(out_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()

        def on_response(resp):
            # TikTok tai danh sach de xuat qua API item_list -> doc thang JSON thay vi
            # boc tach HTML (selector cua TikTok doi thuong xuyen)
            if "/api/recommend/item_list" not in resp.url:
                return
            try:
                items = resp.json().get("itemList") or []
            except Exception:
                return
            for item in items:
                if item.get("id") and item["id"] not in seen:
                    seen.add(item["id"])
                    writer.writerow(to_row(item))
            f.flush()
            print(f"Da ghi {len(seen)} video vao {out_file}")

        context = p.chromium.launch_persistent_context(
            PROFILE_DIR, headless=False, channel="chrome")
        page = context.pages[0] if context.pages else context.new_page()

        page.goto("https://www.tiktok.com/foryou")
        page.wait_for_timeout(3000)

        if not is_logged_in(context):
            print("Chua dang nhap. Hay dang nhap tay trong cua so (KHONG dong cua so)...")
            if not wait_for_login(context, page):
                print("Khong dang nhap duoc, dung lai.")
                return

        # Chi ghi du lieu sau khi da dang nhap, de CSV khong lan feed cua khach (chua dang nhap)
        page.on("response", on_response)
        page.goto("https://www.tiktok.com/foryou")
        page.wait_for_timeout(3000)

        # Dua chuot vao giua feed (khong click: click 1 lan se dung video, 2 lan se tha tim)
        vp = page.viewport_size or {"width": 1280, "height": 720}
        page.mouse.move(vp["width"] / 2, vp["height"] / 2)

        try:
            for i in range(max_videos):
                print(f"Video {i + 1}/{max_videos}")
                page.wait_for_timeout(watch_s * 1000)
                page.mouse.wheel(0, vp["height"])
        except PlaywrightError:
            print("Cua so da bi dong, dung lai.")

        print(f"Xong. Tong cong {len(seen)} video duoc de xuat, luu tai {out_file}")
        try:
            context.close()
        except PlaywrightError:
            pass


if __name__ == "__main__":
    max_videos = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    watch_s = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    run(max_videos, watch_s)
