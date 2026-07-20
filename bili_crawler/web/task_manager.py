"""任务管理器：Web 控制面板的核心运行时。

负责：
- 接收采集请求，创建 :class:`TaskInfo` 并在后台线程中执行采集；
- 通过回调钩子实时更新任务进度 / 日志 / 状态；
- 支持暂停 / 恢复 / 取消（基于线程事件）；
- 将采集结果落盘为原始 JSON，供导出页二次转换为 JSON/CSV；
- 任务元信息轻量持久化（重启后可继续在列表展示，未完成任务标记为取消）。
"""

from __future__ import annotations

import json
import os
import threading
import time

from ..config.settings import Settings
from ..crawlers.base import CancelledError, CrawlHooks
from ..crawlers.batch import BatchCrawler
from ..crawlers.comment import CommentCrawler
from ..crawlers.danmaku import DanmakuCrawler
from ..crawlers.douyin import DouyinBatchCrawler, DouyinCommentCrawler
from ..exporters.csv_exporter import CsvExporter
from ..exporters.json_exporter import JsonExporter
from ..models.task import TaskInfo, TaskKind, TaskStatus
from ..utils.logger import get_logger

logger = get_logger("task_manager")


class TaskManager:
    """采集任务的调度与状态中枢。"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.tasks: dict[str, TaskInfo] = {}
        self._events: dict[str, dict] = {}   # task_id -> {"pause":Event,"cancel":Event}
        self._lock = threading.Lock()
        # 任务元信息持久化文件（基于配置中的 state_dir，已在 settings 中锚定为绝对路径）
        state_dir = settings.export.get("state_dir", "data/state")
        os.makedirs(state_dir, exist_ok=True)
        self._persist_file = os.path.join(state_dir, "tasks.json")
        self._load_persisted()

    # ========== 任务提交 ==========
    def submit_video(self, bvid_or_url: str, kind: str, platform: str = "bilibili") -> TaskInfo:
        """提交单个视频的弹幕或评论采集任务。

        Args:
            bvid_or_url: BV 号 / 视频 URL / av 号（B站），或视频链接 / aweme_id（抖音）。
            kind: 采集类型（danmaku / comment）。
            platform: 平台（bilibili / douyin）。
        """
        if kind not in (TaskKind.DANMAKU.value, TaskKind.COMMENT.value):
            raise ValueError(f"非法任务类型: {kind}")
        if platform == "douyin" and kind == TaskKind.DANMAKU.value:
            raise ValueError("抖音视频不支持弹幕采集（仅支持评论）")
        platform_label = "抖音" if platform == "douyin" else "B站"
        name = f"{platform_label}{'弹幕' if kind == 'danmaku' else '评论'}采集 · {bvid_or_url}"
        task = TaskInfo(
            name=name, kind=kind, platform=platform,
            params={"input": bvid_or_url},
        )
        self._register(task)
        t = threading.Thread(
            target=self._run_single, args=(task, bvid_or_url, kind, platform), daemon=True
        )
        t.start()
        return task

    def submit_batch(
        self,
        source: str,
        source_type: str = "auto",
        kinds: tuple = ("danmaku", "comment"),
        concurrency: int = 3,
        platform: str = "bilibili",
    ) -> TaskInfo:
        """提交批量采集任务（B站：UP主/收藏夹/合集/频道；抖音：用户主页）。"""
        platform_label = "抖音" if platform == "douyin" else "B站"
        name = f"{platform_label}批量采集 · {source[:40]}"
        task = TaskInfo(
            name=name,
            kind=TaskKind.BATCH.value,
            platform=platform,
            params={
                "source": source,
                "source_type": source_type,
                "kinds": list(kinds),
                "concurrency": concurrency,
            },
        )
        self._register(task)
        t = threading.Thread(
            target=self._run_batch,
            args=(task, source, source_type, kinds, concurrency, platform),
            daemon=True,
        )
        t.start()
        return task

    # ========== 任务控制 ==========
    def pause(self, task_id: str) -> bool:
        ev = self._events.get(task_id)
        if not ev:
            return False
        ev["pause"].set()
        with self._lock:
            if self.tasks[task_id].status == TaskStatus.RUNNING.value:
                self.tasks[task_id].status = TaskStatus.PAUSED.value
        self._persist()
        return True

    def resume(self, task_id: str) -> bool:
        ev = self._events.get(task_id)
        if not ev:
            return False
        ev["pause"].clear()
        with self._lock:
            if self.tasks[task_id].status == TaskStatus.PAUSED.value:
                self.tasks[task_id].status = TaskStatus.RUNNING.value
        self._persist()
        return True

    def cancel(self, task_id: str) -> bool:
        ev = self._events.get(task_id)
        if not ev:
            return False
        # 先解除暂停，使线程能执行到 should_stop 检查点
        ev["pause"].clear()
        ev["cancel"].set()
        return True

    def delete_task(self, task_id: str, purge_files: bool = False) -> bool:
        """删除任务。

        Args:
            task_id: 任务 ID。
            purge_files: True 时同时删除该任务的原始数据文件与已导出的文件；
                         False 时仅移除任务记录（保留磁盘真实数据，供后续需要）。

        Returns:
            是否成功删除（任务存在并已被移除）。
        """
        with self._lock:
            task = self.tasks.get(task_id)
            if task is None:
                return False
            # 若仍在运行，先发取消信号让后台线程退出
            ev = self._events.get(task_id)
            if ev:
                ev["pause"].clear()
                ev["cancel"].set()

            files_to_delete: list = []
            if purge_files:
                rp = task.result_path or self._raw_path(task_id)
                if rp and os.path.isfile(rp):
                    files_to_delete.append(rp)
                out_dir = self.settings.export.get("output_dir", "data/exports")
                if os.path.isdir(out_dir):
                    for fn in os.listdir(out_dir):
                        if fn.startswith(task_id):
                            files_to_delete.append(os.path.join(out_dir, fn))

            self.tasks.pop(task_id, None)
            self._events.pop(task_id, None)

        # 锁外删除文件，避免阻塞其它任务
        for p in files_to_delete:
            try:
                os.remove(p)
            except OSError:
                pass

        self._persist()
        return True

    # ========== 查询 ==========
    def list_tasks(self) -> list[dict]:
        with self._lock:
            return [t.to_dict() for t in self.tasks.values()]

    def get_task(self, task_id: str) -> dict | None:
        with self._lock:
            t = self.tasks.get(task_id)
            return t.to_dict() if t else None

    def get_raw(self, task_id: str):
        """读取任务原始结果（落盘 JSON）。"""
        path = self._raw_path(task_id)
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError):
            return None

    # ========== 导出 ==========
    def _load_raw(self, task_id: str):
        """读取任务原始结果。

        优先使用任务记录的 ``result_path``（兼容不同工作目录下保存的历史文件），
        其次回退到按当前规则计算的 ``_raw_path``。两者皆不存在返回 ``None``。
        """
        task = self.get_task(task_id)
        candidates = []
        if task and task.get("result_path"):
            candidates.append(task["result_path"])
        candidates.append(self._raw_path(task_id))
        for p in candidates:
            if p and os.path.isfile(p):
                try:
                    with open(p, "r", encoding="utf-8") as fh:
                        return json.load(fh)
                except (OSError, json.JSONDecodeError):
                    continue
        return None

    def export(self, task_id: str, fmt: str, sub: str | None = None) -> str:
        """将任务结果导出为 JSON/CSV，返回生成文件的绝对路径。"""
        raw = self._load_raw(task_id)
        if raw is None:
            raise FileNotFoundError(
                "未找到该任务的原始数据，可能尚未完成、已清理，或原始文件被移动"
            )

        # 定位待导出记录
        kind = raw.get("kind")
        if kind == TaskKind.BATCH.value:
            sub = sub or "danmaku"
            records = raw.get(sub, [])
        else:
            records = raw.get("records", [])

        if fmt not in ("json", "csv"):
            raise ValueError("导出格式仅支持 json / csv")
        exporter = JsonExporter() if fmt == "json" else CsvExporter()
        # 弹幕走专用表头，其余（评论/抖音评论）走评论表头；
        # 批量任务按 sub（danmaku/comment）区分，单任务按 kind 区分。
        if kind == TaskKind.BATCH.value:
            export_kind = sub or "danmaku"
        else:
            export_kind = kind if kind in (TaskKind.DANMAKU.value, "danmaku") else "comment"

        out_dir = self.settings.export.get("output_dir", "data/exports")
        os.makedirs(out_dir, exist_ok=True)
        prefix = f"{task_id}_{sub or kind}"
        path = os.path.join(out_dir, prefix)
        return exporter.export(records, path, kind=export_kind)

    # ========== 内部执行 ==========
    def _register(self, task: TaskInfo) -> None:
        with self._lock:
            self.tasks[task.task_id] = task
        self._events[task.task_id] = {"pause": threading.Event(), "cancel": threading.Event()}
        self._persist()

    def _make_hooks(self, task: TaskInfo) -> CrawlHooks:
        ev = self._events[task.task_id]

        def on_progress(cur: int, tot: int) -> None:
            with self._lock:
                task.progress_current = cur
                task.progress_total = tot

        def on_log(msg: str) -> None:
            with self._lock:
                task.logs.append(msg)
                if len(task.logs) > 500:
                    task.logs = task.logs[-500:]

        def should_stop() -> bool:
            return ev["cancel"].is_set()

        def on_pause() -> None:
            # 暂停事件置位时阻塞，直到恢复
            while ev["pause"].is_set():
                time.sleep(0.2)

        return CrawlHooks(on_progress, on_log, should_stop, on_pause)

    def _finish(self, task: TaskInfo, status: str, error: str = "") -> None:
        with self._lock:
            task.status = status
            task.error = error
            task.finished_at = time.strftime("%Y-%m-%d %H:%M:%S")
        self._persist()

    def _run_single(self, task: TaskInfo, bvid_or_url: str, kind: str, platform: str = "bilibili") -> None:
        from ..utils.http import HTTPClient

        http = HTTPClient(self.settings)
        hooks = self._make_hooks(task)
        with self._lock:
            task.status = TaskStatus.RUNNING.value
        try:
            if platform == "douyin":
                crawler = DouyinCommentCrawler(http, hooks)
                records = [c.to_dict() for c in crawler.crawl(bvid_or_url)]
            elif kind == TaskKind.DANMAKU.value:
                crawler = DanmakuCrawler(http, hooks)
                records = [d.to_dict() for d in crawler.crawl(bvid_or_url)]
            else:
                crawler = CommentCrawler(http, hooks)
                records = [c.to_dict() for c in crawler.crawl(bvid_or_url)]
            meta = getattr(crawler, "meta", {})
            with self._lock:
                task.meta = meta
            self._save_raw(task.task_id, {"kind": kind, "records": records, "meta": meta})
            self._finish(task, TaskStatus.COMPLETED.value)
        except CancelledError:
            self._finish(task, TaskStatus.CANCELLED.value)
        except Exception as exc:  # 采集失败，记录原因
            logger.exception("任务 %s 失败", task.task_id)
            self._finish(task, TaskStatus.FAILED.value, str(exc))

    def _run_batch(self, task: TaskInfo, source, source_type, kinds, concurrency, platform="bilibili") -> None:
        from ..utils.http import HTTPClient

        http = HTTPClient(self.settings)
        hooks = self._make_hooks(task)
        with self._lock:
            task.status = TaskStatus.RUNNING.value
        try:
            if platform == "douyin":
                crawler = DouyinBatchCrawler(http, hooks)
            else:
                crawler = BatchCrawler(http, hooks)
            result = crawler.crawl(source, source_type, kinds, concurrency)
            meta = getattr(crawler, "meta", {})
            with self._lock:
                task.meta = meta
            self._save_raw(task.task_id, {
                "kind": TaskKind.BATCH.value,
                "danmaku": result.get("danmaku", []),
                "comment": result.get("comment", []),
                "meta": meta,
            })
            self._finish(task, TaskStatus.COMPLETED.value)
        except CancelledError:
            self._finish(task, TaskStatus.CANCELLED.value)
        except Exception as exc:
            logger.exception("批量任务 %s 失败", task.task_id)
            self._finish(task, TaskStatus.FAILED.value, str(exc))

    # ========== 落盘 ==========
    def _raw_path(self, task_id: str) -> str:
        raw_dir = self.settings.export.get("raw_dir", "data/results")
        os.makedirs(raw_dir, exist_ok=True)
        return os.path.join(raw_dir, f"{task_id}.json")

    def _save_raw(self, task_id: str, data: dict) -> None:
        path = self._raw_path(task_id)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        with self._lock:
            if task_id in self.tasks:
                self.tasks[task_id].result_path = path

    # ========== 元信息持久化 ==========
    def _persist(self) -> None:
        try:
            with self._lock:
                snapshot = [t.to_dict() for t in self.tasks.values()]
            with open(self._persist_file, "w", encoding="utf-8") as fh:
                json.dump(snapshot, fh, ensure_ascii=False)
        except OSError:
            pass

    def _load_persisted(self) -> None:
        if not os.path.isfile(self._persist_file):
            return
        try:
            with open(self._persist_file, "r", encoding="utf-8") as fh:
                snapshot = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return
        for d in snapshot:
            t = TaskInfo(**{k: v for k, v in d.items() if k in TaskInfo.__dataclass_fields__})
            # 重启后未完成的任务：running/paused 视为已取消（线程已随进程死亡）
            if t.status in (TaskStatus.RUNNING.value, TaskStatus.PAUSED.value):
                t.status = TaskStatus.CANCELLED.value
            self.tasks[t.task_id] = t
            self._events[t.task_id] = {"pause": threading.Event(), "cancel": threading.Event()}
            # 重启后仍处于 pending 的任务：其后台线程已随旧进程死亡，
            # 若不重新派发就会永远「待处理」卡死。这里自动恢复派发。
            if t.status == TaskStatus.PENDING.value:
                self._redispatch(t)

    def _redispatch(self, task: TaskInfo) -> None:
        """重启后重新派发遗留的 pending 任务（其原后台线程已随旧进程死亡）。

        仅会在 ``_load_persisted`` 中对「从磁盘读回的历史 pending 任务」调用，
        当前进程通过 ``submit_*`` 提交的任务自带线程，不会被重复派发。
        """
        platform = task.platform or "bilibili"
        kind = task.kind
        params = task.params or {}
        try:
            if kind == TaskKind.BATCH.value:
                t = threading.Thread(
                    target=self._run_batch,
                    args=(
                        task,
                        params.get("source", ""),
                        params.get("source_type", "auto"),
                        tuple(params.get("kinds", ("danmaku", "comment"))),
                        params.get("concurrency", 3),
                        platform,
                    ),
                    daemon=True,
                )
            else:
                t = threading.Thread(
                    target=self._run_single,
                    args=(task, params.get("input", ""), kind, platform),
                    daemon=True,
                )
            t.start()
            logger.info("重启恢复派发任务 %s (%s/%s)", task.task_id, platform, kind)
        except Exception as exc:
            logger.exception("重启恢复任务 %s 失败", task.task_id)
            self._finish(task, TaskStatus.FAILED.value, str(exc))
