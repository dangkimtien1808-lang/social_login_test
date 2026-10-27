from dotenv import load_dotenv
import json
import os
import re

load_dotenv()

ACCOUNTS_FILE = "accounts.json"
ENV_PREFIX = {"facebook": "FB", "tiktok": "TIKTOK"}
COOKIE_DOMAIN = {"facebook": ".facebook.com", "tiktok": ".tiktok.com"}


def _parse_cookie_string(raw, domain):
    # "c_user=...; xs=...; datr=..." -> danh sach cookie cho Playwright
    cookies = []
    for pair in raw.split(";"):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        name, value = pair.split("=", 1)
        name, value = name.strip(), value.strip()
        if not name or not value:
            continue
        cookies.append({
            "name": name, "value": value,
            "domain": domain, "path": "/",
        })
    return cookies


def _classify_segment(seg, platform):
    # Nhan dien 1 doan trong chuoi "a|b|c|d" la loai gi
    s = seg.strip()
    if not s:
        return None, None
    if "c_user=" in s or "sessionid=" in s or (";" in s and "=" in s):
        return "cookie", s
    if re.fullmatch(r"EAA[A-Za-z0-9]+", s):
        return "token", s
    if s.isdigit():
        return "uid", s
    return "other", s  # username hoac password


def _parse_credential(raw, platform):
    # Nhan nguyen chuoi tu .env, tra ve (login_id, password, cookies, token).
    # Ho tro: email/sdt/uid don gian, hoac chuoi "uid|pass|cookie|token".
    out = {"login_id": None, "password": None, "cookies": [], "token": None}
    if not raw:
        return out

    if "|" in raw:
        uid = others = None
        others = []
        for seg in raw.split("|"):
            kind, val = _classify_segment(seg, platform)
            if kind == "cookie":
                out["cookies"] = _parse_cookie_string(val, COOKIE_DOMAIN[platform])
            elif kind == "token":
                out["token"] = val
            elif kind == "uid":
                uid = val
            elif kind == "other":
                others.append(val)
        # Doan "other" dau tien coi la mat khau (vi tri thu 2 trong dinh dang pho bien)
        if others:
            out["password"] = others[0]
        out["login_id"] = uid or (others[0] if others else None)
    else:
        out["login_id"] = raw.strip()
    return out


def load_accounts(platform):
    # Danh sach tai khoan lay tu accounts.json (khong chua mat khau).
    # Trong .env, moi tai khoan co tien to rieng, vi du FB_ACC2_...:
    #   FB_ACC2_CRED     = nguyen chuoi "uid|matkhau|cookie|token"  (uu tien cao nhat)
    #   FB_ACC2_COOKIE   = chi rieng chuoi cookie "c_user=...;xs=..."
    #   FB_ACC2_EMAIL    = email / sdt / uid / username
    #   FB_ACC2_PASSWORD = mat khau
    with open(ACCOUNTS_FILE, encoding="utf-8-sig") as f:
        entries = json.load(f).get(platform, [])

    accounts = []
    for e in entries:
        name = e["name"]
        prefix = e.get("env_prefix", f"{ENV_PREFIX[platform]}_{name.upper()}")

        cred = _parse_credential(os.getenv(f"{prefix}_CRED"), platform)

        # Cho phep khai bao rieng tung truong, ghi de len ket qua tach tu CRED
        email = os.getenv(f"{prefix}_EMAIL") or cred["login_id"]
        password = os.getenv(f"{prefix}_PASSWORD") or cred["password"]
        cookie_raw = os.getenv(f"{prefix}_COOKIE")
        cookies = (_parse_cookie_string(cookie_raw, COOKIE_DOMAIN[platform])
                   if cookie_raw else cred["cookies"])

        accounts.append({
            "platform": platform,
            "name": name,
            "email": email,
            "password": password,
            "cookies": cookies,
            "token": cred["token"],
            "profile_dir": e.get("profile_dir", f"profiles/{platform}_{name}"),
            "session_file": e.get("session_file", f"sessions/{platform}_{name}.json"),
        })
    return accounts


def get_account(platform, name):
    for acc in load_accounts(platform):
        if acc["name"] == name:
            os.makedirs(os.path.dirname(acc["session_file"]) or ".", exist_ok=True)
            return acc
    raise SystemExit(f"Khong tim thay tai khoan '{name}' cua {platform} trong {ACCOUNTS_FILE}")
