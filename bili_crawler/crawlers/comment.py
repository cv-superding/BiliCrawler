"""评论采集器。

逐页爬取视频评论区，支持按热度 / 时间排序，并递归获取二级（子）评论以还原回复层级树。
- 一级评论：``x/v2/reply/wbi/main``（需 WBI 签名，游标分页）
- 二级评论：``x/v2/reply/reply``（按 root 评论 ID 分页）
"""

from __future__ import annotations

import json
from typing import List

from ..models.comment import Comment
from ..utils.parse import extract_aid, extract_bvid
from ..utils.exceptions import ThrottleError
from .base import BaseCrawler


class CommentCrawler(BaseCrawler):
    """按 BV 号 / URL / av 号采集视频评论（含回复树）。"""

    def crawl(
        self,
        bvid_or_url: str,
        sort: str = "time",
        max_pages: int | None = None,
        with_sub: bool = True,
    ) -> List[Comment]:
        """采集单个视频的评论。

        Args:
            bvid_or_url: BV 号、完整视频 URL 或 av 号。
            sort: 排序方式，"time" 按时间（最新），"hot" 按热度。
            max_pages: 一级评论最大翻页数（None 表示不限）。
            with_sub: 是否递归获取二级评论。

        Returns:
            List[Comment]: 评论对象列表（一级 + 二级混合，靠 parent/root 还原层级）。
        """
        bvid = extract_bvid(bvid_or_url)
        aid = extract_aid(bvid_or_url)
        if not bvid and not aid:
            raise ValueError(f"无法从输入中解析出 BV 号或 av 号: {bvid_or_url!r}")

        info = self._get_video_info(bvid=bvid, aid=aid)
        aid = info.get("aid") or aid
        bvid = info.get("bvid") or bvid
        title = info.get("title", "")
        author = (info.get("owner") or {}).get("name", "")
        self.meta = {"title": title, "author": author, "platform": "bilibili"}
        self._log(f"视频《{title}》开始采集评论（排序={sort}）")

        # mode: 2=按时间(最新), 3=按热度
        mode = 3 if sort == "hot" else 2
        comments: List[Comment] = []
        offset = ""
        page = 0

        while True:
            self._heartbeat()
            page += 1
            if max_pages and page > max_pages:
                break

            params = {
                "oid": aid,
                "type": 1,
                "mode": mode,
                "pagination_str": json.dumps({"offset": offset}),
                "web_location": "1315875",
                "plat": 1,
            }
            resp = self._get_json_with_cooldown(
                "https://api.bilibili.com/x/v2/reply/wbi/main",
                params=params,
                sign_wbi=True,
                what=f"评论第 {page} 页",
            )
            if resp is None:
                break

            data = resp.get("data") or {}
            replies = data.get("replies") or []
            if not replies:
                break

            for r in replies:
                root_rpid = r.get("rpid")
                c = self._parse_comment(
                    r, bvid=bvid, aid=aid, page_no=1, title=title,
                    root=root_rpid, parent=0, parent_username="",
                )
                comments.append(c)
                if with_sub and root_rpid:
                    comments.extend(
                        self._fetch_sub(
                            root_rpid, aid=aid, bvid=bvid, title=title,
                            total_sub=c.sub_reply_count, page_no=1,
                            parent_username=c.username,
                        )
                    )

            self._progress(page, 0)  # 总数未知，仅上报已翻页数
            self._log(f"评论第 {page} 页，累计 {len(comments)} 条")

            cursor = data.get("cursor") or {}
            if cursor.get("is_end"):
                break
            offset = (cursor.get("pagination_reply") or {}).get("next_offset", "")
            if not offset:
                break

        self._log(f"评论采集完成，共 {len(comments)} 条")
        return comments

    # ----- 内部方法 -----
    def _get_json_with_cooldown(
        self, url: str, params: dict, sign_wbi: bool, what: str
    ):
        """带「分级冷却续爬」的请求：遇到账号临时限流不立刻放弃，暂停后重试。

        参考成熟项目 BiliSpider 的风控应对：触发 -403/-412/-509 等业务风控码时，
        暂停一段时间再重试；每次冷却时间翻倍（默认 120s → 240s → 480s…），
        但单个冷却上限 600 秒（10 分钟）；连续冷却 ``throttle_max_pauses`` 次仍失败
        才放弃当前请求（返回 None）。

        冷却期间通过 :meth:`_sleep_with_heartbeat` 分片休眠，仍可响应暂停 / 取消。

        Args:
            url: 请求地址。
            params: 查询参数。
            sign_wbi: 是否 WBI 签名（一级评论需要，二级不需要）。
            what: 用于日志的请求描述（如 "评论第 3 页"）。

        Returns:
            dict | None: 成功返回响应 JSON；被限流耗尽或其它错误返回 None（调用方据此停止）。
        """
        http_cfg = getattr(self.http, "settings", None)
        http_cfg = getattr(http_cfg, "http", {}) if http_cfg else {}
        max_pauses = int(http_cfg.get("throttle_max_pauses", 5))
        pause_base = float(http_cfg.get("throttle_pause_base", 120.0))
        max_single_pause = 600.0

        attempt = 0
        while True:
            try:
                return self.http.get_json(url, params=params, sign_wbi=sign_wbi)
            except ThrottleError as exc:
                attempt += 1
                if attempt > max_pauses:
                    self._log(
                        f"{what} 连续 {max_pauses} 次冷却后仍被限流，已停止本次采集：{exc}"
                        "账号 cooldown 较长，建议暂停 1~2 小时后再试，期间不要反复请求。"
                    )
                    return None
                pause = min(pause_base * (2 ** (attempt - 1)), max_single_pause)
                self._log(
                    f"{what} 触发B站风控，暂停 {pause:.0f} 秒后重试"
                    f"（第 {attempt}/{max_pauses} 次冷却，期间请勿手动重试）"
                )
                self._sleep_with_heartbeat(pause)
            except Exception as exc:
                self._log(f"{what} 获取失败: {exc}")
                return None

    def _get_video_info(self, bvid: str | None = None, aid: int | None = None) -> dict:
        from ..utils.exceptions import APIError

        params = {"bvid": bvid} if bvid else {"aid": aid}
        resp = self.http.get_json(
            "https://api.bilibili.com/x/web-interface/view", params=params
        )
        data = resp.get("data")
        if not data:
            raise APIError("view 接口未返回视频数据，可能视频不存在或已下架")
        return data

    def _fetch_sub(
        self, root_rpid: int, aid: int, bvid: str, title: str,
        total_sub: int, page_no: int, parent_username: str,
    ) -> List[Comment]:
        """获取某条一级评论下的全部二级回复。"""
        subs: List[Comment] = []
        pn = 1
        while True:
            self._heartbeat()
            params = {
                "oid": aid,
                "type": 1,
                "root": root_rpid,
                "pn": pn,
                "ps": 10,
                "web_location": "333.788",
            }
            resp = self._get_json_with_cooldown(
                "https://api.bilibili.com/x/v2/reply/reply",
                params=params,
                sign_wbi=False,
                what=f"二级评论 root={root_rpid} 第 {pn} 页",
            )
            if resp is None:
                break
            data = resp.get("data") or {}
            replies = data.get("replies") or []
            if not replies:
                break
            for r in replies:
                subs.append(
                    self._parse_comment(
                        r, bvid=bvid, aid=aid, page_no=page_no, title=title,
                        root=root_rpid,
                        parent=r.get("parent", root_rpid),
                        parent_username=parent_username,
                    )
                )
            # 已采集数量达到接口声明的子回复数则停止
            if total_sub and len(subs) >= total_sub:
                break
            pn += 1
            if pn > 50:  # 安全上限，避免异常死循环
                break
        return subs

    @staticmethod
    def _parse_comment(
        r: dict, bvid: str, aid: int, page_no: int, title: str,
        root: int, parent: int, parent_username: str,
    ) -> Comment:
        """将接口返回的单个评论 JSON 转换为 :class:`Comment`。"""
        member = r.get("member") or {}
        vip = member.get("vip") or {}
        content = r.get("content") or {}
        rc = r.get("reply_control") or {}
        location = rc.get("location") or ""
        # location 形如 "IP属地：北京"，去除前缀
        ip_location = location[5:] if location.startswith("IP属地：") else location

        return Comment(
            rpid=r.get("rpid", 0),
            oid=aid,
            bvid=bvid,
            title=title,
            user_id=member.get("mid") or r.get("mid", 0),
            username=member.get("uname", ""),
            avatar=member.get("avatar", ""),
            level=(member.get("level_info") or {}).get("current_level", 0),
            content=content.get("message", ""),
            ctime=r.get("ctime", 0),
            like=r.get("like", 0),
            parent=r.get("parent", parent),
            root=root if root else r.get("rpid", 0),
            parent_username=parent_username,
            sex=member.get("sex", ""),
            vip=bool(vip.get("vipStatus")),
            ip_location=ip_location,
            sub_reply_count=r.get("rcount", r.get("sub_reply_count", 0)),
            page=page_no,
        )
