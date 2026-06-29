"""数据模型定义 —— 用 dataclass 清晰描述所有核心结构。"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union
from enum import Enum

from pydantic import field_validator


class HTTPMethod(str, Enum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"


class RequestType(str, Enum):
    JSON = "json"
    PARAMS = "params"
    DATA = "data"
    FORM = "form"
    NONE = "none"


class AssertOperator(str, Enum):
    """断言比较运算符"""
    EQ = "=="
    NOT_EQ = "!="
    GT = ">"
    GE = ">="
    LT = "<"
    LE = "<="
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    LEN_EQ = "len_eq"
    LEN_GT = "len_gt"
    LEN_LT = "len_lt"
    REGEX = "regex"
    IS_NULL = "is_null"
    IS_NOT_NULL = "is_not_null"


@dataclass
class AssertRule:
    """单条断言规则

    YAML 对应:
        code:
          jsonpath: $.code
          type: ==
          value: 0
    """
    jsonpath: str                          # JSONPath 表达式
    operator: AssertOperator               # 比较运算符
    expect: Any                            # 期望值
    assert_type: Optional[str] = None      # AssertType: R_SQL / SQL / D_SQL / None
    message: Optional[str] = None          # 自定义失败消息

    def __repr__(self):
        return (f"AssertRule(jsonpath={self.jsonpath!r}, "
                f"op={self.operator.value}, expect={self.expect!r})")


@dataclass
class CaseMeta:
    """Allure 报告元信息（来自 case_common_N）"""
    epic: str = ""
    feature: str = ""
    story: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {
            "epic": self.epic,
            "feature": self.feature,
            "story": self.story,
        }


@dataclass
class DependentCaseData:
    """用例依赖声明"""
    case_id: str
    dependent_data: Optional[List[Dict[str, Any]]] = None


@dataclass
class CaseData:
    """单个测试用例的完整描述（来自 兔子_NN）"""
    # 标识
    case_id: str                                    # e.g. "兔子_01"
    detail: str = ""                                # e.g. "测试已注册手机号"

    # 请求
    host: str = ""                                  # 域名，可能含 ${{host()}}
    url: str = ""                                   # 路径
    method: HTTPMethod = HTTPMethod.POST
    headers: Dict[str, str] = field(default_factory=dict)
    request_type: RequestType = RequestType.JSON
    data: Any = None                                # 请求体/参数

    # 控制
    is_run: Optional[bool] = True                   # 是否执行
    sleep: Optional[float] = None                   # 请求前等待（秒）

    # 断言
    asserts: Dict[str, AssertRule] = field(default_factory=dict)
    status_code: Optional[int] = None               # HTTP 状态码断言

    # 依赖
    dependence_case: bool = False
    dependence_case_data: Optional[List[DependentCaseData]] = None
    @field_validator('dependence_case_data', mode = 'before')
    @classmethod
    def _convert_dict_to_list(cls, v):
        if isinstance(v, dict):
            return [v]
        return v

    # SQL（预留）
    sql: Optional[List[str]] = None
    setup_sql: Optional[List[str]] = None
    teardown_sql: Optional[List[str]] = None

    # 提取
    extract: Optional[Dict[str, str]] = None         # 响应提取规则

    # 元信息（跨用例共享，如 Allure 标签）
    meta: Optional[CaseMeta] = None

    def get_full_url(self) -> str:
        """拼接完整 URL"""
        h = self.host.rstrip("/")
        u = self.url if self.url.startswith("/") else "/" + self.url
        return h + u

    def get_assert_list(self) -> List[AssertRule]:
        """返回断言规则列表"""
        return list(self.asserts.values())

    def __repr__(self):
        return (f"CaseData(id={self.case_id!r}, method={self.method.value}, "
                f"url={self.url!r}, detail={self.detail!r})")


@dataclass
class ServerResponse:
    """服务端响应包装"""
    status_code: int
    headers: Dict[str, str] = field(default_factory=dict)
    body: Any = None                               # 已解析的 JSON / 原始文本
    text: str = ""                                  # 原始响应文本
    elapsed_ms: float = 0.0                        # 耗时（毫秒）
    cookies: Dict[str, str] = field(default_factory=dict)

    @property
    def json(self) -> Any:
        """返回 JSON body"""
        return self.body

    def __repr__(self):
        body_preview = str(self.body)[:100] if self.body else "None"
        return (f"ServerResponse(status={self.status_code}, "
                f"elapsed={self.elapsed_ms:.0f}ms, body={body_preview})")


@dataclass
class CaseResult:
    """单条用例执行结果"""
    case: CaseData
    passed: bool
    response: Optional[ServerResponse] = None
    assertion_results: List[AssertionResult] = field(default_factory=list)
    error: Optional[str] = None
    elapsed_ms: float = 0.0


@dataclass
class AssertionResult:
    """单条断言结果"""
    rule: AssertRule
    passed: bool
    actual: Any = None
    expect: Any = None
    message: str = ""

    def __repr__(self):
        status = "PASS" if self.passed else "FAIL"
        return f"[{status}] {self.rule.jsonpath}: actual={self.actual!r} expect={self.expect!r}"
