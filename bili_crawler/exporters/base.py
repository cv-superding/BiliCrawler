"""数据导出层基类。

所有导出器接收「已转换为字典的模型列表」（snake_case 字段），负责落盘为具体格式。
格式统一的字段命名规范由数据模型保证，本层只关注序列化与编码（防中文乱码）。
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import List


class BaseExporter(ABC):
    """导出器抽象基类。"""

    #: 文件扩展名（不含点），子类覆盖
    ext: str = ""

    @abstractmethod
    def export(self, records: List[dict], path: str) -> str:
        """将记录列表导出到指定路径。

        Args:
            records: 已标准化的字典列表（来自模型的 to_dict）。
            path: 目标文件路径（不含扩展名时由子类补上）。

        Returns:
            str: 实际写入的文件路径。
        """
        raise NotImplementedError

    @staticmethod
    def _ensure_dir(path: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    @staticmethod
    def _with_ext(path: str, ext: str) -> str:
        """若 path 无对应扩展名则补上。"""
        if not path.lower().endswith(f".{ext}"):
            return f"{path}.{ext}"
        return path
