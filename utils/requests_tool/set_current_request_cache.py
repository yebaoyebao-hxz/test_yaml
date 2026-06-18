# -*- coding: utf-8 -*-
"""请求缓存桩模块 — 缺失模块占位"""

from typing import Any


class SetCurrentRequestCache:
    """缓存当前请求/响应数据（桩实现）"""

    def __init__(
        self,
        current_request_set_cache: Any = None,
        request_data: Any = None,
        response_data: Any = None,
    ):
        self._cache = current_request_set_cache
        self._request = request_data
        self._response = response_data

    def set_caches_main(self) -> None:
        """写入缓存（桩：无操作）"""
        pass
