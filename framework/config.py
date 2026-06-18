"""配置管理 —— 支持 YAML 文件 + 环境变量，单例模式。"""

from __future__ import annotations
import os
import yaml
from pathlib import Path
from typing import Any, Dict, Optional
from threading import Lock


class Config:
    """全局配置单例"""

    _instance: Optional[Config] = None
    _lock: Lock = Lock()

    def __new__(cls, config_path: Optional[str] = None):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    obj = super().__new__(cls)
                    obj._initialized = False
                    cls._instance = obj
        return cls._instance

    def __init__(self, config_path: Optional[str] = None):
        if self._initialized:
            return
        self._initialized = True
        self._data: Dict[str, Any] = {}

        # 默认值
        self._data.setdefault("host", os.environ.get("TEST_HOST", "https://wwyd.vip.hnhxzkj.com"))
        self._data.setdefault("timeout", int(os.environ.get("TEST_TIMEOUT", "30")))
        self._data.setdefault("verify_ssl", os.environ.get("TEST_VERIFY_SSL", "false").lower() == "true")
        self._data.setdefault("retry_times", int(os.environ.get("TEST_RETRY", "0")))
        self._data.setdefault("log_level", os.environ.get("TEST_LOG_LEVEL", "INFO"))
        self._data.setdefault("mysql_switch", False)
        self._data.setdefault("mirror_source", "")
        self._data.setdefault("project_name", "兔子")
        self._data.setdefault("env", "test")
        self._data.setdefault("tester_name", "auto")

        if config_path and Path(config_path).exists():
            with open(config_path, "r", encoding="utf-8") as f:
                yaml_data = yaml.safe_load(f)
                if yaml_data:
                    self._data.update(yaml_data)

    @classmethod
    def reset(cls):
        """重置单例（测试用）"""
        cls._instance = None

    @property
    def host(self) -> str:
        return self.get("host", "").rstrip("/")

    @host.setter
    def host(self, value: str):
        self._data["host"] = value

    @property
    def timeout(self) -> int:
        return self.get("timeout", 30)

    @property
    def verify_ssl(self) -> bool:
        return self.get("verify_ssl", False)

    @property
    def mysql_enabled(self) -> bool:
        return self.get("mysql_switch", False)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any):
        self._data[key] = value

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return self._data.get(name)

    def __repr__(self):
        return f"Config(host={self.host!r}, timeout={self.timeout}s)"
