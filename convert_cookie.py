#!/usr/bin/env python3
"""把浏览器插件导出的抖音 Cookie JSON 转成 Cookie 头字符串，并写入 config.yaml。"""
import json
import re
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "抖音cookie.txt"
CFG = ROOT / "config.yaml"


def load_cookies(path: Path) -> str:
    raw = json.loads(path.read_text(encoding="utf-8"))
    parts = []
    for c in raw:
        name = (c.get("name") or "").strip()
        if not name:
            continue  # 跳过空 name（导出里偶有脏数据）
        value = c.get("value") or ""
        # URL 解码：导出里大量 %7C / %22 等是浏览器实际发送前的编码形态
        name = urllib.parse.unquote(name)
        value = urllib.parse.unquote(value)
        parts.append(f"{name}={value}")
    return "; ".join(parts)


def yaml_quote(s: str) -> str:
    """转成 YAML 单引号安全字符串（反斜杠/双引号均按字面量，仅 ' 需转义为 ''）。"""
    s = s.replace("'", "''")
    return f"'{s}'"


def main():
    cookie = load_cookies(SRC)
    if not cookie:
        raise SystemExit("未解析到任何 Cookie")

    # 校验关键字段是否解码正确
    for key in ("sessionid", "ttwid", "odin_tt", "sid_tt"):
        hit = next((p for p in cookie.split("; ") if p.startswith(key + "=")), None)
        print(f"  {key:10s}: {'OK ' + hit[:48] if hit else 'MISSING'}")

    text = CFG.read_text(encoding="utf-8")
    if re.search(r'^\s*douyin:\s*".*"\s*$', text, re.M):
        text = re.sub(r'^\s*douyin:\s*".*"\s*$', f'  douyin: {yaml_quote(cookie)}', text, flags=re.M)
    else:
        # 兜底：没匹配到就直接追加
        text = text.rstrip() + f'\n  douyin: {yaml_quote(cookie)}\n'
    CFG.write_text(text, encoding="utf-8")
    print(f"\n已写入 config.yaml，Cookie 长度 = {len(cookie)} 字符")


if __name__ == "__main__":
    main()
