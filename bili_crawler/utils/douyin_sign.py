"""抖音请求签名工具。

抖音 Web 接口需在查询参数中携带签名（早期 ``X-Bogus``，新版 ``a_bogus``），
否则服务端拒绝返回数据。本模块提供：

- ``XBogus``：移植自 Evil0ctal/Douyin_TikTok_Download_API（Apache-2.0），
  纯 Python 实现，**无任何第三方依赖**，离线即可验证。
- ``gen_a_bogus``：因 ``a_bogus`` 由 JSVMP 虚拟机（bdms SDK）生成，纯 Python
  实现成本高且易随版本失效；本函数提供钩子，可通过 Node.js 调用用户自备的
  签名脚本来生成（详见 README「抖音平台」章节）。
- ``sign_douyin_url``：一站式签名入口，向完整 URL 追加 ``X-Bogus``（及可选的
  ``a_bogus``），返回可直接请求的签名 URL。

⚠️ 关键约束：签名所用的 User-Agent 必须与真正发送请求时的 UA **完全一致**，
否则服务端校验失败。本模块导出 ``DEFAULT_UA`` 作为约定 UA，采集器会同时用于
签名与请求。
"""

from __future__ import annotations

import os
import subprocess
import urllib.parse

# 默认用于抖音签名 / 请求的 User-Agent（必须与发送请求时的 UA 一致）
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0"
)


# ==============================================================================
# X-Bogus 实现（移植自 Evil0ctal/Douyin_TikTok_Download_API，Apache-2.0）
# Contributor: https://github.com/Evil0ctal  https://github.com/Johnserf-Seed
# ==============================================================================
class XBogus:
    """抖音 / TikTok Web 接口 X-Bogus 签名生成器（纯 Python）。"""

    def __init__(self, user_agent: str = None) -> None:
        # fmt: off
        self.Array = [
            None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None,
            None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None,
            None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None,
            0, 1, 2, 3, 4, 5, 6, 7, 8, 9, None, None, None, None, None, None, None, None, None, None, None,
            None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None,
            None, None, None, None, None, None, None, None, None, None, None, None, 10, 11, 12, 13, 14, 15
        ]
        self.character = "Dkdpgh4ZKsQB80/Mfvw36XI1R25-WUAlEi7NLboqYTOPuzmFjJnryx9HVGcaStCe="
        # fmt: on
        self.ua_key = b"\x00\x01\x0c"
        self.user_agent = (
            user_agent
            if user_agent is not None and user_agent != ""
            else DEFAULT_UA
        )

    def md5_str_to_array(self, md5_str):
        """将字符串使用 md5 哈希算法转换为整数数组。"""
        if isinstance(md5_str, str) and len(md5_str) > 32:
            return [ord(char) for char in md5_str]
        array = []
        idx = 0
        while idx < len(md5_str):
            array.append(
                (self.Array[ord(md5_str[idx])] << 4) | self.Array[ord(md5_str[idx + 1])]
            )
            idx += 2
        return array

    def md5_encrypt(self, url_path):
        """使用多轮 md5 哈希算法对 URL 路径进行加密。"""
        hashed = self.md5_str_to_array(
            self.md5(self.md5_str_to_array(self.md5(url_path)))
        )
        return hashed

    def md5(self, input_data):
        """计算输入数据的 md5 哈希值（输入可为 str 或 int 数组）。"""
        import hashlib

        if isinstance(input_data, str):
            array = self.md5_str_to_array(input_data)
        elif isinstance(input_data, list):
            array = input_data
        else:
            raise ValueError("Invalid input type. Expected str or list.")
        md5_hash = hashlib.md5()
        md5_hash.update(bytes(array))
        return md5_hash.hexdigest()

    def encoding_conversion(
        self, a, b, c, e, d, t, f, r, n, o, i, _, x, u, s, l, v, h, p
    ):
        """第一次编码转换。"""
        y = [a]
        y.append(int(i))
        y.extend([b, _, c, x, e, u, d, s, t, l, f, v, r, h, n, p, o])
        return bytes(y).decode("ISO-8859-1")

    def encoding_conversion2(self, a, b, c):
        """第二次编码转换。"""
        return chr(a) + chr(b) + c

    def rc4_encrypt(self, key, data):
        """使用 RC4 算法对数据进行加密。"""
        if isinstance(key, str):
            key = key.encode("ISO-8859-1")
        s = list(range(256))
        j = 0
        encrypted = bytearray()
        for i in range(256):
            j = (j + s[i] + key[i % len(key)]) % 256
            s[i], s[j] = s[j], s[i]
        i = j = 0
        for byte in data:
            i = (i + 1) % 256
            j = (j + s[i]) % 256
            s[i], s[j] = s[j], s[i]
            encrypted.append(byte ^ s[(s[i] + s[j]) % 256])
        return encrypted

    def calculation(self, a1, a2, a3):
        """按字节三元组计算自定义 Base64 输出。"""
        x1 = (a1 & 255) << 16
        x2 = (a2 & 255) << 8
        x3 = x1 | x2 | a3
        return (
            self.character[(x3 & 16515072) >> 18]
            + self.character[(x3 & 258048) >> 12]
            + self.character[(x3 & 4032) >> 6]
            + self.character[x3 & 63]
        )

    def getXBogus(self, url_path):
        """获取 X-Bogus 值。

        Args:
            url_path: 完整请求 URL（含 path + query，但不含 X-Bogus/a_bogus 参数）。

        Returns:
            tuple: (带 X-Bogus 的完整参数串, X-Bogus 值, 使用的 UA)。
        """
        import base64
        import time

        array1 = self.md5_str_to_array(
            self.md5(
                base64.b64encode(
                    self.rc4_encrypt(self.ua_key, self.user_agent.encode("ISO-8859-1"))
                ).decode("ISO-8859-1")
            )
        )
        array2 = self.md5_str_to_array(
            self.md5(self.md5_str_to_array("d41d8cd98f00b204e9800998ecf8427e"))
        )
        url_path_array = self.md5_encrypt(url_path)

        timer = int(time.time())
        ct = 536919696
        # fmt: off
        new_array = [
            64, 0.00390625, 1, 12,
            url_path_array[14], url_path_array[15], array2[14], array2[15], array1[14], array1[15],
            timer >> 24 & 255, timer >> 16 & 255, timer >> 8 & 255, timer & 255,
            ct >> 24 & 255, ct >> 16 & 255, ct >> 8 & 255, ct & 255
        ]
        # fmt: on
        xor_result = new_array[0]
        for i in range(1, len(new_array)):
            b = new_array[i]
            if isinstance(b, float):
                b = int(b)
            xor_result ^= b

        new_array.append(xor_result)

        idx = 0
        array3 = []
        array4 = []
        while idx < len(new_array):
            array3.append(new_array[idx])
            try:
                array4.append(new_array[idx + 1])
            except IndexError:
                pass
            idx += 2

        merge_array = array3 + array4

        garbled_code = self.encoding_conversion2(
            2,
            255,
            self.rc4_encrypt(
                "ÿ".encode("ISO-8859-1"),
                self.encoding_conversion(*merge_array).encode("ISO-8859-1"),
            ).decode("ISO-8859-1"),
        )

        xb_ = ""
        idx = 0
        while idx < len(garbled_code):
            xb_ += self.calculation(
                ord(garbled_code[idx]),
                ord(garbled_code[idx + 1]),
                ord(garbled_code[idx + 2]),
            )
            idx += 3
        return (f"{url_path}&X-Bogus={xb_}", xb_, self.user_agent)


