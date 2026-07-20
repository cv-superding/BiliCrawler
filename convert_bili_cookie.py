"""
将浏览器导出的 B站 Cookie JSON 数组转换为 `name=value; ...` 字符串，
并写入 config.yaml 的 cookie.session 字段（覆盖原游客 Cookie）。

重要约定：
- 保持 value 原样（含 %2C/%3D 等 URL 编码），因为 SESSDATA 需要以编码形式上报。
- 不额外做 URL decode，避免把 SESSDATA 里的 %2C 解成逗号导致鉴权失败。
"""
import json
import re
import sys

COOKIE_JSON = "B站cookie.txt"
CONFIG = "config.yaml"


def build_cookie(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("Cookie 文件不是 JSON 数组格式")
    parts = []
    for c in data:
        name = c.get("name")
        value = c.get("value", "")
        if not name:
            continue
        parts.append(f"{name}={value}")
    return "; ".join(parts)


def patch_config(config_path, cookie_str):
    with open(config_path, "r", encoding="utf-8") as f:
        text = f.read()
    # 用单引号包裹（YAML 单引号内只有 ' 需转义为 ''），
    # 这样可安全容纳值里自带的双引号（如 bmg_af_sc={"none":...}）。
    escaped = cookie_str.replace("'", "''")
    yaml_scalar = f"'{escaped}'"
    # 匹配缩进后的 session: 行（允许引号包裹或裸值）
    pattern = re.compile(r'^(\s*)session:\s*.*$', re.MULTILINE)
    replacement = rf'\1session: {yaml_scalar}'
    new_text, n = pattern.subn(replacement, text)
    if n == 0:
        raise RuntimeError("在 config.yaml 中未找到 cookie.session 字段")
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(new_text)
    return n


def main():
    cookie = build_cookie(COOKIE_JSON)
    print(f"[convert] 共 {cookie.count('=') - cookie.count('%3D')} 个 cookie 项，长度 {len(cookie)}")
    # 预览前 80 字符
    print("[convert] 预览:", cookie[:80], "...")
    n = patch_config(CONFIG, cookie)
    print(f"[convert] 已更新 config.yaml 的 cookie.session（替换 {n} 处）")


if __name__ == "__main__":
    main()
