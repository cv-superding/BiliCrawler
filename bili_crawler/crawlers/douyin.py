"""抖音采集器。

通过抖音 Web 评论接口采集视频评论（含二级回复，还原回复树）：
1. ``/aweme/v1/web/comment/list/`` 分页获取一级评论；
2. 对含子回复的一级评论，调用 ``/aweme/v1/web/comment/list/reply/`` 获取二级回复。

所有请求均经 :mod:`bili_crawler.utils.douyin_sign` 进行 X-Bogus 签名；
抖音 Web 接口的签名是动态反爬机制，详见 README「抖音平台」章节。

⚠️ 抖音视频**没有「弹幕」**概念，因此抖音平台仅支持评论采集。
"""

from __future__ import annotations

import json
from typing import List

from ..models.douyin_comment import DouyinComment
from ..utils.douyin_parse import extract_aweme_id, extract_sec_uid, resolve_share_url
from ..utils.douyin_sign import DEFAULT_UA, sign_douyin_url
from ..utils.exceptions import ThrottleError
from .base import BaseCrawler

_COMMENT_LIST = "https://www.douyin.com/aweme/v1/web/comment/list/"
_COMMENT_REPLY = "https://www.douyin.com/aweme/v1/web/comment/list/reply/"
_USER_POST = "https://www.douyin.com/aweme/v1/web/aweme/post/"

# 抖音 Web 评论接口的公共固定参数（device_platform / aid 等每次请求相同）
_BASE_PARAMS = {
    "device_platform": "webapp",
    "aid": "6383",
    "channel": "channel_pc_web",
    "version_code": "170400",
    "version_name": "17.4.0",
    "cookie_enabled": "true",
    "screen_width": "1920",
    "screen_height": "1080",
    "browser_language": "zh-CN",
    "browser_platform": "Win32",
    "browser_name": "Edge",
    "browser_version": "122.0.0.0",
    "os_name": "Windows",
    "os_version": "10",
    "platform": "PC",
}


