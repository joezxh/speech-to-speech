"""演示面身份：匿名 cookie 或 HF OAuth（移植自 `demo/auth.py`）。

与运维面的 JWT **完全独立**（§10.1）：`/api/*` 只认这里，`/api/v1/*` 只认
`core/security.py`；两者不共享依赖注入，也不把 demo 的 tier 映射成
`admin`/`operator`。tier 只决定「今天能说多少秒」。
"""

from __future__ import annotations

import os
import secrets
from datetime import UTC, datetime, timedelta

from loguru import logger

from app.services import metering_service

# huggingface_hub 挂上来时自带这几个路由；集中在这里，版本改名就是一行的事。
# 路径通过 /api/me 交给前端，前端不硬编码。
OAUTH_LOGIN_PATH = "/oauth/huggingface/login"
OAUTH_LOGOUT_PATH = "/oauth/huggingface/logout"

ANON_COOKIE = "s2s_anon"
_COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 天
_OAUTH_EXPIRY_SKEW = timedelta(seconds=30)

# 这些组织成默认不限量（与 PRO 同档）；UNLIMITED_ORGS 是在此之上追加，不是替换。
_DEFAULT_UNLIMITED_ORGS = {"cerebras", "huggingfacem4", "smolagents", "pollen-robotics"}

# 把探到的 org 与 tier 写进日志和 /api/me，便于在真 Space 上核对组织放行是否生效。
AUTH_DEBUG = bool(os.environ.get("AUTH_DEBUG"))

# 由 attach() 置位：True = 登录真的接上了（可 import + 环境变量在）。
oauth_enabled = False

try:
    from huggingface_hub import attach_huggingface_oauth, parse_huggingface_oauth

    _OAUTH_IMPORTABLE = True
except Exception as exc:  # pragma: no cover - import guard
    logger.info("huggingface_hub OAuth unavailable ({}); sign-in disabled", exc)
    _OAUTH_IMPORTABLE = False

# whoami-v2 的结果按 token 缓存到进程结束：/api/me 与 /api/session 共用一次 Hub 请求。
_whoami_cache: dict[str, dict] = {}


def attach(app) -> bool:
    """能 import 且配了 OAUTH_CLIENT_ID 就把 HF OAuth 挂到 app 上，返回是否可用。

    必须在 `mount_spa()` 之前调用：这里的路由是追加的，兜底的
    `GET /{full_path:path}` 会吞掉之后注册的一切。
    """
    global oauth_enabled
    from app.config import demo

    if not _OAUTH_IMPORTABLE or not demo.oauth_client_id.strip():
        return False
    try:
        attach_huggingface_oauth(app)
        oauth_enabled = True
        logger.info("HF OAuth attached (sign-in enabled)")
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("failed to attach HF OAuth: {}", exc)
        oauth_enabled = False
    return oauth_enabled


def _field(obj, name, default=None):
    """用户信息可能是对象也可能是 dict，两种都读。"""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def current_oauth(request):
    """解析后的 HF OAuth 信息（user_info + access_token），没有就 None。"""
    if not oauth_enabled:
        return None
    try:
        return parse_huggingface_oauth(request)
    except Exception:
        return None


def _oauth_token_expired(info, *, now=None) -> bool:
    """access token 是否过期（含时钟偏移）。"""
    expires_at = _field(info, "access_token_expires_at")
    if expires_at is None:
        # 老版本 huggingface_hub 不暴露这个字段：交给上游校验，不要误判。
        return False
    if not isinstance(expires_at, datetime):
        logger.warning("unexpected OAuth expiry value; requiring a fresh login")
        return True
    if expires_at.tzinfo is None:
        expires_at = expires_at.astimezone(UTC)
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.astimezone(UTC)
    return expires_at <= current + _OAUTH_EXPIRY_SKEW


def _oauth_token(info) -> str | None:
    token = _field(info, "access_token")
    if token is None:
        return None
    return str(token).strip() or None


def oauth_login_required_reason(request) -> str | None:
    """已登录的缓存会话为什么不能用（要重新登录）——没有会话则 None。"""
    info = current_oauth(request)
    if not _field(info, "user_info"):
        return None
    if _oauth_token_expired(info):
        return "token_expired"
    if not _oauth_token(info):
        return "token_invalid"
    return None


def current_access_token(request) -> str | None:
    """登录用户的 HF access token，没有就 None。

    只在服务端用（把 LB 的会话申请记到具体 HF 账号上），**绝不**回给浏览器。
    """
    info = current_oauth(request)
    if _oauth_token_expired(info):
        return None
    return _oauth_token(info)


def _user_org_names(user) -> set[str]:
    """OAuth userinfo 里带的组织名（按 username/name/id 三种键都认）。"""
    names: set[str] = set()
    for org in _field(user, "orgs", []) or []:
        for key in ("preferred_username", "name", "sub"):
            val = _field(org, key)
            if val:
                names.add(str(val).lower())
    return names