# ==============================================================================
# 对外签名 API
# ==============================================================================
def gen_x_bogus(url_path: str, user_agent: str) -> str:
    """对完整 URL（含 path+query，不含签名参数）生成 X-Bogus 值。"""
    return XBogus(user_agent=user_agent).getXBogus(url_path)[1]


def gen_a_bogus(query: str, user_agent: str, worker: str | None = None) -> str | None:
    """调用 Node.js 签名脚本生成 a_bogus（可选，需用户自备 worker）。

    Args:
        query: 待签名的查询字符串（不含 a_bogus）。
        user_agent: User-Agent。
        worker: worker 脚本路径；默认 ``js/douyin_sign_worker.js``。

    Returns:
        a_bogus 字符串；若未配置 / 不可用则返回 None（调用方退化为仅 X-Bogus）。
    """
    if not worker:
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        worker = os.path.join(root, "js", "douyin_sign_worker.js")
    if not worker or not os.path.isfile(worker):
        return None
    try:
        out = subprocess.run(
            ["node", worker, query, user_agent],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if out.returncode != 0:
            return None
        return out.stdout.strip() or None
    except Exception:
        return None


def sign_douyin_url(
    url: str,
    user_agent: str,
    with_a_bogus: bool = False,
    worker: str | None = None,
) -> str:
    """对完整 URL 追加签名参数，返回可直接请求的签名 URL。

    Args:
        url: 完整请求 URL（含 path + query，但不含 X-Bogus/a_bogus）。
        user_agent: 与发送请求一致的 UA。
        with_a_bogus: 是否额外追加 a_bogus（需自备 Node worker）。
        worker: a_bogus worker 脚本路径。

    Returns:
        str: 追加签名后的 URL。
    """
    xb = gen_x_bogus(url, user_agent)
    signed = f"{url}&X-Bogus={xb}"
    if with_a_bogus:
        ab = gen_a_bogus(urllib.parse.urlparse(url).query, user_agent, worker)
        if ab:
            signed = f"{signed}&a_bogus={ab}"
    return signed
