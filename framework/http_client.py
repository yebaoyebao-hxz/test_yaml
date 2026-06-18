"""HTTP 请求引擎 —— 基于 requests.Session，支持重试和超时控制。"""

from __future__ import annotations
import time
import json
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import Any, Dict, Optional, Tuple
from urllib3.exceptions import InsecureRequestWarning

from .models import CaseData, ServerResponse, HTTPMethod, RequestType
from .config import Config

# 禁用 SSL 警告
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)


class HttpClient:
    """HTTP 请求客户端，封装 session 管理和请求执行。"""

    def __init__(self, config: Optional[Config] = None):
        self._config = config or Config()
        self._session = requests.Session()

        # 默认全局 headers（可被用例级 headers 覆盖）
        self._session.headers.update({
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 12; RabbitTest/2.0)",
        })

        # 重试策略
        retry_times = self._config.get("retry_times", 0)
        if retry_times > 0:
            retry = Retry(
                total=retry_times,
                backoff_factor=0.5,
                status_forcelist=[500, 502, 503, 504],
            )
            adapter = HTTPAdapter(max_retries=retry)
            self._session.mount("http://", adapter)
            self._session.mount("https://", adapter)

    # ── 属性 ──

    @property
    def session(self) -> requests.Session:
        return self._session

    def set_header(self, key: str, value: str):
        self._session.headers[key] = value

    def set_headers(self, headers: Dict[str, str]):
        self._session.headers.update(headers)

    def clear_headers(self):
        self._session.headers.clear()

    # ── 核心执行 ──

    def execute(self, case: CaseData, **override_kwargs) -> ServerResponse:
        """执行一个用例的 HTTP 请求。

        Args:
            case: 用例数据
            **override_kwargs: 可覆盖 host/url/headers/data 等

        Returns:
            ServerResponse
        """
        # 构建请求参数（允许覆盖）
        host = override_kwargs.get("host", case.host)
        url = override_kwargs.get("url", case.url)
        full_url = self._build_url(host, url)

        method = override_kwargs.get("method", case.method)
        headers = {**case.headers, **override_kwargs.get("headers", {})}
        req_type = override_kwargs.get("request_type", case.request_type)
        data = override_kwargs.get("data", case.data)
        timeout = override_kwargs.get("timeout", self._config.timeout)

        # 发送请求
        start = time.perf_counter()
        try:
            resp = self._send(
                method=method,
                url=full_url,
                headers=headers,
                req_type=req_type,
                data=data,
                timeout=timeout,
            )
            elapsed_ms = (time.perf_counter() - start) * 1000
        except requests.Timeout as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return ServerResponse(
                status_code=0,
                text=str(e),
                elapsed_ms=elapsed_ms,
            )
        except requests.ConnectionError as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return ServerResponse(
                status_code=0,
                text=f"ConnectionError: {e}",
                elapsed_ms=elapsed_ms,
            )
        except requests.RequestException as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return ServerResponse(
                status_code=0,
                text=f"RequestException: {e}",
                elapsed_ms=elapsed_ms,
            )

        # 解析响应
        body = self._parse_body(resp)
        return ServerResponse(
            status_code=resp.status_code,
            headers=dict(resp.headers),
            body=body,
            text=resp.text,
            elapsed_ms=elapsed_ms,
            cookies=dict(resp.cookies),
        )

    def _send(
        self,
        method: HTTPMethod,
        url: str,
        headers: Dict[str, str],
        req_type: RequestType,
        data: Any,
        timeout: int,
    ) -> requests.Response:
        """发送请求"""
        kwargs: Dict[str, Any] = {
            "headers": headers,
            "timeout": timeout,
            "verify": self._config.verify_ssl,
        }

        if req_type == RequestType.JSON:
            kwargs["json"] = data
        elif req_type == RequestType.PARAMS:
            kwargs["params"] = data
        elif req_type == RequestType.DATA:
            kwargs["data"] = data
        elif req_type == RequestType.FORM:
            kwargs["data"] = data
            kwargs["headers"].setdefault("Content-Type", "application/x-www-form-urlencoded")

        return self._session.request(method=method.value, url=url, **kwargs)

    @staticmethod
    def _build_url(host: str, url: str) -> str:
        """拼接完整 URL"""
        h = host.rstrip("/")
        if url.startswith("http://") or url.startswith("https://"):
            return url
        u = url if url.startswith("/") else "/" + url
        return h + u

    @staticmethod
    def _parse_body(resp: requests.Response) -> Any:
        """尝试解析响应体为 JSON，失败则返回原始文本"""
        try:
            return resp.json()
        except (json.JSONDecodeError, ValueError):
            return resp.text

    def close(self):
        self._session.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