class DouyinCommentCrawler(BaseCrawler):
    """按视频链接 / aweme_id 采集抖音评论（含回复树）。"""

    def __init__(
        self,
        http,
        hooks=None,
        user_agent: str = DEFAULT_UA,
        with_a_bogus: bool = False,
        a_bogus_worker: str = None,
    ):
        super().__init__(http, hooks)
        self.ua = user_agent
        self.with_a_bogus = with_a_bogus
        self.a_bogus_worker = a_bogus_worker
        # 抖音 Cookie（可选，配置在 cookie.douyin，与 B站 Cookie 隔离）
        self.douyin_cookie = (self.http.settings.cookie.get("douyin") or "").strip()

    def crawl(
        self,
        url_or_id: str,
        max_pages: int | None = None,
        with_sub: bool = True,
        title: str | None = None,
    ) -> List[DouyinComment]:
        """采集单个抖音视频的评论。

        Args:
            url_or_id: 视频链接（长链 / 分享短链）或 aweme_id。
            max_pages: 一级评论最大翻页数（None 表示不限）。
            with_sub: 是否递归获取二级回复。
            title: 外部已获取的视频标题（批量采集时传入，避免重复请求）。

        Returns:
            List[DouyinComment]: 评论列表（一级 + 二级混合，靠 parent_id/root_id 还原层级）。
        """
        aweme_id = extract_aweme_id(url_or_id)
        if not aweme_id and is_douyin(url_or_id):
            # 可能是分享短链，尝试解析跳转
            real = resolve_share_url(url_or_id, self.http)
            aweme_id = extract_aweme_id(real) if real else None
        if not aweme_id:
            raise ValueError(f"无法从输入中解析出抖音视频 ID: {url_or_id!r}")

        # 尝试获取视频标题与作者（详情接口失败不影响评论采集，留空）
        author = ""
        if title:
            self._log(f"使用外部传入的视频标题：{title}")
        else:
            try:
                title, author = self._get_aweme_detail(aweme_id)
            except Exception as exc:
                self._log(f"获取视频标题失败，将留空：{exc}")
                title = ""
        self.meta = {"title": title or "", "author": author, "platform": "douyin"}

        self._log(f"抖音视频 aweme_id={aweme_id} 开始采集评论")
        comments: List[DouyinComment] = []
        cursor = 0
        page = 0
        has_more = True

        while has_more:
            self._heartbeat()
            page += 1
            if max_pages and page > max_pages:
                break

            params = dict(_BASE_PARAMS)
            params.update(
                {"aweme_id": aweme_id, "cursor": str(cursor), "count": "20", "item_type": "0"}
            )
            try:
                data = self._signed_get(_COMMENT_LIST, params)
            except ThrottleError as exc:
                self._log(f"评论采集被限流，已停止：{exc}")
                break
            except Exception as exc:
                self._log(f"评论第 {page} 页获取失败: {exc}")
                break

            items = data.get("comments") or []
            if not items:
                break

            for c in items:
                root = int(c.get("cid") or 0)
                dc = self._parse_comment(c, aweme_id, root=root, parent=0, title=title, parent_username="")
                comments.append(dc)
                if with_sub and c.get("reply_comment_total"):
                    comments.extend(
                        self._fetch_sub(
                            str(c.get("cid")),
                            aweme_id,
                            dc.comment_id,
                            dc.username,
                            int(c.get("reply_comment_total", 0)),
                            title,
                        )
                    )

            self._progress(page, 0)  # 总数未知，仅上报已翻页数
            self._log(f"评论第 {page} 页，累计 {len(comments)} 条")

            cursor, has_more = self._next_cursor(data, cursor)
            if cursor == 0 and not has_more:
                break

        self._log(f"评论采集完成，共 {len(comments)} 条")
        return comments

    def _fetch_sub(
        self, comment_id: str, aweme_id: str, root_id: int, parent_username: str,
        total_sub: int, title: str,
    ) -> List[DouyinComment]:
        """获取某条一级评论下的全部二级回复。"""
        subs: List[DouyinComment] = []
        cursor = 0
        while True:
            self._heartbeat()
            params = dict(_BASE_PARAMS)
            params.update(
                {"aweme_id": aweme_id, "comment_id": comment_id, "cursor": str(cursor), "count": "20"}
            )
            try:
                data = self._signed_get(_COMMENT_REPLY, params)
            except Exception as exc:
                self._log(f"二级评论 comment_id={comment_id} 获取失败: {exc}")
                break
            items = data.get("comments") or []
            if not items:
                break
            for c in items:
                # 二级评论的 root 为一级评论 cid；reply_id 为直接父评论
                subs.append(
                    self._parse_comment(
                        c, aweme_id, root=root_id,
                        parent=int(c.get("reply_id") or 0),
                        title=title, parent_username=parent_username,
                    )
                )
            if total_sub and len(subs) >= total_sub:
                break
            cursor, _ = self._next_cursor(data, cursor)
            if cursor == 0:
                break
        return subs

    # ----- 内部方法 -----
    def _signed_get(self, base: str, params: dict) -> dict:
        """构造签名 URL 并请求，返回解析后的 JSON（已做抖音业务码校验）。"""
        from urllib.parse import urlencode

        query = urlencode(params)
        url = f"{base}?{query}"
        signed = sign_douyin_url(
            url, self.ua, with_a_bogus=self.with_a_bogus, worker=self.a_bogus_worker
        )
        headers = {"User-Agent": self.ua, "Referer": "https://www.douyin.com/"}
        if self.douyin_cookie:
            headers["Cookie"] = self.douyin_cookie
        resp = self.http.request("GET", signed, headers=headers)
        try:
            payload = resp.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"抖音响应不是合法 JSON（可能被风控 / 需登录）：{exc}；"
                f"响应前 200 字：{getattr(resp, 'text', '')[:200]}"
            )
        # 抖音业务约定：status_code == 0 为成功
        status = payload.get("status_code", 0)
        if status != 0:
            msg = payload.get("status_msg") or ""
            if status in (1, 2, 8) or any(k in msg for k in ("鉴权", "登录", "sign", "验证")):
                raise ThrottleError(
                    f"抖音接口返回业务错误 status_code={status} message={msg}"
                    f"（多为签名失效或需登录，请检查 Cookie / 是否需启用 a_bogus）"
                )
            raise ValueError(f"抖音接口返回业务错误 status_code={status} message={msg}")
        return payload

    @staticmethod
    def _next_cursor(data: dict, fallback: int):
        """从响应中提取下一页游标与是否还有更多。兼容新旧两种字段结构。"""
        cursor_info = data.get("cursor_info") or {}
        if "cursor" in cursor_info:
            return int(cursor_info.get("cursor", 0)), bool(cursor_info.get("has_more", False))
        if data.get("has_more") is not None:
            return int(data.get("cursor", 0)), bool(data.get("has_more"))
        return 0, False

    @staticmethod
    def _parse_comment(
        c: dict, aweme_id: str, root: int, parent: int,
        title: str = "", parent_username: str = "",
    ) -> DouyinComment:
        """将接口返回的单个评论 JSON 转换为 :class:`DouyinComment`。"""
        user = c.get("user") or {}
        avatar_list = (user.get("avatar_thumb") or {}).get("url_list") or []

        cid = c.get("cid") or c.get("comment_id") or 0
        try:
            cid_int = int(cid)
        except (ValueError, TypeError):
            cid_int = 0

        uid = user.get("uid") or user.get("unique_id") or 0
        try:
            uid_int = int(uid)
        except (ValueError, TypeError):
            uid_int = 0

        ip = user.get("ip_label") or ""
        ip_label = ip[5:] if ip.startswith("IP属地：") else ip

        # reply_id 为父评论（二级回复），一级评论为 0
        reply_id = int(c.get("reply_id") or 0)
        parent_id = reply_id if reply_id else parent

        return DouyinComment(
            comment_id=cid_int,
            aweme_id=aweme_id,
            title=title,
            user_id=uid_int,
            username=user.get("nickname", ""),
            avatar=avatar_list[0] if avatar_list else "",
            content=c.get("text", ""),
            create_time=int(c.get("create_time", 0)),
            digg_count=int(c.get("digg_count", 0)),
            reply_comment_total=int(c.get("reply_comment_total", 0)),
            parent_id=parent_id,
            parent_username=parent_username,
            root_id=root if root else cid_int,
            ip_label=ip_label,
            user_level=int(user.get("user_level") or 0),
            is_author=bool(c.get("is_author")),
            vip=bool(user.get("verification_type") or user.get("author_badge")),
        )

    def _get_aweme_detail(self, aweme_id: str) -> tuple:
        """通过抖音视频详情接口获取视频标题（desc）与作者昵称。

        返回 ``(title, author)``，失败抛异常由调用方处理。
        """
        params = dict(_BASE_PARAMS)
        params.update({"aweme_id": aweme_id})
        data = self._signed_get(
            "https://www.douyin.com/aweme/v1/web/aweme/detail/", params
        )
        detail = (data or {}).get("aweme_detail") or {}
        title = detail.get("desc", "") or ""
        author = (detail.get("author") or {}).get("nickname", "") or ""
        return title, author


