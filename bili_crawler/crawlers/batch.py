"""批量采集引擎。

支持四类批量来源：
- ``space``      UP 主空间：遍历该 UP 全部投稿视频
- ``favorites``  收藏夹：按 media_id 遍历收藏的视频
- ``collection`` 合集：按 (mid, sid) 遍历合集内视频
- ``channel``   频道/系列：按 (mid, cid) 遍历频道内视频

能力：并发采集（可配置并发数）、断点续爬（记录已采集视频 BV 号，中断后可续）、
统一复用 :class:`DanmakuCrawler` 与 :class:`CommentCrawler`。
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List

from ..models.danmaku import Danmaku
from ..models.comment import Comment
from ..utils.parse import (
    extract_aid,
    extract_bvid,
    extract_media_id,
    extract_mid,
    extract_sid_cid_sid,
)
from .base import BaseCrawler, CancelledError
from .comment import CommentCrawler
from .danmaku import DanmakuCrawler


class BatchCrawler(BaseCrawler):
    """按来源批量采集弹幕 / 评论。"""

    def crawl(
        self,
        source_input: str,
        source_type: str = "auto",
        kinds: tuple = ("danmaku", "comment"),
        concurrency: int = 3,
        resume: bool = True,
    ) -> Dict[str, list]:
        """批量采集入口。

        Args:
            source_input: UP 主主页 URL / 收藏夹链接 / 合集或频道链接，或数字 ID。
            source_type: 来源类型，"auto" 自动识别，或显式指定
                         space/favorites/collection/channel。
            kinds: 采集内容元组，含 "danmaku" 和/或 "comment"。
            concurrency: 并发视频数（>1 时多线程）。
            resume: 是否启用断点续爬。

        Returns:
            Dict[str, list]: {"danmaku": [...], "comment": [...]} 字典列表。
        """
        source = self._resolve_source(source_input, source_type)
        videos = self._list_videos(source)
        self.meta = {
            "title": f"批量采集（{source['type']}）· 共 {len(videos)} 个视频",
            "author": "",
            "platform": "bilibili",
        }
        if not videos:
            self._log("未从来源中解析出可采集视频，请检查链接或 Cookie 权限")
            return {"danmaku": [], "comment": []}

        state_key = self._state_key(source)
        done = self._load_state(state_key) if resume else set()
        todo = [v for v in videos if v["bvid"] not in done]
        self._log(
            f"来源解析出 {len(videos)} 个视频，已完成 {len(done)}，待采集 {len(todo)}"
        )
        self._progress(0, len(todo))

        collected: Dict[str, list] = {"danmaku": [], "comment": []}
        done_lock = threading.Lock()
        settings = self.http.settings

        def worker(video: dict) -> int:
            """单个视频的采集工作（独立 HTTPClient，避免多线程共享 Session）。"""
            from ..utils.http import HTTPClient

            http = HTTPClient(settings)
            local = {"danmaku": [], "comment": []}
            try:
                if "danmaku" in kinds:
                    dc = DanmakuCrawler(http, self.hooks)
                    local["danmaku"] = [d.to_dict() for d in dc.crawl(video["bvid"])]
                if "comment" in kinds:
                    cc = CommentCrawler(http, self.hooks)
                    local["comment"] = [c.to_dict() for c in cc.crawl(video["bvid"])]
            except CancelledError:
                raise
            except Exception as exc:  # 单视频失败不影响整体
                self._log(f"视频 {video['bvid']} 采集异常: {exc}")
            with done_lock:
                collected["danmaku"].extend(local["danmaku"])
                collected["comment"].extend(local["comment"])
                done.add(video["bvid"])
            self._save_state(state_key, done)
            return len(local["danmaku"]) + len(local["comment"])

        # 并发数归一化
        concurrency = max(1, int(concurrency or 1))
        if concurrency > 1 and len(todo) > 1:
            with ThreadPoolExecutor(max_workers=min(concurrency, len(todo))) as ex:
                futures = [ex.submit(worker, v) for v in todo]
                for fut in as_completed(futures):
                    self._heartbeat()
                    try:
                        fut.result()
                    except CancelledError:
                        ex.shutdown(wait=False, cancel_futures=True)
                        raise
                    except Exception:
                        pass
                    with done_lock:
                        done_count = len(done)
                    self._progress(done_count, len(todo))
        else:
            done_count = 0
            for v in todo:
                self._heartbeat()
                worker(v)
                done_count += 1
                self._progress(done_count, len(todo))

        self._log(
            f"批量采集完成：弹幕 {len(collected['danmaku'])} 条，"
            f"评论 {len(collected['comment'])} 条"
        )
        return collected

    # ----- 来源解析 -----
    def _resolve_source(self, source_input: str, source_type: str) -> dict:
        """将用户输入解析为结构化的来源描述。"""
        text = (source_input or "").strip()
        mid = extract_mid(text)
        media_id = extract_media_id(text)
        sid = extract_sid_cid_sid(text)
        lower = text.lower()

        if source_type == "auto":
            if "collectiondetail" in lower or ("sid=" in lower and "series" not in lower and "channel" not in lower):
                source_type = "collection" if "collection" in lower else "favorites"
            elif "seriesdetail" in lower or ("cid=" in lower):
                source_type = "channel"
            elif "fav" in lower or media_id:
                source_type = "favorites"
            elif mid:
                source_type = "space"
            else:
                # 纯数字：默认视为 UP 主 mid
                source_type = "space"
                if text.isdigit():
                    mid = int(text)

        if source_type == "favorites":
            if not media_id:
                raise ValueError("收藏夹来源需要 media_id（链接中含 fid= 或 media_id=）")
            return {"type": "favorites", "media_id": media_id}
        if source_type == "collection":
            if not (mid and sid):
                raise ValueError("合集来源需同时提供 UP mid 与 sid")
            return {"type": "collection", "mid": mid, "sid": sid}
        if source_type == "channel":
            if not (mid and sid):
                raise ValueError("频道来源需同时提供 UP mid 与 sid（或 cid）")
            return {"type": "channel", "mid": mid, "cid": sid}
        # space
        if not mid:
            if text.isdigit():
                mid = int(text)
            else:
                raise ValueError("UP 主空间来源需要数字 mid（如 space.bilibili.com/123456）")
        return {"type": "space", "mid": mid}

    # ----- 视频列表 -----
    def _list_videos(self, source: dict) -> List[dict]:
        """按来源类型列出待采集视频（BV 号 + 标题）。"""
        t = source["type"]
        if t == "space":
            return self._paginate(
                "https://api.bilibili.com/x/space/arc/search",
                {"mid": source["mid"], "ps": 30, "order": "pubdate", "web_location": "333.1007"},
            )
        if t == "favorites":
            return self._paginate(
                "https://api.bilibili.com/x/v3/fav/resource/list",
                {"media_id": source["media_id"], "ps": 20, "order": "mtime"},
            )
        if t == "collection":
            return self._paginate(
                "https://api.bilibili.com/x/space/collection/video",
                {"mid": source["mid"], "sid": source["sid"], "ps": 50},
            )
        if t == "channel":
            return self._paginate(
                "https://api.bilibili.com/x/space/channel/video",
                {"mid": source["mid"], "cid": source["cid"], "ps": 50},
            )
        return []

    def _paginate(self, url: str, base_params: dict) -> List[dict]:
        """通用分页采集：循环翻页直到本页无视频或达到安全上限。"""
        items: List[dict] = []
        pn = 1
        cap = 200  # 单来源最多翻 200 页，避免异常死循环
        while pn <= cap:
            self._heartbeat()
            params = {**base_params, "pn": pn}
            try:
                resp = self.http.get_json(url, params=params)
            except Exception as exc:
                self._log(f"视频列表第 {pn} 页获取失败: {exc}")
                break
            page_items = self._extract_items(resp)
            items.extend(page_items)
            if not page_items:
                break
            pn += 1
        return items

    @staticmethod
    def _extract_items(resp: dict) -> List[dict]:
        """从接口响应中稳健提取含 bvid 的项（兼容 vlist/archives/medias 等结构）。"""
        items: List[dict] = []
        data = (resp or {}).get("data") or {}
        for key in ("vlist", "archives", "medias"):
            lst = data.get(key)
            if isinstance(lst, list):
                for it in lst:
                    if not isinstance(it, dict):
                        continue
                    bv = it.get("bvid")
                    if bv and str(bv).startswith("BV"):
                        items.append({"bvid": str(bv), "title": it.get("title", "")})
                if items:
                    return items
        return items

    # ----- 断点续爬状态 -----
    def _state_key(self, source: dict) -> str:
        raw = json.dumps(source, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]

    def _state_path(self, key: str) -> str:
        state_dir = self.http.settings.export.get("state_dir", "data/state")
        os.makedirs(state_dir, exist_ok=True)
        return os.path.join(state_dir, f"{key}.json")

    def _load_state(self, key: str) -> set:
        path = self._state_path(key)
        if not os.path.isfile(path):
            return set()
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return set(json.load(fh))
        except (OSError, json.JSONDecodeError):
            return set()

    def _save_state(self, key: str, done: set) -> None:
        path = self._state_path(key)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(sorted(done), fh, ensure_ascii=False)
        except OSError as exc:
            self._log(f"断点状态保存失败: {exc}")
