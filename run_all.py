from accounts import load_accounts
import subprocess
import sys

# Mở song song mọi tài khoản trong accounts.json, mỗi tài khoản một tiến trình + một profile riêng.
#   python run_all.py                  -> tất cả tài khoản Facebook + TikTok
#   python run_all.py facebook         -> chỉ Facebook
#   python run_all.py tiktok acc2      -> chỉ tài khoản acc2 của TikTok

SCRIPTS = {"facebook": "test_fb_login.py", "tiktok": "test_tiktok_login.py"}


def main():
    platforms = [sys.argv[1]] if len(sys.argv) > 1 else list(SCRIPTS)
    only = set(sys.argv[2:])

    procs = []
    for platform in platforms:
        for acc in load_accounts(platform):
            if only and acc["name"] not in only:
                continue
            print(f"Mo {platform}/{acc['name']} ...")
            procs.append(subprocess.Popen([sys.executable, SCRIPTS[platform], acc["name"]]))

    for proc in procs:
        proc.wait()


if __name__ == "__main__":
    main()