class DouyinBatchCrawler(BaseCrawler):
    """按抖音用户主页（sec_user_id）批量采集其全部视频的评论。"""

    def __init__(
        self,
        http,
        hooks=None,
        user_agent: str = DEFAULT_UA,
        with_a_bogus: bool = False,
        a_bogus_worker: str = None,
    ):
        super().__init__(http, hooks)
        self.comment_crawler = DouyinCommentCrawler(
            http, hooks, user_agent, with_a_bogus, a_bogus_worker
        )

    def crawl(
        self,
        source: str,
        source_type: str = "auto",
        kinds: tuple = ("comment",),
        concurrency: int = 1,
        max_videos: int | None = None,
    ) -> dict:
        """批量采集某抖音用户全部视频的评论。

        Args:
            source: 用户主页链接或 sec_user_id。
            source_type: 预留（抖音仅支持用户主页）。
            kinds: 采集类型元组，抖音仅支持 ``comment``。
            concurrency: 预留（当前串行，避免触发风控）。
            max_videos: 最多采集的视频数（None 不限）。

        Returns:
            dict: ``{"danmaku": [], "comment": [...]}``，与 B站批量结果结构一致。
        """
        sec_uid = extract_sec_uid(source)
        if not sec_uid:
            raise ValueError(f"无法从输入中解析出抖音用户 sec_user_id: {source!r}")

        self._log(f"抖音用户 sec_user_id={sec_uid[:20]}... 开始批量采集")
        aweme_list = self._collect_videos(sec_uid, max_videos)
        self._log(f"共发现 {len(aweme_list)} 个视频，开始逐个采集评论")
        author = aweme_list[0][2] if aweme_list else ""
        self.meta = {
            "title": f"抖音用户主页 · 共 {len(aweme_list)} 个视频",
            "author": author,
            "platform": "douyin",
        }

        comments: List[DouyinComment] = []
        for i, (aid, title, author) in enumerate(aweme_list, 1):
            self._heartbeat()
            self._progress(i, len(aweme_list))
            try:
                for c in self.comment_crawler.crawl(aid, with_sub=True, title=title):
                    c.page = i  # 标记来源视频序号
                    comments.append(c)
            except Exception as exc:
                self._log(f"视频 {aid} 评论采集失败: {exc}")

        return {"danmaku": [], "comment": [c.to_dict() for c in comments]}

    def _collect_videos(self, sec_uid: str, max_videos: int | None) -> List[tuple]:
        """遍历用户投稿，收集全部 (aweme_id, title)。"""
        items: List[tuple] = []
        max_cursor = 0
        has_more = True
        while has_more:
            self._heartbeat()
            params = dict(_BASE_PARAMS)
            params.update(
                {
                    "sec_user_id": sec_uid,
                    "max_cursor": str(max_cursor),
                    "count": "18",
                    "locate_query": "false",
                }
            )
            try:
                data = self.comment_crawler._signed_get(_USER_POST, params)
            except Exception as exc:
                self._log(f"视频列表获取失败: {exc}")
                break
            for aw in data.get("aweme_list") or []:
                aid = aw.get("aweme_id")
                if aid:
                    author = (aw.get("author") or {}).get("nickname", "") or ""
                    items.append((str(aid), aw.get("desc", "") or "", author))
            if max_videos and len(items) >= max_videos:
                break
            cursor_info = data.get("cursor_info") or {}
            if "max_cursor" in cursor_info:
                max_cursor = int(cursor_info.get("max_cursor", 0))
                has_more = bool(cursor_info.get("has_more", False))
            else:
                has_more = bool(data.get("has_more"))
                max_cursor = int(data.get("max_cursor", 0))
            if not has_more:
                break
        return items


