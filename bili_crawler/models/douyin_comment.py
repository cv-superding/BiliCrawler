"""抖音评论数据模型。

字段统一采用 snake_case 命名，覆盖评论内容、用户信息、点赞、发布时间、
父/根评论 ID（用于还原回复层级树）等。与 B站 :class:`Comment` 不同，
抖音使用 ``cid`` 作为评论 ID、``aweme_id`` 作为视频 ID、``sec_uid`` 标识用户。

``parent_id`` / ``root_id`` 共同描述评论树结构：
- 一级评论：``parent_id == 0``，``root_id == 自身 cid``
- 二级（及更深）回复：``parent_id`` 指向直接父评论，``root_id`` 指向根评论
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class DouyinComment:
    """单条抖音评论（可为一/二级评论）。"""

    comment_id: int = 0              # 评论 cid
    aweme_id: str = ""               # 视频 aweme_id
    title: str = ""                  # 视频标题
    user_id: int = 0                 # 用户 UID（明文）
    username: str = ""               # 昵称
    avatar: str = ""                 # 头像 URL
    content: str = ""                # 评论正文
    create_time: int = 0             # 发布时间戳（Unix 秒）
    digg_count: int = 0              # 点赞数
    reply_comment_total: int = 0     # 子回复数量
    parent_id: int = 0               # 父评论 cid（一级评论为 0）
    parent_username: str = ""         # 父评论用户名（二级回复用：回复目标）
    root_id: int = 0                 # 根评论 cid（用于还原回复树）
    ip_label: str = ""               # IP 属地
    user_level: int = 0              # 用户等级
    is_author: bool = False          # 是否视频作者本人
    vip: bool = False                # 是否认证（黄 V / 蓝 V）
    page: int = 1                    # 视频序号（批量采集时标记来源视频）

    def to_dict(self) -> dict:
        """转换为导出用的扁平字典（中文 key，与 B站 Comment 输出字段对齐）。"""
        create_time_iso = ""
        if self.create_time:
            try:
                create_time_iso = datetime.fromtimestamp(self.create_time).isoformat()
            except (ValueError, OSError):
                create_time_iso = ""

        # 评论类型：根评论 / 二级回复（抖音多为两级，其余按 parent 判断是否更深）
        comment_type = "根评论" if self.parent_id == 0 else "二级回复"
        # 回复目标：仅非根评论显示父评论用户名
        reply_target = "" if self.parent_id == 0 else self.parent_username

        return {
            "评论类型": comment_type,
            "回复目标": reply_target,
            "视频标题": self.title,
            "用户名": self.username,
            "用户ID": self.user_id,
            "用户等级": self.user_level,
            "评论内容": self.content,
            "点赞数": self.digg_count,
            "回复数": self.reply_comment_total,
            "发布时间": create_time_iso,
            "IP属地": self.ip_label,
            "视频ID": self.aweme_id,
            "评论ID": self.comment_id,
            "父评论ID": self.parent_id,
            "根评论ID": self.root_id,
        }
