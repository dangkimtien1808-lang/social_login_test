from playwright.sync_api import sync_playwright
from accounts import get_account
import sys
import random  # Thêm thư viện để tạo độ trễ xem video ngẫu nhiên

def is_logged_in(context):
    return any(c["name"] == "sessionid" and c["value"]
               for c in context.cookies("https://tiktok.com"))

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


# =========================================================================
# KHU VỰC CẬP NHẬT: HÀM TỰ ĐỘNG LƯỚT TIKTOK + LIKE CHUẨN VIEWPORT CHỐNG BAN
# =========================================================================
def auto_scroll_tiktok_videos(page, total_videos=15):
    print("[Hệ thống] Bắt đầu chu trình kiểm thử tự động xem video TikTok...")
    
    # Selector tổng của khối video để kiểm tra trạng thái nạp trang
    video_selector = '[data-e2e="recommend-list-item-container"]'
    
    try:
        page.wait_for_selector(video_selector, timeout=10000)
    except Exception:
        print("[ Cảnh báo ] Giao diện video tải hơi chậm, bắt đầu chạy cưỡng bức...")

    for i in range(total_videos):
        if page.is_closed():
            break

        print(f"\n--- Đang kiểm thử video thứ {i+1}/{total_videos} ---")
        
        # 1. Giả lập hành vi xem video trong khoảng thời gian ngẫu nhiên
        watch_time = random.randint(6000, 12000) 
        print(f"[*] Đang giữ màn hình để nạp dữ liệu video và kiểm tra UI trong: {watch_time/1000} giây...")
        page.wait_for_timeout(watch_time)

        # 2. Xử lý tương tác Like ngẫu nhiên (Tỷ lệ 25% - trung bình lướt 4 bài Like 1 bài)
        if random.random() < 0.25:
            try:
                # Quét trực tiếp nút Like hiển thị tích cực trên màn hình dựa theo thuộc tính data-e2e của TikTok
                # Sử dụng bộ lọc lấy nút đầu tiên đang hiển thị thực tế (.filter(visible=True).first)
                like_icon = page.locator('[data-e2e="like-icon"]').filter(has_text="").filter(visible=True).first
                
                if like_icon.is_visible():
                    # Kiểm tra xem nút này đã được bấm hay chưa bằng cách kiểm tra màu sắc (đỏ) của thẻ SVG bên trong
                    svg_element = like_icon.locator('svg').first
                    is_already_liked = False
                    
                    if svg_element.is_visible():
                        svg_class = svg_element.get_attribute("class") or ""
                        # Khi đã ấn thích, thuộc tính class hoặc fill của SVG thường chuyển trạng thái màu sắc đặc trưng
                        if "active" in svg_class.lower() or "color" in svg_class.lower():
                            is_already_liked = True

                    if not is_already_liked:
                        print("[Tương tác] Trúng xác suất ngẫu nhiên. Tiến hành bấm Like video...")
                        page.wait_for_timeout(random.randint(1000, 2000))  # Nghỉ ngắn giả lập phản xạ tay
                        
                        # Click force=True đâm xuyên qua màng bảo vệ video player
                        like_icon.click(force=True)
                        print("[Thành công] Đã tự động bấm Thích video TikTok thành công!")
                        
                        page.wait_for_timeout(random.randint(1500, 2500))
                    else:
                        print("[Bỏ qua] Video này hệ thống ghi nhận bạn đã Thích từ trước.")
                else:
                    print("[Cảnh báo] Không tìm thấy nút Thích hiển thị trên khung giao diện hiện tại.")
            except Exception as e:
                print(f"[Lỗi xử lý] Không thể thao tác nút Like: {str(e)}")

        # 3. Thực hiện hành vi chuyển video bằng cách nhấn phím ArrowDown giống người dùng thật
        print("[*] Nhấn phím Mũi tên xuống để chuyển video tiếp theo...")
        page.keyboard.press("ArrowDown")
        
        # Đợi ổn định hiệu ứng chuyển cảnh mượt mà của TikTok
        page.wait_for_timeout(random.randint(2500, 4000))

        # 4. Kiểm tra nạp DOM để tránh flaky
        try:
            current_loaded_cards = page.locator(video_selector).count()
            js_condition = f"document.querySelectorAll('{video_selector}').length >= {current_loaded_cards}"
            page.wait_for_function(js_condition, timeout=4000)
            print(f"[ Thừa nhận ] Chuyển vùng video thành công. Tổng số block video đã cache: {current_loaded_cards}")
        except Exception:
            pass

    print("[Hệ thống] Kết thúc chu trình tự động lướt video TikTok.")
# =========================================================================


def login_tiktok(acc):
    tag = f"[tiktok/{acc['name']}]"
    session_file = acc["session_file"]
    fail_png = f"tiktok_fail_{acc['name']}.png"

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            acc["profile_dir"], headless=False, channel="chrome")
        page = context.pages[0] if context.pages else context.new_page()

        if not is_logged_in(context) and acc["cookies"]:
            context.add_cookies(acc["cookies"])
            print(tag, f"Da nap {len(acc['cookies'])} cookie tu .env")

        page.goto("https://tiktok.com/")
        page.wait_for_timeout(3000)

        if not is_logged_in(context):
            if acc["email"] and acc["password"]:
                page.goto("https://tiktok.com/login/phone-or-email/email")
                page.wait_for_selector('input[name="username"]')
                page.type('input[name="username"]', acc["email"], delay=80)
                page.type('input[type="password"]', acc["password"], delay=80)
                page.click('button[type="submit"]')
                page.wait_for_timeout(5000)
            else:
                print(tag, "Chua co email/mat khau trong .env, hay dang nhap tay.")
                page.goto("https://tiktok.com/login")

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

        if is_logged_in(context):
            context.storage_state(path=session_file)
            print(tag, "✅ Đăng nhập TikTok thành công, đã lưu session vào", session_file)
            
            page.wait_for_timeout(3000) 
            auto_scroll_tiktok_videos(page, total_videos=20) 
            
        else:
            print(tag, "❌ Đăng nhập TikTok THẤT BẠI")
            print(tag, "URL h hiện tại:", page.url)
            page.screenshot(path=fail_png)
            print(tag, "Da luu anh man hinh vao", fail_png)

        keep_open_until_closed(context, tag)


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "acc1"
    login_tiktok(get_account("tiktok", name))