def _whoami_via_token(token: str) -> dict:
    """认证过的 Hub `whoami-v2` 档案，按 token 缓存。"""
    if not token:
        return {}
    if token in _whoami_cache:
        return _whoami_cache[token]
    try:
        import httpx

        resp = httpx.get(
            "https://huggingface.co/api/whoami-v2",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5.0,
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            raise ValueError("whoami-v2 returned a non-object response")
    except Exception as exc:  # pragma: no cover - 依赖网络与权限
        logger.info("whoami-v2 profile lookup failed: {}", exc)
        return {}
    _whoami_cache[token] = data
    return data


def _orgs_via_token(token: str, profile=None) -> set[str]:
    """从缓存的 Hub 档案里取组织名。"""
    if profile is None:
        profile = _whoami_via_token(token)
    names: set[str] = set()
    for org in profile.get("orgs", []) or []:
        for key in ("name", "fullname"):
            val = _field(org, key)
            if val:
                names.add(str(val).lower())
    return names


def _org_names(user, token=None, allow=None, profile=None) -> set[str]:
    """用户所在组织。userinfo 里的 claim 常是空的或残缺的，若不满足 `allow`
    就回落到 Hub 的 whoami-v2 再问一次。"""
    names = _user_org_names(user)
    if token and (allow is None or not (allow & names)):
        names = names | _orgs_via_token(token, profile)
    return names


def _unlimited_orgs() -> set[str]:
    """默认不限量的组织集合；UNLIMITED_ORGS（逗号/空格分隔）在上面追加。"""
    raw = os.environ.get("UNLIMITED_ORGS", "")
    extra = {o.strip().lower() for o in raw.replace(",", " ").split() if o.strip()}
    return _DEFAULT_UNLIMITED_ORGS | extra


def resolve_tier(user, token=None) -> str:
    """登录用户的档位：pro（付费）、org（放行组织成员，不限量）、free。
    PRO 优先于 org。"""
    if bool(_field(user, "is_pro", False)):
        return "pro"
    profile = _whoami_via_token(token)
    if bool(profile.get("isPro", False)):
        return "pro"
    allow = _unlimited_orgs()
    names = _org_names(user, token, allow, profile)
    tier = "org" if (allow & names) else "free"
    if AUTH_DEBUG:
        logger.info("tier={} orgs={} allow={}", tier, sorted(names), sorted(allow))
    return tier


def user_view(request, tier=None) -> dict:
    """`/api/me` 的公开身份段。"""
    info = current_oauth(request)
    user = _field(info, "user_info")
    if not user:
        return {"loggedIn": False, "tier": "anon"}
    if _oauth_token_expired(info):
        return {"loggedIn": False, "tier": "anon", "reason": "token_expired"}
    token = _oauth_token(info)
    if not token:
        return {"loggedIn": False, "tier": "anon", "reason": "token_invalid"}
    out = {
        "loggedIn": True,
        "username": _field(user, "preferred_username") or _field(user, "name") or "you",
        "avatar": _field(user, "picture"),
        "tier": tier if tier is not None else resolve_tier(user, token),
    }
    if AUTH_DEBUG:
        out["orgs"] = sorted(_org_names(user, token))
    return out


def _client_ip(request) -> str:
    """真实客户端 IP。HF 上应用在代理后面，地址是 X-Forwarded-For 的首跳。

    信这个头不是安全边界：伪造它换不来新额度，因为 `_spent_max` 对
    ip 键与 cookie 键取 max，cookie 那一半仍然被算进去。"""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def resolve_identity(request) -> tuple[str, list[str], str | None]:
    """解析 `(tier, keys, set_cookie)`。

    `keys` 是要扣的 usage_daily 键（登录一个、匿名两个）；`set_cookie` 是本次
    新签发匿名 id 时要 Set-Cookie 的签名值，否则 None。
    """
    info = current_oauth(request)
    user = _field(info, "user_info")
    token = _oauth_token(info)
    if user and token and not _oauth_token_expired(info):
        sub = _field(user, "sub") or _field(user, "preferred_username")
        return resolve_tier(user, token), [metering_service.hash_key(f"sub:{sub}")], None

    # 匿名：IP 与一个签名 cookie id 双键，缺 cookie 就当场发一个。
    ip = _client_ip(request)
    cookie_id = metering_service.verify_cookie(request.cookies.get(ANON_COOKIE, ""))
    set_cookie = None
    if not cookie_id:
        cookie_id = secrets.token_urlsafe(18)
        set_cookie = metering_service.sign_cookie(cookie_id)
    keys = [metering_service.hash_key(f"ip:{ip}"), metering_service.hash_key(f"cookie:{cookie_id}")]
    return "anon", keys, set_cookie


def set_anon_cookie(response, signed: str) -> None:
    # 真 Space 跑在 huggingface.co 的 iframe 里，cookie 处于跨站上下文，必须
    # SameSite=None; Secure，否则浏览器直接丢掉。本地 http 下这条 cookie 收不到，
    # 所以本地开发不启用计量（`limiter_enabled` 需要 LB + SPACE_ID）。
    response.set_cookie(
        ANON_COOKIE, signed,
        max_age=_COOKIE_MAX_AGE, httponly=True, samesite="none", secure=True,
    )
