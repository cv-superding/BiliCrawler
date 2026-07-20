"""Protobuf 解析工具（针对 B站弹幕二进制格式，零第三方依赖）。

B站弹幕接口（``x/v2/dm/web/seg.so`` 等）返回的是 ``DmSegMobileReply`` 的 protobuf 编码，
结构为 ``repeated DanmakuElem elems = 1;``。本模块手写了一个精简的 protobuf 解码器，
无需 ``protoc`` 编译即可解析，便于跨平台部署。
"""

from __future__ import annotations

from typing import Any

from .exceptions import ParseError

# DanmakuElem 字段含义（field number -> 含义）
# 1:id 2:progress(ms) 3:mode 4:fontsize 5:color 6:midHash 7:content
# 8:ctime 9:weight 10:action 11:pool 12:idStr


def _read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    """从字节流读取一个 varint，返回 (值, 新位置)。"""
    result = 0
    shift = 0
    while True:
        if pos >= len(buf):
            raise ParseError("protobuf 解析越界：varint 未结束")
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
    return result, pos


def parse_protobuf(data: bytes) -> dict[int, Any]:
    """解析一个 protobuf 消息为 ``{field_number: value}``。

    - varint(0)/64bit(1)/32bit(5) 字段解析为 int
    - length-delimited(2) 字段保留为原始 bytes（由调用方按需二次解析）

    Args:
        data: protobuf 编码的字节串。

    Returns:
        dict: 字段号到值的映射；repeated 字段的值为列表。

    Raises:
        ParseError: 数据格式非法或越界。
    """
    fields: dict[int, Any] = {}
    pos = 0
    n = len(data)
    while pos < n:
        tag, pos = _read_varint(data, pos)
        field_num = tag >> 3
        wire_type = tag & 0x07
        if wire_type == 0:  # varint
            val, pos = _read_varint(data, pos)
        elif wire_type == 1:  # 64-bit
            if pos + 8 > n:
                raise ParseError("protobuf 解析越界：64bit 字段")
            val = int.from_bytes(data[pos:pos + 8], "little")
            pos += 8
        elif wire_type == 2:  # length-delimited
            length, pos = _read_varint(data, pos)
            if pos + length > n:
                raise ParseError("protobuf 解析越界：length-delimited 字段")
            val = data[pos:pos + length]
            pos += length
        elif wire_type == 5:  # 32-bit
            if pos + 4 > n:
                raise ParseError("protobuf 解析越界：32bit 字段")
            val = int.from_bytes(data[pos:pos + 4], "little")
            pos += 4
        else:
            raise ParseError(f"不支持的 protobuf wire type: {wire_type}")

        if field_num in fields:
            if not isinstance(fields[field_num], list):
                fields[field_num] = [fields[field_num]]
            fields[field_num].append(val)
        else:
            fields[field_num] = val
    return fields


def _to_str(raw: bytes | None) -> str:
    """将 protobuf 字符串字段（bytes 或已被 url/decode 的 str）转为 str。"""
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace")


def parse_danmaku_protobuf(
    data: bytes, bvid: str = "", cid: int = 0, page: int = 1
) -> list[dict]:
    """解析一段弹幕 protobuf 二进制（``DmSegMobileReply``）为弹幕字典列表。

    Args:
        data: seg.so 返回的二进制内容。
        bvid: 所属视频 BV 号（仅用于回填到结果，便于溯源）。
        cid: 所属分 P 的 cid。
        page: 分 P 序号。

    Returns:
        list[dict]: 每条弹幕的标准化字典，字段含 id/content/send_time/uid_hash/
                    mode/color/fontsize/progress 等。
    """
    root = parse_protobuf(data)
    elems_raw = root.get(1, [])
    if isinstance(elems_raw, bytes):
        elems_raw = [elems_raw]
    elif not isinstance(elems_raw, list):
        elems_raw = [elems_raw]

    results: list[dict] = []
    for raw in elems_raw:
        # 每个 elem 自身是 length-delimited(bytes)，二次解析
        if not isinstance(raw, bytes):
            continue
        try:
            elem = parse_protobuf(raw)
        except ParseError:
            continue
        results.append({
            "id": elem.get(1),
            "id_str": _to_str(elem.get(12)),
            "content": _to_str(elem.get(7)),
            "send_time": elem.get(8),
            "uid_hash": _to_str(elem.get(6)),
            "mode": elem.get(3),
            "color": elem.get(5),
            "fontsize": elem.get(4),
            "progress": elem.get(2),
            "pool": elem.get(11),
            "weight": elem.get(9),
            "action": _to_str(elem.get(10)),
            "bvid": bvid,
            "cid": cid,
            "page": page,
        })
    return results


def parse_danmaku_xml(
    data: bytes, bvid: str = "", cid: int = 0, page: int = 1
) -> list[dict]:
    """解析旧版 XML 弹幕（``<d p="...">文本</d>``），作为 protobuf 的兜底。

    p 属性顺序：出现时间,模式,字体大小,颜色,发送时间戳,弹幕池,用户hash,弹幕ID
    """
    import re
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ParseError(f"XML 弹幕解析失败: {exc}") from exc

    results: list[dict] = []
    for node in root.iter("d"):
        p = node.get("p", "")
        parts = p.split(",")
        if len(parts) < 8:
            continue
        try:
            appear, mode, fontsize, color, ctime, pool, uid_hash, dm_id = parts[:8]
            results.append({
                "id": int(dm_id) if dm_id.isdigit() else dm_id,
                "id_str": str(dm_id),
                "content": (node.text or "").strip(),
                "send_time": int(float(ctime)),
                "uid_hash": uid_hash,
                "mode": int(float(mode)),
                "color": int(color),
                "fontsize": int(float(fontsize)),
                "progress": int(float(appear) * 1000),
                "pool": int(float(pool)),
                "weight": 0,
                "action": "",
                "bvid": bvid,
                "cid": cid,
                "page": page,
            })
        except (ValueError, IndexError):
            continue
    return results


def parse_danmaku_blob(
    data: bytes, bvid: str = "", cid: int = 0, page: int = 1
) -> list[dict]:
    """自动识别弹幕二进制格式（protobuf 或 XML）并解析。

    Args:
        data: 弹幕接口返回的二进制内容。

    Returns:
        list[dict]: 标准化弹幕字典列表。
    """
    head = data[:5].lstrip(b"\xef\xbb\xbf").lower()  # 去除 BOM 后判断
    if head.startswith(b"<?xml") or head.startswith(b"<i>"):
        return parse_danmaku_xml(data, bvid, cid, page)
    try:
        return parse_danmaku_protobuf(data, bvid, cid, page)
    except ParseError:
        # protobuf 失败则退化为 XML 尝试
        return parse_danmaku_xml(data, bvid, cid, page)
