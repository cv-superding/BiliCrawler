"""弹幕数据模型。

字段统一采用 snake_case 命名，并附带来源接口含义说明。
注意：B站弹幕接口出于隐私保护只返回 ``mid_hash``（用户 ID 的哈希），
不提供明文 UID；如需明文 UID 请使用评论接口（见 :mod:`bili_crawler.models.comment`）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

# 弹幕模式（mode）含义映射
MODE_MAP = {
    1: "滚动",
    4: "底部",
    5: "顶部",
    6: "逆向滚动",
    7: "高级",
    8: "代码弹幕",
    9: "BAS弹幕",
    10: "特殊定位",
}


@dataclass
class Danmaku:
    """单条弹幕记录。"""

    id: int | str | None = None           # 弹幕唯一 ID
    id_str: str = ""                       # 弹幕 ID 字符串形式
    content: str = ""                      # 弹幕文本
    send_time: int = 0                     # 发送时间戳（Unix 秒）
    uid_hash: str = ""                     # 用户 ID 哈希（midHash，非明文 UID）
    mode: int = 1                          # 弹幕类型（1滚动/4底部/5顶部…）
    color: int = 0                         # 颜色（十进制 RGB）
    fontsize: int = 25                     # 字体大小
    progress: int = 0                      # 在视频中出现的时间点（毫秒）
    pool: int = 0                          # 弹幕池（0普通/1字幕/2特殊）
    weight: int = 0                        # 权重（用于防挡优先级）
    action: str = ""                       # 动作（通常为空）
    bvid: str = ""                         # 所属视频 BV 号
    cid: int = 0                           # 所属分 P 的 cid
    page: int = 1                          # 分 P 序号

    def to_dict(self) -> dict:
        """转换为导出用的扁平字典（含衍生字段：时间 ISO、颜色 hex、类型名）。"""
        color_hex = f"#{self.color:06X}" if isinstance(self.color, int) else ""
        send_iso = ""
        if self.send_time:
            try:
                send_iso = datetime.fromtimestamp(self.send_time).isoformat()
            except (ValueError, OSError):
                send_iso = ""
        return {
            "id": self.id,
            "id_str": self.id_str,
            "content": self.content,
            "send_time": self.send_time,
            "send_time_iso": send_iso,
            "uid_hash": self.uid_hash,
            "mode": self.mode,
            "mode_name": MODE_MAP.get(self.mode, "未知"),
            "color": self.color,
            "color_hex": color_hex,
            "fontsize": self.fontsize,
            "progress_ms": self.progress,
            "progress_sec": round(self.progress / 1000, 2) if self.progress else 0,
            "pool": self.pool,
            "weight": self.weight,
            "action": self.action,
            "bvid": self.bvid,
            "cid": self.cid,
            "page": self.page,
        }
