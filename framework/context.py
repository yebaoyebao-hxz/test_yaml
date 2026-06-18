"""运行时上下文 —— 线程安全的变量存储，支持提取值缓存。"""

from __future__ import annotations
from typing import Any, Dict, Optional
from threading import Lock
import json


class RuntimeContext:
    """线程安全的运行时变量上下文

    用于存储:
    - 认证 token (Authorization header)
    - 提取的参数 (extract 结果)
    - 用例间传递的数据
    - 自定义变量
    """

    def __init__(self):
        self._variables: Dict[str, Any] = {}
        self._session_headers: Dict[str, str] = {}
        self._lock = Lock()

    # ── 变量存取 ──

    def set(self, key: str, value: Any):
        with self._lock:
            self._variables[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._variables.get(key, default)

    def set_many(self, **kwargs):
        with self._lock:
            self._variables.update(kwargs)

    def pop(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._variables.pop(key, default)

    @property
    def all(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._variables)

    # ── 会话级请求头 ──

    def set_header(self, key: str, value: str):
        with self._lock:
            self._session_headers[key] = value

    def get_headers(self) -> Dict[str, str]:
        with self._lock:
            return dict(self._session_headers)

    def clear_headers(self):
        with self._lock:
            self._session_headers.clear()

    # ── Token 快捷方法 ──

    def set_token(self, token: str, prefix: str = "Bearer"):
        """设置认证 token，自动写入 Authorization header"""
        self.set_header("Authorization", f"{prefix} {token}")
        self.set("_token", token)

    def get_token(self) -> Optional[str]:
        return self.get("_token")

    # ── 序列化 ──

    def dump(self) -> str:
        return json.dumps(self.all, ensure_ascii=False, indent=2)

    def __repr__(self):
        return f"RuntimeContext(vars={len(self._variables)}, headers={list(self._session_headers.keys())})"


# 全局上下文实例（pytest 中可用 fixture 隔离）
_global_context = RuntimeContext()


def get_global_context() -> RuntimeContext:
    """获取全局运行时上下文"""
    return _global_context


def reset_global_context():
    """重置全局上下文"""
    global _global_context
    _global_context = RuntimeContext()
