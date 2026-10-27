"""Facebook Login (OAuth 2.0 Authorization Code) và quản lý token.

Luồng token:
  code ──► short-lived user token (~1-2 giờ)
       ──► long-lived user token (~60 ngày)       [fb_exchange_token]
       ──► page access token từ /me/accounts      [lấy từ long-lived user token → KHÔNG có hạn cố định,
                                                    nhưng mất hiệu lực khi đổi mật khẩu, mất quyền admin,
                                                    gỡ app, hoặc hết 'data access' 90 ngày]
"""
from urllib.parse import urlencode

from app.config import get_settings
from app.meta.graph_client import GraphClient


def build_login_url(state: str) -> str:
    s = get_settings()
    params = {
        "client_id": s.meta_app_id,
        "redirect_uri": s.oauth_redirect_uri,
        "state": state,  # chống CSRF, phải khớp khi callback
        "response_type": "code",
    }
    if s.meta_login_config_id:
        # Facebook Login for Business: quyền được cấu hình sẵn trong configuration
        params["config_id"] = s.meta_login_config_id
    else:
        params["scope"] = ",".join(s.oauth_scopes)
    return f"https://www.facebook.com/{s.meta_graph_version}/dialog/oauth?{urlencode(params)}"


def exchange_code(client: GraphClient, code: str) -> dict:
    s = get_settings()
    return client.get("oauth/access_token", client_id=s.meta_app_id, client_secret=s.meta_app_secret,
                      redirect_uri=s.oauth_redirect_uri, code=code)


def exchange_long_lived_user_token(client: GraphClient, short_token: str) -> dict:
    """Trả về {'access_token', 'token_type', 'expires_in'?}."""
    s = get_settings()
    return client.get("oauth/access_token", grant_type="fb_exchange_token", client_id=s.meta_app_id,
                      client_secret=s.meta_app_secret, fb_exchange_token=short_token)


def get_me(client: GraphClient, user_token: str) -> dict:
    return client.get("me", user_token, fields="id,name")


def get_managed_pages(client: GraphClient, user_token: str) -> list[dict]:
    """Các Page user có vai trò. Mỗi phần tử có access_token riêng của Page."""
    return list(client.paginate("me/accounts", user_token, fields="id,name,category,access_token,tasks", limit=100))


def debug_token(client: GraphClient, input_token: str) -> dict:
    """Kiểm tra token bằng app token: is_valid, expires_at, data_access_expires_at, scopes."""
    s = get_settings()
    app_token = f"{s.meta_app_id}|{s.meta_app_secret}"
    return client.request("GET", "debug_token", app_token, params={"input_token": input_token},
                          app_token=True).get("data", {})


def subscribe_page_webhooks(client: GraphClient, fb_page_id: str, page_token: str) -> bool:
    """Đăng ký app nhận webhook của Page (cần pages_manage_metadata)."""
    res = client.post(f"{fb_page_id}/subscribed_apps", page_token,
                      data={"subscribed_fields": get_settings().webhook_fields})
    return bool(res.get("success"))
