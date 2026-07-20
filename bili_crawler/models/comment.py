"""评论数据模型。

字段统一采用 snake_case 命名，覆盖评论内容、用户信息、点赞、时间、
父/根评论 ID（用于还原回复层级树）等。``parent`` / ``root`` 共同描述评论树结构：
- 一级评论：``parent == 0``，``root == 自身 rpid``
- 二级（及更深）回复：``parent`` 指向直接父评论，``root`` 指向根评论
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Comment:
    """单条评论记录（可为一/二级评论）。"""

    rpid: int = 0                           # 评论 ID
    oid: int = 0                            # 视频 aid（评论归属对象）
    bvid: str = ""                          # 视频 BV 号
    title: str = ""                         # 视频标题（导出时更直观）
    user_id: int = 0                        # 用户 UID（明文）
    username: str = ""                      # 用户名
    avatar: str = ""                        # 头像 URL
    level: int = 0                          # 用户等级
    content: str = ""                       # 评论正文
    ctime: int = 0                          # 发布时间戳（Unix 秒）
    like: int = 0                           # 点赞数
    parent: int = 0                         # 父评论 rpid（一级评论为 0）
    root: int = 0                           # 根评论 rpid（用于还原回复树）
    parent_username: str = ""                # 父评论用户名（二级回复用：回复目标）
    sex: str = ""                           # 性别
    vip: bool = False                       # 是否大会员
    ip_location: str = ""                   # IP 属地
    sub_reply_count: int = 0                # 子回复数量
    page: int = 1                           # 分 P 序号（多 P 视频）

    def to_dict(self) -> dict:
        """转换为导出用的扁平字典（含衍生字段：发布时间 ISO、评论类型、回复目标）。"""
        ctime_iso = ""
        if self.ctime:
            try:
                ctime_iso = datetime.fromtimestamp(self.ctime).isoformat()
            except (ValueError, OSError):
                ctime_iso = ""

        # 评论类型：根评论 / 二级回复 / 三级回复
        if self.parent == 0:
            comment_type = "根评论"
        elif self.parent == self.root:
            comment_type = "二级回复"
        else:
            comment_type = "三级回复"

        # 回复目标：仅非根评论显示父评论用户名
        reply_target = "" if self.parent == 0 else self.parent_username

        return {
            "评论类型": comment_type,
            "回复目标": reply_target,
            "视频标题": self.title,
            "用户名": self.username,
            "用户ID": self.user_id,
            "用户等级": self.level,
            "评论内容": self.content,
            "点赞数": self.like,
            "回复数": self.sub_reply_count,
            "发布时间": ctime_iso,
            "IP属地": self.ip_location,
            "视频ID": self.bvid,
            "评论ID": self.rpid,
            "父评论ID": self.parent,
            "根评论ID": self.root,
        }
