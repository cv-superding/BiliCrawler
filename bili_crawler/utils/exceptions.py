"""自定义异常体系，便于在采集层与 Web 层做精细化错误处理。"""

from __future__ import annotations


class BiliCrawlerError(Exception):
    """所有本工具异常的基类。"""


class NetworkError(BiliCrawlerError):
    """网络层异常：连接失败、超时、DNS 解析失败等。"""


class RateLimitError(BiliCrawlerError):
    """触发平台风控 / 限流（HTTP 412 / 429）且重试耗尽。"""


class ThrottleError(RateLimitError):
    """B站业务级风控 / 限流（业务 code=-403/-412/-509 等）。

    通常为账号短时间请求过多触发的**临时冷却**，过一段时间会自动解除，
    并非 Cookie 失效或代码错误。
    """


class APIError(BiliCrawlerError):
    """B站接口返回非预期状态码或业务 code 异常。"""


class ParseError(BiliCrawlerError):
    """响应数据解析失败（protobuf / JSON / XML）。"""


class ConfigError(BiliCrawlerError):
    """配置缺失或格式错误。"""
