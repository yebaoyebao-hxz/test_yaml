"""兔子测试框架 (YAML-Driven API Test Framework)

基于 YAML 用例描述文件，提供解析 → 变量替换 → 请求发送 → 断言校验
→ 参数提取 → 依赖串联 → Allure 报告 的全链路自动化测试能力。

快速开始:
    from framework import TestRunner

    runner = TestRunner("data/兔子.yaml")
    results = runner.run()
    runner.print_report()
"""
__version__ = "2.0.0"
__all__ = [
    "TestRunner",
    "CaseParser",
    "VariableResolver",
    "HttpClient",
    "AssertionEngine",
    "Extractor",
    "RuntimeContext",
    "CaseData",
    "AssertRule",
    "ServerResponse",
]

from .runner import TestRunner
from .parser import CaseParser
from .resolver import VariableResolver
from .http_client import HttpClient
from .assertion import AssertionEngine
from .extractor import Extractor
from .context import RuntimeContext
from .models import CaseData, AssertRule, ServerResponse
