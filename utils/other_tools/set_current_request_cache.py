import json
from typing import Any
from utils.cache_process.cache_control import CacheHandler
import jsonpath as _jsonpath


def _jp(data, expr):
    """兼容jsonpath 新旧版本 API"""
    result = _jsonpath.search(expr, data)
    if not result:
        return False
    return  result


class SetCurrentRequestCache:
    """请求执行后，从响应中提取数据并缓存"""

    def __init__(self,
                 current_request_set_cache: Any = None,
                 request_data: Any = None,
                 response_data: Any = None):
        self._cache_config = current_request_set_cache
        self._request_data = request_data
        self._response_data = response_data

    def set_caches_main(self) -> None:
        """
        遍历 cache_config，对每个 key 执行 jsonpath 提取，写入 CacheHandler

        YAML 示例:
            current_request_set_cache:
              sms_code: $.msg          → 从响应的 msg 字段提取
              token: $.data.token      → 从响应的 data.token 提取
        """
        if not self._cache_config or not self._response:
            return

        if isinstance(self._request,str):
            try:
                response_obj = json.loads(self._response)
            except (json.JSONDecodeError, TypeError):
                return
        else:
            response_obj = self._response
        for cache_key, jsonpath_expr in self._cache_config.items():
            if not jsonpath_expr:
                continue
            result = _jp(response_obj, jsonpath_expr)
            if result:
                value = result[0] if isinstance(result, list) else result
                CacheHandler.update_cache(cache_name=cache_key, value=value)