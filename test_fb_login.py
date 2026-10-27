from playwright.sync_api import sync_playwright
from accounts import get_account
import json
import os
import sys
import random  # Thêm thư viện để tạo độ trễ ngẫu nhiên giống người thật

def is_logged_in(context):
    return any(c["name"] == "c_user" and c["value"]
               for c in context.cookies("https://www.facebook.com"))

def wait_for_login(context, page, timeout_s=300):
    for _ in range(timeout_s // 2):
        if page.is_closed():
            return False
        try:
            if is_logged_in(context):
                return True
            page.wait_for_timeout(2000)
        except Exception:
            return False
    return False

def keep_open_until_closed(context, tag):
    print(tag, "Trinh duyet dang mo. Ban tu dong cua so khi muon ket thuc...")
    try:
        while any(not pg.is_closed() for pg in context.pages):
            context.pages[0].wait_for_timeout(1000)
    except Exception:
        pass

def import_old_session(context, session_file):
    if not os.path.exists(session_file):
        return
    with open(session_file, encoding="utf-8-sig") as f:
        cookies = json.load(f).get("cookies", [])
    if cookies:
        context.add_cookies(cookies)

def import_cred_cookies(context, acc, tag):
    if acc["cookies"]:
        context.add_cookies(acc["cookies"])
        print(tag, f"Da nap {len(acc['cookies'])} cookie tu .env")


# =========================================================================
# KHU VỰC CẬP NHẬT CHUYÊN BIỆT: GIẢ LẬP XEM VIDEO REELS + LIKE NGẪU NHIÊN CHỐNG BAN
# =========================================================================
def auto_scroll_and_count(page, max_scrolls=20):
    print("[Hệ thống] Bắt đầu chu trình lướt Reels và tương tác Like ngẫu nhiên...")
    
    # Đợi ổn định giao diện trình phát video khi nạp trang lần đầu
    page.wait_for_timeout(3000)
    
    for i in range(max_scrolls):
        if page.is_closed():
            break
            
        print(f"\n--- Đang xem video thứ {i+1}/{max_scrolls} ---")
        
        # Giả lập thời gian xem video ngẫu nhiên từ 6 đến 12 giây giống hành vi người thật
        watch_time = random.randint(6000, 12000)
        print(f"[*] Đang giữ màn hình để xem nội dung video trong: {watch_time/1000} giây...")
        page.wait_for_timeout(watch_time)
        
        # Xử lý tương tác Like ngẫu nhiên: Xác suất 40% (trung bình lướt 2-3 video sẽ bấm Like 1 lần)
        if random.random() < 0.15:
            try:
                # Quét trực tiếp nút Like đang hiện hữu trên khung nhìn (Hỗ trợ cả giao diện EN/VI)
                like_button = page.locator('div[role="button"][aria-label="Like"], div[role="button"][aria-label="Thích"]').first
                
                if like_button.is_visible():
                    # Đọc trạng thái xem nút này đã được tài khoản bấm thích từ trước chưa
                    is_already_liked = like_button.get_attribute("aria-pressed") == "true"
                    
                    if not is_already_liked:
                        print("[Tương tác] Phát hiện nút Thích hợp lệ. Tiến hành bấm Like...")
                        # Nghỉ ngắn 1-2 giây trước khi bấm nhằm mô phỏng tốc độ phản xạ của mắt người
                        page.wait_for_timeout(random.randint(1000, 2500))
                        
                        # Dùng thuộc tính force=True giúp ép click đâm xuyên qua lớp phủ bóng (overlay) của video
                        like_button.click(force=True)
                        print("[Thành công] Đã tự động bấm Thích video Reels ngẫu nhiên!")
                        
                        # Nghỉ thêm sau khi tương tác xong để hành vi mượt mà
                        page.wait_for_timeout(random.randint(1500, 3000))
                    else:
                        print("[Bỏ qua] Video này bạn đã bấm Thích từ trước đó rồi.")
                else:
                    print("[Cảnh báo] Không tìm thấy nút Thích hiển thị trên khung giao diện hiện tại.")
            except Exception as e:
                print(f"[Lỗi xử lý] Không thể thao tác bấm Like: {str(e)}")
                
        # Giả lập thao tác nhấn phím Mũi tên xuống để chuyển đổi video tiếp theo (chuẩn thao tác máy tính)
        print("[*] Nhấn phím Mũi tên xuống để chuyển sang video tiếp theo...")
        page.keyboard.press("ArrowDown")
        
        # Đợi một chút ngắn sau khi chuyển video để nội dung kế tiếp kịp nạp (cache) vào luồng
        page.wait_for_timeout(random.randint(2500, 4500))

    print("[Hệ thống] Kết thúc toàn bộ chu trình kiểm thử và tương tác Video Reels.")
# =========================================================================


def login_facebook(acc):
    tag = f"[facebook/{acc['name']}]"
    session_file = acc["session_file"]
    fail_png = f"fb_fail_{acc['name']}.png"

    with sync_playwright() as p:
        context = p.firefox.launch_persistent_context(acc["profile_dir"], headless=False)
        page = context.pages[0] if context.pages else context.new_page()

        if not is_logged_in(context):
            import_cred_cookies(context, acc, tag)   
        if not is_logged_in(context):
            import_old_session(context, session_file)

        page.goto("https://www.facebook.com/")
        page.wait_for_timeout(3000)

        if not is_logged_in(context):
            if acc["email"] and acc["password"]:
                print(tag, "Session het han, dang nhap lai bang tai khoan trong .env ...")
                page.fill('input[name="email"]', acc["email"])
                page.fill('input[name="pass"]', acc["password"])
                page.press('input[name="pass"]', "Enter")
                page.wait_for_timeout(5000)
            else:
                print(tag, "Chua co email/mat khau trong .env, hay dang nhap tay.")

        if not is_logged_in(context):
            print(tag, "Chua dang nhap duoc. Hay xu ly captcha/xac minh hoac dang nhap tay "
                  "trong trinh duyet (KHONG dong cua so). Script tu nhan dien khi xong...")
            if not wait_for_login(context, page):
                if page.is_closed():
                    print(tag, "Cua so trinh duyet da bi dong truoc khi dang nhap xong.")
                else:
                    print(tag, "Het 5 phut ma van chua dang nhap duoc. URL:", page.url)
                    page.screenshot(path=fail_png)
                    print(tag, "Da luu anh man hinh vao", fail_png)
                    keep_open_until_closed(context, tag)
                return

        if "/checkpoint/" in page.url:
            print(tag, "Tai khoan Facebook dang bi KHOA / cho xem xet khang nghi (checkpoint)")
            print(tag, "URL hien tai:", page.url)
            page.screenshot(path=fail_png)
            print(tag, "Da luu anh man hinh vao", fail_png)
            
        elif is_logged_in(context):
            context.storage_state(path=session_file)
            print(tag, "Dang nhap Facebook thanh cong, da luu session vao", session_file)
            
            page.wait_for_timeout(2000) 
            auto_scroll_and_count(page, max_scrolls=30) 
            
        else:
            print(tag, "Dang nhap Facebook THAT BAI")
            print(tag, "URL hien tai:", page.url)
            page.screenshot(path=fail_png)
            print(tag, "Da luu anh man hinh vao", fail_png)

        keep_open_until_closed(context, tag)

if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "acc1"
    login_facebook(get_account("facebook", name))
