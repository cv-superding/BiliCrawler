"""采集器基类与回调钩子。

设计目标：将「采集逻辑」与「运行环境（Web / CLI）」解耦。采集器只通过
:class:`CrawlHooks` 与外部环境通信——上报进度、打日志、判断是否暂停/取消，
因此同一套采集器既可在 Web 任务队列中多线程运行，也可在命令行中直接调用。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

# 取消信号：采集器检测到后抛出，由运行环境捕获为 CANCELLED 状态
class CancelledError(Exception):
    """任务被取消时由采集器抛出。"""


@dataclass
class CrawlHooks:
    """采集器与外部运行环境之间的回调钩子（均可为空操作）。"""

    on_progress: Callable[[int, int], None] = lambda cur, tot: None   # 进度上报
    on_log: Callable[[str], None] = lambda msg: None                 # 日志
    should_stop: Callable[[], bool] = lambda: False                  # 是否应取消
    on_pause: Callable[[], None] = lambda: None                      # 阻塞直至恢复


class BaseCrawler:
    """所有采集器的基类，提供钩子封装与通用方法。"""

    def __init__(self, http, hooks: Optional[CrawlHooks] = None):
        """
        Args:
            http: :class:`~bili_crawler.utils.http.HTTPClient` 实例。
            hooks: 回调钩子，缺省为空操作。
        """
        self.http = http
        self.hooks = hooks or CrawlHooks()

    # ----- 钩子封装 -----
    def _log(self, msg: str) -> None:
        try:
            self.hooks.on_log(msg)
        except Exception:
            pass

    def _progress(self, current: int, total: int) -> None:
        try:
            self.hooks.on_progress(current, total)
        except Exception:
            pass

    def _check_stop(self) -> None:
        """检测取消信号，若被取消则抛出 :class:`CancelledError`。"""
        if self.hooks.should_stop and self.hooks.should_stop():
            raise CancelledError("任务已被取消")

    def _check_pause(self) -> None:
        """若外部处于暂停态，阻塞直到恢复。"""
        if self.hooks.on_pause:
            self.hooks.on_pause()

    def _heartbeat(self) -> None:
        """单次循环的统一检查点：先暂停后取消。"""
        self._check_pause()
        self._check_stop()

    def _sleep_with_heartbeat(self, seconds: float, step: float = 2.0) -> None:
        """可中断的休眠：分片睡眠，期间持续响应暂停 / 取消信号。

        用于风控冷却等较长的等待，避免长时间阻塞导致任务无法被取消。

        Args:
            seconds: 需要休眠的总秒数。
            step: 每片的最大秒数（越小对取消越灵敏）。
        """
        remaining = float(seconds)
        while remaining > 0:
            self._heartbeat()  # 期间仍响应暂停 / 取消
            chunk = step if remaining > step else remaining
            time.sleep(chunk)
            remaining -= chunk
