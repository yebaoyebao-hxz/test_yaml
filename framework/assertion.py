"""断言引擎 —— JSONPath 提取 + 运算符比较 + 结果收集。"""

from __future__ import annotations
import re
import json
from typing import Any, Dict, List, Optional

try:
    from jsonpath_ng.ext import parse as jsonpath_parse
    from jsonpath_ng.exceptions import JsonPathParserError
except ImportError:
    jsonpath_parse = None
    JsonPathParserError = Exception

from .models import (
    AssertRule, AssertOperator, ServerResponse, AssertionResult,
)

# 简化的 jsonpath 适配层：如果安装了 jsonpath-ng 就用它，否则用内置简化版
_HAS_JSONPATH_NG = jsonpath_parse is not None


def _extract_by_jsonpath(data: Any, path: str) -> List[Any]:
    """用 jsonpath 表达式从数据中提取值"""
    if _HAS_JSONPATH_NG:
        try:
            expr = jsonpath_parse(path)
            matches = expr.find(data)
            return [match.value for match in matches]
        except Exception:
            return []
    else:
        # 内置简化 jsonpath 实现（支持 $.key.sub 和 $..key）
        return _simple_jsonpath(data, path)


def _simple_jsonpath(data: Any, path: str) -> List[Any]:
    """简化版 jsonpath，支持 $.key.sub 语法"""
    if not path.startswith("$"):
        return []

    # $.key1.key2 → [key1, key2]
    parts = path.lstrip("$").lstrip(".").split(".")
    current = data

    for part in parts:
        if part == "":
            continue
        if part == "..":
            # 递归搜索 ... 简化处理，仅搜索当前层级
            continue
        if isinstance(current, dict):
            current = current.get(part)
            if current is None:
                return []
        elif isinstance(current, list):
            try:
                idx = int(part)
                current = current[idx]
            except (ValueError, IndexError):
                # 列表里按 key 找
                found = []
                for item in current:
                    if isinstance(item, dict):
                        v = item.get(part)
                        if v is not None:
                            found.append(v)
                if found:
                    return found
                return []
        else:
            return []

    return [current] if current is not None else []


class AssertionEngine:
    """断言执行引擎"""

    def __init__(self, response: ServerResponse):
        self.response = response

    def run(self, rules: List[AssertRule]) -> List[AssertionResult]:
        """执行一批断言规则"""
        results = []
        for rule in rules:
            result = self._check_one(rule)
            results.append(result)
        return results

    def _check_one(self, rule: AssertRule) -> AssertionResult:
        """执行单条断言"""
        # 1) 提取实际值
        actual_list = _extract_by_jsonpath(self.response.body, rule.jsonpath)
        if not actual_list:
            return AssertionResult(
                rule=rule,
                passed=False,
                actual=None,
                expect=rule.expect,
                message=f"jsonpath '{rule.jsonpath}' 提取失败，响应中未找到对应值",
            )

        actual = actual_list[0] if len(actual_list) == 1 else actual_list

        # 2) 执行比较
        passed, msg = self._compare(actual, rule.expect, rule.operator)

        return AssertionResult(
            rule=rule,
            passed=passed,
            actual=actual,
            expect=rule.expect,
            message=rule.message or msg,
        )

    def _compare(self, actual: Any, expect: Any, op: AssertOperator) -> tuple:
        """执行比较，返回 (passed, message)"""
        try:
            if op == AssertOperator.EQ:
                ok = actual == expect
                return ok, f"期望={expect}, 实际={actual}" if not ok else ""

            elif op == AssertOperator.NOT_EQ:
                ok = actual != expect
                return ok, f"期望≠{expect}, 实际={actual}" if not ok else ""

            elif op == AssertOperator.GT:
                ok = float(actual) > float(expect)
                return ok, f"期望 > {expect}, 实际={actual}" if not ok else ""

            elif op == AssertOperator.GE:
                ok = float(actual) >= float(expect)
                return ok, f"期望 >= {expect}, 实际={actual}" if not ok else ""

            elif op == AssertOperator.LT:
                ok = float(actual) < float(expect)
                return ok, f"期望 < {expect}, 实际={actual}" if not ok else ""

            elif op == AssertOperator.LE:
                ok = float(actual) <= float(expect)
                return ok, f"期望 <= {expect}, 实际={actual}" if not ok else ""

            elif op == AssertOperator.CONTAINS:
                if isinstance(actual, (list, tuple, dict, str, bytes)):
                    ok = expect in actual
                else:
                    ok = str(expect) in str(actual)
                return ok, f"期望包含 '{expect}', 实际={actual}" if not ok else ""

            elif op == AssertOperator.NOT_CONTAINS:
                if isinstance(actual, (list, tuple, dict, str, bytes)):
                    ok = expect not in actual
                else:
                    ok = str(expect) not in str(actual)
                return ok, f"期望不包含 '{expect}', 实际={actual}" if not ok else ""

            elif op == AssertOperator.LEN_EQ:
                ok = len(actual) == int(expect)
                return ok, f"期望长度={expect}, 实际长度={len(actual)}" if not ok else ""

            elif op == AssertOperator.LEN_GT:
                ok = len(actual) > int(expect)
                return ok, f"期望长度 > {expect}, 实际长度={len(actual)}" if not ok else ""

            elif op == AssertOperator.LEN_LT:
                ok = len(actual) < int(expect)
                return ok, f"期望长度 < {expect}, 实际长度={len(actual)}" if not ok else ""

            elif op == AssertOperator.REGEX:
                ok = bool(re.search(str(expect), str(actual)))
                return ok, f"正则不匹配: pattern={expect}, 实际={actual}" if not ok else ""

            elif op == AssertOperator.IS_NULL:
                ok = actual is None
                return ok, f"期望 null, 实际={actual}" if not ok else ""

            elif op == AssertOperator.IS_NOT_NULL:
                ok = actual is not None
                return ok, f"期望非null, 实际={actual}" if not ok else ""

            else:
                return False, f"不支持的断言运算符: {op}"

        except (TypeError, ValueError) as e:
            return False, f"比较异常: {e}, actual={actual}, expect={expect}"

    @staticmethod
    def summary(results: List[AssertionResult]) -> str:
        """生成断言结果摘要"""
        passed = sum(1 for r in results if r.passed)
        failed = sum(1 for r in results if not r.passed)
        lines = [f"断言结果: {passed}/{len(results)} 通过"]
        for r in results:
            if not r.passed:
                lines.append(f"  ✗ {r}")
        return "\n".join(lines)
