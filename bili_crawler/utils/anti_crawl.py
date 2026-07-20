"""反爬策略基础组件。

包含三块可复用能力：
- :class:`RateLimiter`   请求频率自适应限速（被限流时自动放宽延迟区间）
- :class:`UserAgentPool` 随机 User-Agent 池轮换
- :class:`RetryPolicy`   指数退避重试策略（配合 HTTP 412/429 使用）
"""

from __future__ import annotations

import random
import threading
import time

# 内置默认 User-Agent 池（覆盖主流桌面 / 移动浏览器，低版本号以避免被识别为爬虫）
DEFAULT_UA_POOL: list[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
]


class RateLimiter:
    """请求频率自适应限速器。

    每次请求前调用 :meth:`wait` 在 ``[min_delay, max_delay]`` 区间内随机休眠。
    当检测到被限流时调用 :meth:`adapt` 放宽区间；平稳时缓慢回落，避免长期过慢。
    """

    def __init__(self, min_delay: float = 0.5, max_delay: float = 1.5):
        self.min_delay = float(min_delay)
        self.max_delay = float(max_delay)
        self._lock = threading.Lock()

    def wait(self) -> None:
        """按当前区间随机休眠，模拟人工浏览节奏。"""
        with self._lock:
            lo, hi = self.min_delay, self.max_delay
        # 区间可能在另一线程被放大，确保 lo <= hi
        if lo > hi:
            lo, hi = hi, lo
        time.sleep(random.uniform(lo, hi))

    def adapt(self, hit_limit: bool) -> None:
        """根据是否触发限流动态调整延迟区间。

        Args:
            hit_limit: True 表示刚被限流，应拉长延迟；False 表示请求顺利，缓慢回落。
        """
        with self._lock:
            if hit_limit:
                self.min_delay = min(self.min_delay * 1.5, 5.0)
                self.max_delay = min(self.max_delay * 1.5, 10.0)
            else:
                self.min_delay = max(self.min_delay * 0.95, 0.3)
                self.max_delay = max(self.max_delay * 0.95, 0.6)


class UserAgentPool:
    """User-Agent 池，支持顺序轮换或随机取值。"""

    def __init__(self, custom_pool: list[str] | None = None, rotate: bool = True):
        self.rotate = rotate
        self.pool = list(custom_pool) if custom_pool else list(DEFAULT_UA_POOL)
        if not self.pool:
            self.pool = list(DEFAULT_UA_POOL)
        self._idx = 0
        self._lock = threading.Lock()

    def next(self) -> str:
        """返回下一个 UA（顺序轮换）；未开启轮换则固定返回首个。"""
        with self._lock:
            if not self.rotate or len(self.pool) == 1:
                return self.pool[0]
            ua = self.pool[self._idx % len(self.pool)]
            self._idx += 1
        return ua

    def random(self) -> str:
        """从池中随机返回一个 UA。"""
        return random.choice(self.pool)


class RetryPolicy:
    """指数退避重试策略。第 n 次重试休眠 ≈ base * 2^n + 抖动。"""

    def __init__(self, max_retries: int = 3, backoff_base: float = 1.0):
        self.max_retries = int(max_retries)
        self.backoff_base = float(backoff_base)

    def sleep(self, attempt: int) -> None:
        """在指定重试次数处休眠。

        Args:
            attempt: 当前已发生的重试次数（从 0 开始）。
        """
        delay = self.backoff_base * (2 ** attempt) + random.uniform(0, 0.5)
        time.sleep(delay)
