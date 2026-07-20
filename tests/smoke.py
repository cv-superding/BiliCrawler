"""离线冒烟测试：验证 protobuf 解析、URL 解析、导出器与包整体导入。

无需联网即可运行：``python tests/smoke.py``
"""

from __future__ import annotations

import io
import os
import sys
import tempfile

# 将项目根目录加入路径，便于直接 import bili_crawler
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

FAIL = []


def check(name: str, cond: bool, extra: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    if not cond:
        FAIL.append(name)
    print(f"[{status}] {name} {extra}")


# ---------- 1. protobuf 编解码自洽 ----------
def enc_varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            break
    return bytes(out)


def enc_tag(field: int, wt: int) -> bytes:
    return enc_varint((field << 3) | wt)


def enc_str(field: int, s: str) -> bytes:
    b = s.encode("utf-8")
    return enc_tag(field, 2) + enc_varint(len(b)) + b


def enc_var(field: int, n: int) -> bytes:
    return enc_tag(field, 0) + enc_varint(n)


def enc_elem(e: dict) -> bytes:
    parts = [
        enc_var(1, e["id"]),
        enc_var(2, e["progress"]),
        enc_var(3, e["mode"]),
        enc_var(4, e["fontsize"]),
        enc_var(5, e["color"]),
        enc_str(6, e["midHash"]),
        enc_str(7, e["content"]),
        enc_var(8, e["ctime"]),
        enc_var(11, e["pool"]),
        enc_str(12, e["idStr"]),
    ]
    return b"".join(parts)


def enc_root(elems: list) -> bytes:
    body = b"".join(enc_tag(1, 2) + enc_varint(len(e)) + e for e in elems)
    return body


def test_protobuf():
    from bili_crawler.utils.protobuf import parse_danmaku_protobuf

    elems = [
        enc_elem({"id": 101, "progress": 1234, "mode": 1, "fontsize": 25,
                  "color": 16777215, "midHash": "abc123", "content": "你好世界",
                  "ctime": 1609459200, "pool": 0, "idStr": "101"}),
        enc_elem({"id": 102, "progress": 5678, "mode": 5, "fontsize": 25,
                  "color": 0, "midHash": "def456", "content": "顶部弹幕",
                  "ctime": 1609459300, "pool": 1, "idStr": "102"}),
    ]
    blob = enc_root(elems)
    result = parse_danmaku_protobuf(blob, bvid="BVtest", cid=999, page=1)
    check("protobuf 解析出 2 条弹幕", len(result) == 2, f"got {len(result)}")
    r0 = result[0]
    check("protobuf 字段 id", r0["id"] == 101, repr(r0["id"]))
    check("protobuf 字段 content", r0["content"] == "你好世界", repr(r0["content"]))
    check("protobuf 字段 mode", r0["mode"] == 1)
    check("protobuf 字段 color", r0["color"] == 16777215)
    check("protobuf 字段 progress", r0["progress"] == 1234)
    check("protobuf 字段 send_time", r0["send_time"] == 1609459200)
    check("protobuf 字段 uid_hash", r0["uid_hash"] == "abc123")
    check("protobuf 字段 id_str", r0["id_str"] == "101")
    check("protobuf 字段 pool", r0["pool"] == 0)
    check("protobuf 回填 bvid", r0["bvid"] == "BVtest")


# ---------- 2. URL / ID 解析 ----------
def test_parse():
    from bili_crawler.utils.parse import (
        extract_aid, extract_bvid, extract_media_id, extract_mid, extract_sid_cid_sid,
    )
    check("extract_bvid BV", extract_bvid("https://www.bilibili.com/video/BV1xx411c7mD?t=10") == "BV1xx411c7mD")
    check("extract_bvid 纯号", extract_bvid("BV1xx411c7mD") == "BV1xx411c7mD")
    check("extract_aid", extract_aid("https://www.bilibili.com/video/av170001") == 170001)
    check("extract_mid", extract_mid("https://space.bilibili.com/123456") == 123456)
    check("extract_media_id", extract_media_id("https://space.bilibili.com/1/favlist?fid=777") == 777)
    check("extract_sid", extract_sid_cid_sid("https://space.bilibili.com/1/channel/collectiondetail?sid=888") == 888)


# ---------- 3. 模型 to_dict ----------
def test_models():
    from bili_crawler.models.comment import Comment
    from bili_crawler.models.danmaku import Danmaku

    d = Danmaku(id=1, content="x", send_time=1609459200, mode=1, color=16711680)
    dd = d.to_dict()
    check("danmaku to_dict color_hex", dd["color_hex"] == "#FF0000", dd["color_hex"])
    check("danmaku to_dict mode_name", dd["mode_name"] == "滚动")

    c = Comment(rpid=5, user_id=99, username="张三", content="赞", ctime=1609459200, parent=0, root=5)
    cd = c.to_dict()
    check("comment to_dict 发布时间 非空", bool(cd["发布时间"]), cd["发布时间"])
    check("comment to_dict 父/根评论ID", cd["父评论ID"] == 0 and cd["根评论ID"] == 5)


# ---------- 4. 导出器（BOM + 中文） ----------
def test_exporters():
    from bili_crawler.exporters.csv_exporter import CsvExporter
    from bili_crawler.exporters.json_exporter import JsonExporter

    records = [
        {"评论内容": "中文测试", "用户名": "张三", "点赞数": 10},
        {"评论内容": "emoji😀", "用户名": "李四", "点赞数": 2},
    ]
    with tempfile.TemporaryDirectory() as td:
        jp = os.path.join(td, "out.json")
        JsonExporter().export(records, jp)
        with open(jp, "rb") as fh:
            raw = fh.read()
        check("JSON 写入 UTF-8 BOM", raw[:3] == b"\xef\xbb\xbf")
        check("JSON 中文不乱码", "中文测试" in raw.decode("utf-8"))

        cp = os.path.join(td, "out.csv")
        CsvExporter().export(records, cp)
        with open(cp, "rb") as fh:
            craw = fh.read()
        check("CSV 写入 UTF-8 BOM(utf-8-sig)", craw[:3] == b"\xef\xbb\xbf")
        check("CSV 中文不乱码", "中文测试" in craw.decode("utf-8"))


# ---------- 5. 包整体导入 ----------
def test_imports():
    try:
        import bili_crawler  # noqa: F401
        check("import bili_crawler", True)
    except Exception as exc:  # pragma: no cover
        check("import bili_crawler", False, repr(exc))
    try:
        from bili_crawler.web.app import create_app  # noqa: F401
        check("import web.app (Flask)", True)
    except Exception as exc:
        check("import web.app (Flask)", False, f"可能需要安装 flask: {exc}")


if __name__ == "__main__":
    test_protobuf()
    test_parse()
    test_models()
    test_exporters()
    test_imports()
    print("\n" + ("=" * 40))
    if FAIL:
        print(f"失败项：{FAIL}")
        sys.exit(1)
    print("全部冒烟测试通过 ✅")
