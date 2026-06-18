"""参数提取器 —— 从响应中按 jsonpath 提取值，存入运行时上下文。"""

from __future__ import annotations
from typing import Any, Dict, List, Optional

from .models import ServerResponse
from .context import get_global_context
from .assertion import _extract_by_jsonpath


class Extractor:
    """响应数据提取器"""

    def __init__(self, context=None):
        self._ctx = context or get_global_context()

    def extract(self, response: ServerResponse, rules: Optional[Dict[str, str]]) -> Dict[str, Any]:
        """按规则从响应中提取数据。

        Args:
            response: 服务端响应
            rules: {变量名: jsonpath表达式}，如 {"token": "$.data.token"}

        Returns:
            提取到的键值对
        """
        if not rules:
            return {}

        extracted = {}
        for var_name, jsonpath_expr in rules.items():
            if not jsonpath_expr:
                continue
            value = self._extract_one(response.body, jsonpath_expr)
            if value is not None:
                extracted[var_name] = value
                self._ctx.set(var_name, value)

        return extracted

    def extract_all(
        self, response: ServerResponse, rules: Optional[Dict[str, str]]
    ) -> Dict[str, Any]:
        """extract 的别名（返回所有提取结果）"""
        return self.extract(response, rules)

    @staticmethod
    def _extract_one(data: Any, jsonpath_expr: str) -> Optional[Any]:
        """从数据中提取单个值"""
        results = _extract_by_jsonpath(data, jsonpath_expr)
        if results:
            return results[0] if len(results) == 1 else results
        return None

    @staticmethod
    def extract_by_paths(data: Any, paths: List[str]) -> List[Any]:
        """批量提取"""
        results = []
        for p in paths:
            val = _extract_by_jsonpath(data, p)
            results.append(val if val else None)
        return results
