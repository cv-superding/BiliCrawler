"""任务模型：描述一次采集任务的生命周期与状态。

任务状态机：``pending -> running <-> paused -> running -> completed/failed/cancelled``。
本模型仅承载可序列化状态；线程控制事件（暂停/取消）由 Web 层的
:class:`bili_crawler.web.task_manager.TaskManager` 在运行时另行维护。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum


class TaskStatus(str, Enum):
    """采集任务状态码。"""

    PENDING = "pending"        # 排队中，尚未开始
    RUNNING = "running"        # 采集中
    PAUSED = "paused"          # 已暂停
    CANCELLED = "cancelled"    # 已取消
    COMPLETED = "completed"    # 已完成
    FAILED = "failed"          # 失败


class TaskKind(str, Enum):
    """采集任务类型。"""

    DANMAKU = "danmaku"        # 弹幕
    COMMENT = "comment"        # 评论
    BATCH = "batch"            # 批量（UP主/收藏夹/合集/频道）


@dataclass
class TaskInfo:
    """一次采集任务的完整描述（可 JSON 序列化）。"""

    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = ""                     # 任务展示名
    kind: str = ""                     # 任务类型（danmaku/comment/batch）
    platform: str = "bilibili"         # 采集平台（bilibili / douyin）
    params: dict = field(default_factory=dict)  # 采集参数
    status: str = TaskStatus.PENDING.value
    progress_current: int = 0          # 当前进度（已处理单元数）
    progress_total: int = 0            # 总单元数（未知时为 0）
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))
    finished_at: str = ""              # 结束时间
    result_path: str = ""              # 原始数据落盘路径（供导出页读取）
    error: str = ""                    # 失败原因
    logs: list = field(default_factory=list)  # 最近日志（环形截断）
    meta: dict = field(default_factory=dict)  # 任务级元信息：{title, author, platform}

    def to_dict(self) -> dict:
        """转换为 API 响应的字典。"""
        return {
            "task_id": self.task_id,
            "name": self.name,
            "kind": self.kind,
            "platform": self.platform,
            "params": self.params,
            "status": self.status,
            "progress_current": self.progress_current,
            "progress_total": self.progress_total,
            "progress_pct": (
                round(self.progress_current / self.progress_total * 100, 1)
                if self.progress_total else 0.0
            ),
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "result_path": self.result_path,
            "error": self.error,
            "logs": self.logs[-50:],   # 仅返回最近 50 条日志
            "meta": self.meta,         # 任务级元信息（视频标题 / 博主名）
        }
