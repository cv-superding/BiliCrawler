"""抖音输入解析工具：从分享链接 / 主页链接 / 文本中提取结构化标识。

抖音常见链接形态：
- 长链接：``https://www.douyin.com/video/<aweme_id>`` 或 ``/note/<aweme_id>``
- 分享短链：``https://v.douyin.com/<share_id>/``（需跳转解析到长链）
- 用户主页：``https://www.douyin.com/user/<sec_user_id>`` 或含 ``sec_user_id=`` 参数

与 B站不同，抖音视频用 ``aweme_id``（纯数字，>=10 位）标识，用户用 ``sec_user_id``
（Base64 风格长串）标识。``resolve_share_url`` 需要一次网络请求来解析短链跳转，
因此接收已构造好的 ``http`` 客户端作为参数。
"""

from __future__ import annotations

import re

from .douyin_sign import DEFAULT_UA

_AWEME_RE = re.compile(r"/(?:video|note)/(\d{6,})")
_SEC_UID_RE = re.compile(r"sec_user_id=([^&\s]+)")
_USER_RE = re.compile(r"/user/([^/?#]+)")
_SHARE_RE = re.compile(r"v\.douyin\.com/([A-Za-z0-9]+)")


def extract_aweme_id(text: str) -> str | None:
    """从文本/URL 中提取视频 aweme_id（纯数字，>=10 位）。"""
    m = _AWEME_RE.search(text)
    if m:
        return m.group(1)
    # 纯数字 ID（>=10 位）直接视作 aweme_id
    digits = re.sub(r"\D", "", text)
    if len(digits) >= 10:
        return digits
    return None


def extract_sec_uid(text: str) -> str | None:
    """从用户主页链接/文本中提取 sec_user_id（Base64 风格长串）。"""
    m = _SEC_UID_RE.search(text)
    if m:
        return m.group(1)
    m = _USER_RE.search(text)
    if m:
        return m.group(1)
    return None


def is_share_link(text: str) -> bool:
    """判断是否为抖音分享短链（v.douyin.com）。"""
    return bool(_SHARE_RE.search(text))


def resolve_share_url(url: str, http) -> str | None:
    """解析抖音分享短链（v.douyin.com/xxx）到真实长链，返回最终 URL。

    Args:
        url: 分享短链。
        http: :class:`~bili_crawler.utils.http.HTTPClient` 实例（用于发起请求）。

    Returns:
        str | None: 解析后的最终 URL；失败返回 None。
    """
    try:
        resp = http.request(
            "GET", url, headers={"User-Agent": DEFAULT_UA, "Referer": "https://www.douyin.com/"}
        )
        return getattr(resp, "url", None)
    except Exception:
        return None
