"""弹幕采集器。

通过 B站弹幕接口获取视频全部弹幕：
1. 先用 ``x/web-interface/view`` 获取视频 cid 与每分 P 时长（弹幕接口需要 cid 而非 BV）；
2. 按 B站固定分段时长（约 360 秒/段）用 ``ceil(时长/360)`` 推算段数，
   逐段请求 ``x/v2/dm/web/seg.so`` 返回 protobuf 二进制，由
   :mod:`bili_crawler.utils.protobuf` 解析；
3. 时长未知时退化为增量抓取（逐段直到连续空段）；
4. 旧视频 / 分段无数据时兜底走 ``x/v1/dm/list.so``（XML）。

注：``x/v2/dm/web/view`` 现返回 protobuf（非 JSON），不再用于取段数，
故段数改为基于视频时长推算，更稳定且无需解析该 protobuf。
"""

from __future__ import annotations

from typing import List

from ..models.danmaku import Danmaku
from ..utils.exceptions import APIError
from ..utils.parse import extract_aid, extract_bvid
from ..utils.protobuf import parse_danmaku_blob
from .base import BaseCrawler


class DanmakuCrawler(BaseCrawler):
    """按 BV 号 / URL / av 号采集视频弹幕。"""

    def crawl(
        self,
        bvid_or_url: str,
        pages: str | int = "all",
    ) -> List[Danmaku]:
        """采集单个视频的全部弹幕。

        Args:
            bvid_or_url: BV 号、完整视频 URL 或 av 号。
            pages: 采集范围，"all" 全部分 P；整数表示指定分 P（1 起）。

        Returns:
            List[Danmaku]: 弹幕对象列表。
        """
        bvid = extract_bvid(bvid_or_url)
        aid = extract_aid(bvid_or_url)
        if not bvid and not aid:
            raise ValueError(f"无法从输入中解析出 BV 号或 av 号: {bvid_or_url!r}")

        info = self._get_video_info(bvid=bvid, aid=aid)
        bvid = info.get("bvid") or bvid
        cids = self._select_cids(info, pages)
        title = info.get("title", "")
        author = (info.get("owner") or {}).get("name", "")
        self.meta = {"title": title, "author": author, "platform": "bilibili"}

        self._log(f"视频《{info.get('title', bvid)}》共 {len(cids)} 个分P，开始采集弹幕")
        all_danmaku: List[Danmaku] = []
        total = len(cids)
        for i, (cid, page_no, duration) in enumerate(cids, 1):
            self._heartbeat()
            try:
                items = self._fetch_by_cid(cid, bvid, page_no, duration)
            except Exception as exc:  # 单分 P 失败不中断整体
                self._log(f"分P{page_no} 弹幕采集失败: {exc}")
                items = []
            all_danmaku.extend(Danmaku(**it) for it in items)
            self._progress(i, total)
            self._log(f"分P{page_no} 弹幕 {len(items)} 条（累计 {len(all_danmaku)}）")
        self._log(f"弹幕采集完成，共 {len(all_danmaku)} 条")
        return all_danmaku

    # ----- 内部方法 -----
    def _get_video_info(self, bvid: str | None = None, aid: int | None = None) -> dict:
        """调用 view 接口获取视频元数据（含 aid 与各分 P 的 cid）。"""
        params = {"bvid": bvid} if bvid else {"aid": aid}
        resp = self.http.get_json(
            "https://api.bilibili.com/x/web-interface/view", params=params
        )
        data = resp.get("data")
        if not data:
            raise APIError("view 接口未返回视频数据，可能视频不存在或已下架")
        return data

    def _select_cids(self, info: dict, pages: str | int) -> List[tuple]:
        """从 view 数据中提取需要采集的 (cid, 分P序号, 时长秒) 列表。"""
        pages_list = info.get("pages") or []
        if pages_list:
            # 单页时长取该分 P 的 duration 字段（多页视频每页独立计时）
            candidates = [
                (p["cid"], p.get("page", 1), int(p.get("duration") or 0))
                for p in pages_list
            ]
        else:
            candidates = [(info.get("cid"), 1, int(info.get("duration") or 0))]

        if pages == "all":
            return candidates
        try:
            idx = int(pages)
            return [candidates[idx - 1]] if 1 <= idx <= len(candidates) else []
        except (ValueError, IndexError):
            self._log(f"指定的分P {pages!r} 无效，回退为全部分P")
            return candidates

    @staticmethod
    def _seg_count(duration: int) -> int:
        """根据视频时长推算弹幕段数。

        B站弹幕按固定时长分段（约 360 秒/段），故段数 = ceil(时长 / 360)。
        额外 +1 作为边界兜底（部分视频末段会多出一个编号）。

        Args:
            duration: 分 P 时长（秒），<=0 表示未知（交由增量抓取处理）。

        Returns:
            int: 段数；0 表示时长未知，调用方应走增量抓取。
        """
        if duration and duration > 0:
            return max(1, (duration + 359) // 360) + 1
        return 0

    def _fetch_by_cid(
        self, cid: int, bvid: str, page_no: int, duration: int = 0
    ) -> List[dict]:
        """按 cid 拉取该分 P 全部弹幕（分段请求 + 兜底 list.so）。

        Args:
            cid: 分 P 的 cid。
            bvid: 视频 BV 号（回填用）。
            page_no: 分 P 序号。
            duration: 分 P 时长（秒），用于推算段数；为 0 时走增量抓取。
        """
        seg_count = self._seg_count(duration)
        if seg_count > 0:
            return self._fetch_segments(cid, bvid, page_no, seg_count)
        # 时长未知：增量抓取直到连续空段
        self._log("分P%s 时长未知，采用增量抓取弹幕" % page_no)
        return self._fetch_incremental(cid, bvid, page_no)

    def _fetch_segments(
        self, cid: int, bvid: str, page_no: int, seg_count: int
    ) -> List[dict]:
        """按已知段数逐段请求 seg.so。"""
        result: List[dict] = []
        for idx in range(1, seg_count + 1):
            self._heartbeat()
            try:
                data = self.http.get_bytes(
                    "https://api.bilibili.com/x/v2/dm/web/seg.so",
                    params={"type": 1, "oid": cid, "segment_index": idx},
                )
                result.extend(parse_danmaku_blob(data, bvid, cid, page_no))
            except Exception as exc:
                self._log(f"分片 {idx}/{seg_count} 获取失败: {exc}")
        # 若分段接口无数据（老视频或需登录），尝试 list.so 兜底
        if not result:
            self._log("分段接口无数据，尝试 list.so 兜底")
            try:
                data = self.http.get_bytes(
                    "https://api.bilibili.com/x/v1/dm/list.so", params={"oid": cid}
                )
                result.extend(parse_danmaku_blob(data, bvid, cid, page_no))
            except Exception as exc:
                self._log(f"list.so 兜底也失败: {exc}")
        return result

    def _fetch_incremental(
        self, cid: int, bvid: str, page_no: int, max_seg: int = 500
    ) -> List[dict]:
        """时长未知时的兜底：逐段请求，直到连续若干段为空。"""
        result: List[dict] = []
        consecutive_empty = 0
        for idx in range(1, max_seg + 1):
            self._heartbeat()
            try:
                data = self.http.get_bytes(
                    "https://api.bilibili.com/x/v2/dm/web/seg.so",
                    params={"type": 1, "oid": cid, "segment_index": idx},
                )
                parsed = parse_danmaku_blob(data, bvid, cid, page_no)
            except Exception as exc:
                self._log(f"分片 {idx} 获取失败: {exc}")
                parsed = []
            if parsed:
                result.extend(parsed)
                consecutive_empty = 0
            else:
                consecutive_empty += 1
                if consecutive_empty >= 3:  # 连续 3 段为空，认为已到末尾
                    break
        if not result:
            self._log("分段接口无数据，尝试 list.so 兜底")
            try:
                data = self.http.get_bytes(
                    "https://api.bilibili.com/x/v1/dm/list.so", params={"oid": cid}
                )
                result.extend(parse_danmaku_blob(data, bvid, cid, page_no))
            except Exception as exc:
                self._log(f"list.so 兜底也失败: {exc}")
        return result
