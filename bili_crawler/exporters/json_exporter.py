"""JSON 导出器：使用 UTF-8 BOM，确保 Windows / Excel 下中文不乱码。"""

from __future__ import annotations

import json
from typing import List

from .base import BaseExporter


class JsonExporter(BaseExporter):
    """将记录导出为带 BOM 的 UTF-8 JSON 文件。"""

    ext = "json"

    def export(self, records: List[dict], path: str) -> str:
        """写入 JSON（数组）。文件头写入 UTF-8 BOM，Excel 可正确识别编码。

        Args:
            records: 字典列表。
            path: 目标路径（自动补 .json）。

        Returns:
            str: 实际文件路径。
        """
        path = self._with_ext(path, self.ext)
        self._ensure_dir(path)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\ufeff")  # UTF-8 BOM
            json.dump(records, fh, ensure_ascii=False, indent=2)
        return path
