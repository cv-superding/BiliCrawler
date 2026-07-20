"""CSV 导出器：使用 ``utf-8-sig`` 编码（UTF-8 + BOM），Excel 双击即正确显示中文。"""

from __future__ import annotations

import csv
from typing import List

from .base import BaseExporter


# 评论 CSV 标准表头（全中文），与 B站/抖音模型 to_dict 输出的中文 key 对齐
_COMMENT_FIELDNAMES = [
    "序号",
    "评论类型",      # 根评论 / 二级回复 / 三级回复
    "回复目标",      # 二级回复的父评论用户名
    "视频标题",
    "用户名",
    "用户ID",
    "用户等级",
    "评论内容",
    "点赞数",
    "回复数",
    "发布时间",
    "IP属地",
    "视频ID",       # B站 BV 号 / 抖音 aweme_id
    "评论ID",
    "父评论ID",
    "根评论ID",
]

# 弹幕 CSV 表头（全中文）。弹幕模型 to_dict 输出为英文 key，
# 这里用「中文表头 -> 源 key」映射在导出时转换，使弹幕也能输出成可读的中文表格。
_DANMAKU_FIELDNAMES = [
    "序号",
    "弹幕内容",
    "出现时间(秒)",   # progress_sec
    "发送时间",       # send_time_iso
    "弹幕模式",       # mode_name
    "颜色",          # color_hex
    "字号",          # fontsize
    "用户ID哈希",     # uid_hash
    "视频ID",        # bvid
    "分P",           # page
    "弹幕ID",        # id_str
]
_DANMAKU_KEYMAP = {
    "弹幕内容": "content",
    "出现时间(秒)": "progress_sec",
    "发送时间": "send_time_iso",
    "弹幕模式": "mode_name",
    "颜色": "color_hex",
    "字号": "fontsize",
    "用户ID哈希": "uid_hash",
    "视频ID": "bvid",
    "分P": "page",
    "弹幕ID": "id_str",
}


class CsvExporter(BaseExporter):
    """将记录导出为 Excel 兼容的 UTF-8-BOM CSV 文件。"""

    ext = "csv"

    def export(self, records: List[dict], path: str, kind: str = "comment") -> str:
        """写入 CSV。列头按采集类型选择，缺少的 key 留空，并自动添加序号。

        Args:
            records: 字典列表。
            path: 目标路径（自动补 .csv）。
            kind: 采集类型，"danmaku" 用弹幕表头，其余（comment/douyin_comment）用评论表头。

        Returns:
            str: 实际文件路径。
        """
        path = self._with_ext(path, self.ext)
        self._ensure_dir(path)

        if kind == "danmaku":
            fieldnames = list(_DANMAKU_FIELDNAMES)
            def build_row(r, i):
                row = {"序号": i}
                for zh, src in _DANMAKU_KEYMAP.items():
                    row[zh] = r.get(src, "")
                return row
        else:
            fieldnames = list(_COMMENT_FIELDNAMES)
            def build_row(r, i):
                row = dict(r)
                row["序号"] = i
                return row

        # newline="" 配合 csv 模块统一换行，utf-8-sig 写入 BOM
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for i, r in enumerate(records, start=1):
                writer.writerow(build_row(r, i))
        return path
