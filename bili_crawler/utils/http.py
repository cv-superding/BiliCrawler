"""HTTP 客户端：封装会话管理、反爬策略与 WBI 签名。

对外暴露 ``request`` / ``get_json`` / ``get_bytes`` / ``get_text`` 四个方法。
内置能力：
- 随机 User-Agent 轮换
- 自适应限速（请求前随机休眠）
- HTTP 412/429/5xx 指数退避重试（最多 ``max_retries`` 次）
- 可选代理、可选登录 Cookie
- 对需要签名的接口调用 WBI 签名
"""

from __future__ import annotations

import json
from typing import Any

import requests

from .anti_crawl import RateLimiter, RetryPolicy, UserAgentPool
from .exceptions import APIError, NetworkError, ParseError, RateLimitError, ThrottleError
from .logger import get_logger
from .wbi import WbiSigner

logger = get_logger("http")


class HTTPClient:
    """统一的 HTTP 客户端，集成反爬与重试策略。"""

    def __init__(self, settings):
        """使用全局 :class:`Settings` 初始化客户端。

        Args:
            settings: 配置对象（含 http / user_agent / cookie 段）。
        """
        self.settings = settings
        http_cfg = settings.http
        ua_cfg = settings.user_agent
        cookie_cfg = settings.cookie

        self.timeout = float(http_cfg.get("timeout", 15))
        self.rate_limiter = RateLimiter(
            http_cfg.get("delay_min", 0.5), http_cfg.get("delay_max", 1.5)
        )
        self.ua_pool = UserAgentPool(
            ua_cfg.get("pool"), rotate=ua_cfg.get("rotate", True)
        )
        self.retry = RetryPolicy(
            http_cfg.get("max_retries", 3), http_cfg.get("backoff_base", 1.0)
        )
        self.wbi = WbiSigner(self)

        self.session = requests.Session()
        proxy = http_cfg.get("proxy")
        if proxy:
            self.session.proxies.update({"http": proxy, "https": proxy})
        cookie = (cookie_cfg.get("session") or "").strip()
        if cookie:
            self.session.headers["Cookie"] = cookie
        # 默认 Referer，规避部分接口的防盗链校验
        self.session.headers["Referer"] = "https://www.bilibili.com"

    # ----- 内部辅助 -----
    def _build_headers(self, extra: dict | None) -> dict:
        """构造请求头：注入随机 UA，合并调用方额外头。"""
        headers = {"User-Agent": self.ua_pool.random()}
        if extra:
            headers.update(extra)
        return headers

    # ----- 核心请求 -----
    def request(
        self,
        method: str,
        url: str,
        params: dict | None = None,
        data: Any = None,
        json_body: Any = None,
        headers: dict | None = None,
        sign_wbi: bool = False,
        raw: bool = False,
    ):
        """发起一次 HTTP 请求，内置重试 / 退避 / 限流处理。

        Args:
            method: GET / POST 等。
            url: 请求地址。
            params: 查询参数，若 ``sign_wbi`` 为 True 将被签名。
            data / json_body: 请求体（表单 / JSON）。
            headers: 额外请求头。
            sign_wbi: 是否对 params 进行 WBI 签名。
            raw: True 时返回原始 bytes，否则返回 ``requests.Response``。

        Returns:
            原始字节（raw=True）或 Response 对象。

        Raises:
            NetworkError: 网络层失败且重试耗尽。
            RateLimitError: 触发 412/429 且重试耗尽。
            APIError: 其他 4xx/5xx 或业务逻辑错误。
        """
        if sign_wbi and params is not None:
            params = self.wbi.sign(params)

        last_exc: Exception | None = None
        for attempt in range(self.retry.max_retries + 1):
            self.rate_limiter.wait()
            h = self._build_headers(headers)
            try:
                resp = self.session.request(
                    method,
                    url,
                    params=params,
                    data=data,
                    json=json_body,
                    headers=h,
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                last_exc = NetworkError(f"网络请求失败: {exc}")
                logger.warning("网络异常（第%d次）: %s", attempt + 1, exc)
                if attempt < self.retry.max_retries:
                    self.retry.sleep(attempt)
                    self.rate_limiter.adapt(True)
                    continue
                raise last_exc

            # ---- 状态码处理 ----
            if resp.status_code in (412, 429):
                self.rate_limiter.adapt(True)
                logger.warning("触发风控/限流 HTTP %d（第%d次）", resp.status_code, attempt + 1)
                if attempt < self.retry.max_retries:
                    self.retry.sleep(attempt)
                    continue
                raise RateLimitError(f"触发风控/限流，重试耗尽 (HTTP {resp.status_code})")
            if resp.status_code >= 500:
                logger.warning("服务端错误 HTTP %d（第%d次）", resp.status_code, attempt + 1)
                if attempt < self.retry.max_retries:
                    self.retry.sleep(attempt)
                    continue
                raise APIError(f"服务端错误，重试耗尽 (HTTP {resp.status_code})")
            if resp.status_code >= 400:
                raise APIError(f"客户端错误 HTTP {resp.status_code}: {resp.text[:200]}")
            # 成功：平稳回落限速
            self.rate_limiter.adapt(False)
            return resp.content if raw else resp

        # 理论不可达，保险兜底
        raise APIError(f"请求重试后仍失败: {last_exc}")

    # ----- 便捷方法 -----
    def get_json(self, url: str, params: dict | None = None, sign_wbi: bool = False) -> dict:
        """GET 并解析 JSON，校验 B站业务 code。"""
        resp = self.request("GET", url, params=params, sign_wbi=sign_wbi)
        try:
            payload = resp.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise ParseError(f"响应不是合法 JSON: {exc}") from exc
        # B站统一接口约定：code != 0 表示业务错误
        if isinstance(payload, dict) and payload.get("code", 0) not in (0, None):
            code = payload.get("code")
            msg = payload.get("message", "")
            # 业务级风控码：账号短时间请求过多导致的临时冷却，非 Cookie 失效
            if code in (-403, -412, -509):
                raise ThrottleError(
                    f"账号被 B站临时限流（业务码 {code}：{msg}）。"
                    f"多为短时间请求过于频繁触发的风控冷却，建议暂停 10~30 分钟后再试，"
                    f"期间不要反复请求；如急需可降低并发与请求频率。"
                )
            raise APIError(
                f"接口返回业务错误 code={code} message={msg}"
            )
        return payload

    def get_bytes(self, url: str, params: dict | None = None, sign_wbi: bool = False) -> bytes:
        """GET 并返回原始字节（用于 protobuf / 二进制）。"""
        return self.request("GET", url, params=params, sign_wbi=sign_wbi, raw=True)

    def get_text(self, url: str, params: dict | None = None, sign_wbi: bool = False) -> str:
        """GET 并返回文本。"""
        resp = self.request("GET", url, params=params, sign_wbi=sign_wbi)
        return resp.text