def is_douyin(text: str) -> bool:
    """判断文本是否像抖音链接。"""
    return "douyin.com" in text or "tiktok.com" in text


def check_douyin_cookie(http) -> tuple:
    """快速验证「配置的抖音 Cookie 是否被服务端接受」。

    用评论列表接口 ``comment/list`` 探测（与真正采集评论走同一接口）：有效 Cookie 会得到
    合法 JSON（即便 aweme_id 为占位值也返回 status_code=0）；失效 / 过期的 Cookie 会被
    抖音风控拦截，返回 HTML 验证页（无法解析为 JSON）。

    .. note::
        不要用 ``aweme/detail`` 探测——该接口对部分 Cookie 会直接返回风控验证页，
        即使 Cookie 实际可用于评论采集，也会误报「失效」。

    Returns:
        (accepted: bool, message: str)
    """
    from urllib.parse import urlencode

    cookie = (http.settings.cookie.get("douyin") or "").strip()
    if not cookie:
        return False, "未配置抖音 Cookie（请在 config.yaml 的 cookie.douyin 填入整段 Cookie 字符串）"

    params = dict(_BASE_PARAMS)
    params.update({"aweme_id": "1", "cursor": "0", "count": "20", "item_type": "0"})
    query = urlencode(params)
    url = f"{_COMMENT_LIST}?{query}"
    signed = sign_douyin_url(url, DEFAULT_UA)
    headers = {"User-Agent": DEFAULT_UA, "Referer": "https://www.douyin.com/"}
    if cookie:
        headers["Cookie"] = cookie
    try:
        resp = http.request("GET", signed, headers=headers)
        resp.json()  # 能解析为 JSON 即说明 Cookie 被服务端接受（非风控验证页）
    except Exception as exc:
        return False, f"抖音接口未返回合法 JSON，Cookie 可能已失效或被风控拦截：{exc}"
    return True, "抖音 Cookie 有效，评论接口已正常响应，可正常采集评论"
