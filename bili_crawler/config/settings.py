"""配置管理模块。

统一从 ``config.yaml``（若不存在则回退到 ``config.example.yaml``）读取 YAML 配置，
并提供属性式访问。所有请求延迟范围、重试次数、Cookie、导出路径等参数均由此集中管理。
"""

from __future__ import annotations

import os
from typing import Any, Dict

import yaml

# 项目根目录（本文件位于 bili_crawler/config/settings.py）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def project_root() -> str:
    """返回项目根目录的绝对路径。"""
    return _PROJECT_ROOT


class Settings:
    """配置容器，将嵌套 dict 以属性方式暴露，读取缺失键时回退到默认值。"""

    def __init__(self, data: Dict[str, Any]):
        self._data = data

    # ----- 通用取值 -----
    def get(self, path: str, default: Any = None) -> Any:
        """按 ``a.b.c`` 形式的点路径读取配置，缺失则返回 default。"""
        node: Any = self._data
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def section(self, name: str) -> Dict[str, Any]:
        """读取某个顶层配置段，返回其字典（不存在则返回空字典）。"""
        return self._data.get(name, {}) or {}

    # ----- 便捷属性 -----
    @property
    def http(self) -> Dict[str, Any]:
        return self.section("http")

    @property
    def user_agent(self) -> Dict[str, Any]:
        return self.section("user_agent")

    @property
    def cookie(self) -> Dict[str, Any]:
        return self.section("cookie")

    @property
    def export(self) -> Dict[str, Any]:
        return self.section("export")

    @property
    def web(self) -> Dict[str, Any]:
        return self.section("web")


def _find_config_file() -> str:
    """定位配置文件：优先 config.yaml，其次 config.example.yaml。"""
    primary = os.path.join(_PROJECT_ROOT, "config.yaml")
    fallback = os.path.join(_PROJECT_ROOT, "config.example.yaml")
    if os.path.isfile(primary):
        return primary
    if os.path.isfile(fallback):
        return fallback
    raise FileNotFoundError(
        "未找到配置文件，请在项目根目录放置 config.yaml 或 config.example.yaml"
    )


def _normalize_path(value: str, base: str) -> str:
    """将路径归一化为绝对路径。

    相对路径以项目根目录 ``base`` 为基准解析；绝对路径原样返回。
    这样无论以哪个工作目录启动 Web / 命令行，落盘与导出路径都稳定一致。
    """
    if not value:
        return value
    return value if os.path.isabs(value) else os.path.abspath(os.path.join(base, value))


# 需要以项目根目录为基准解析的相对路径键（位于 ``export`` 段内）
_EXPORT_PATH_KEYS = ("output_dir", "raw_dir", "state_dir")


def load_settings(path: str | None = None) -> Settings:
    """加载配置并返回 :class:`Settings` 实例。

    加载后会把 ``export`` 段下的相对路径（output_dir / raw_dir / state_dir）
    统一锚定到项目根目录，避免依赖启动时的当前工作目录。

    Args:
        path: 配置文件路径，留空则自动查找 config.yaml / config.example.yaml。

    Returns:
        Settings: 统一配置对象。
    """
    cfg_path = path or _find_config_file()
    with open(cfg_path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    # 路径归一化：相对路径 → 项目根目录下的绝对路径
    export = data.get("export") or {}
    for key in _EXPORT_PATH_KEYS:
        if key in export and isinstance(export[key], str):
            export[key] = _normalize_path(export[key], _PROJECT_ROOT)
    data["export"] = export

    # 环境变量可覆盖 Web 监听地址（便于 Docker / 容器化部署）
    web_cfg = data.setdefault("web", {})
    env_host = os.environ.get("BILI_WEB_HOST")
    if env_host:
        web_cfg["host"] = env_host
    env_port = os.environ.get("BILI_WEB_PORT")
    if env_port:
        try:
            web_cfg["port"] = int(env_port)
        except ValueError:
            pass

    return Settings(data)
