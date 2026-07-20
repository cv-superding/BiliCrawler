"""输入解析工具：从用户提供的 URL / ID 文本中提取结构化标识。

支持：BV 号、av 号、UP 主空间 mid、收藏夹 media_id、合集/频道 sid/cid 等。
弹幕采集需要 cid（通过 view 接口获取），评论采集需要 aid，因此核心解析只负责
提取「用户提供的原始标识」，真正的 BV->aid/cid 解析交由 crawlers 调用 view 接口完成。
"""

from __future__ import annotations

import re

_BV_RE = re.compile(r"BV[0-9A-Za-z]+")
_AV_RE = re.compile(r"a[vV](\d+)", re.IGNORECASE)
_MID_RE = re.compile(r"space\.bilibili\.com/(\d+)")
_MEDIA_RE = re.compile(r"(?:media_id|fid)=(\d+)")
_SID_RE = re.compile(r"[?&]sid=(\d+)")
_CID_RE = re.compile(r"[?&]cid=(\d+)")


def extract_bvid(text: str) -> str | None:
    """从文本/URL 中提取 BV 号（如 ``BV1xx411c7mD``）。"""
    m = _BV_RE.search(text)
    return m.group(0) if m else None


def extract_aid(text: str) -> int | None:
    """从文本/URL 中提取 av 号并返回整数 aid。"""
    m = _AV_RE.search(text)
    return int(m.group(1)) if m else None


def extract_mid(text: str) -> int | None:
    """从 UP 主空间 URL 中提取数字 mid（如 ``space.bilibili.com/123456``）。"""
    m = _MID_RE.search(text)
    return int(m.group(1)) if m else None


def extract_media_id(text: str) -> int | None:
    """从收藏夹 URL 中提取 media_id（如 ``?fid=12345`` / ``?media_id=12345``）。"""
    m = _MEDIA_RE.search(text)
    return int(m.group(1)) if m else None


def extract_sid_cid(text: str) -> tuple[int | None, int | None, int | None]:
    """从合集/频道 URL 中提取 (mid, sid, cid)。

    Returns:
        tuple: (mid, sid, cid)，未匹配部分为 None。
    """
    return extract_mid(text), extract_sid_cid_sid(text), extract_sid_cid_cid(text)


def extract_sid_cid_sid(text: str) -> int | None:
    m = _SID_RE.search(text)
    return int(m.group(1)) if m else None


def extract_sid_cid_cid(text: str) -> int | None:
    m = _CID_RE.search(text)
    return int(m.group(1)) if m else None


def is_url(text: str) -> bool:
    """判断文本是否像一个 URL。"""
    return text.strip().lower().startswith(("http://", "https://"))
