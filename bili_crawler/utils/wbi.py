"""WBI 签名工具。

B站自 2023 年起对部分接口（如 ``x/v2/reply/wbi/main``）启用 WBI 签名校验：
需在请求参数中附加 ``wts``（时间戳）与 ``w_rid``（参数 + mixin_key 的 MD5）。
本模块负责获取 img_key / sub_key 并生成签名。
"""

from __future__ import annotations

import hashlib
import time
import urllib.parse

from .exceptions import APIError

# WBI mixin_key 固定的 64 位置换表（来自 bilibili-API-collect 逆向结论）
_MIXIN_KEY_ENC_TABLE = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 57, 56, 11, 51,
    20, 21, 54, 36, 22, 52, 30, 44, 59, 6, 60, 34, 4, 25, 62, 63, 32,
]


class WbiSigner:
    """WBI 签名器：按需从 nav 接口获取密钥并缓存，对请求参数进行签名。"""

    def __init__(self, http_client):
        # 延迟循环引用：HTTPClient 在初始化时注入自身
        self._http = http_client
        self._img_key: str | None = None
        self._sub_key: str | None = None
        self._lock = __import__("threading").Lock()

    def _ensure_keys(self) -> None:
        """确保已获取 img_key / sub_key，未获取则请求 nav 接口。"""
        if self._img_key and self._sub_key:
            return
        with self._lock:
            # 双重检查，避免并发重复请求
            if self._img_key and self._sub_key:
                return
            resp = self._http.get_json(
                "https://api.bilibili.com/x/web-interface/nav"
            )
            data = (resp or {}).get("data") or {}
            wbi_img = data.get("wbi_img") or {}
            img_url = wbi_img.get("img_url") or ""
            sub_url = wbi_img.get("sub_url") or ""
            if not img_url or not sub_url:
                raise APIError(
                    "无法获取 WBI 签名密钥，请检查网络连通性或配置有效的 Cookie"
                )
            self._img_key = img_url.rsplit("/", 1)[-1].split(".", 1)[0]
            self._sub_key = sub_url.rsplit("/", 1)[-1].split(".", 1)[0]

    @staticmethod
    def _mixin_key(orig: str) -> str:
        """根据 64 位置换表从 img_key+sub_key 生成 32 位 mixin_key。"""
        return "".join(orig[i] for i in _MIXIN_KEY_ENC_TABLE)[:32]

    def sign(self, params: dict) -> dict:
        """对请求参数字典进行 WBI 签名，原地返回带 ``wts`` / ``w_rid`` 的新字典。

        Args:
            params: 原始查询参数字典（不含 wts / w_rid）。

        Returns:
            dict: 已附加签名的参数字典（按 key 升序排列）。
        """
        self._ensure_keys()
        orig = self._img_key + self._sub_key
        mixin_key = self._mixin_key(orig)
        # 附加时间戳并按 key 升序排序（WBI 要求）
        params = dict(sorted({**params, "wts": int(time.time())}.items()))
        query = urllib.parse.urlencode(params)
        params["w_rid"] = hashlib.md5((query + mixin_key).encode("utf-8")).hexdigest()
        return params
