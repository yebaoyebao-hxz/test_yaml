"""测试运行器 —— 编排"解析→变量替换→请求→提取→断言"全流程。"""

from __future__ import annotations
import time
import json
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .models import CaseData, ServerResponse, CaseResult
from .parser import CaseParser
from .resolver import VariableResolver
from .http_client import HttpClient
from .assertion import AssertionEngine
from .extractor import Extractor
from .context import RuntimeContext, get_global_context, reset_global_context
from .config import Config


class TestRunner:
    """测试运行器 —— 执行 YAML 文件中定义的全部用例。"""

    def __init__(
        self,
        yaml_path: str,
        config_path: Optional[str] = None,
        context: Optional[RuntimeContext] = None,
    ):
        self.yaml_path = Path(yaml_path)
        self._config = Config(config_path)

        # 核心组件
        self._parser = CaseParser(str(self.yaml_path))
        self._resolver = VariableResolver()
        self._http = HttpClient(self._config)
        self._extractor = Extractor(context)
        self._context = context or get_global_context()

        # 状态
        self._cases: List[CaseData] = []
        self._results: List[CaseResult] = []

    def _has_stress_cases(self) -> bool:
        """检查 YAML 中是否包含压测用例（存在 stress_type 字段）"""
        import yaml
        try:
            with open(self.yaml_path, 'r', encoding='utf-8') as f:
                raw = yaml.safe_load(f)
            for key, value in raw.items():
                if key.startswith('case_common'):
                    continue
                if isinstance(value, dict) and value.get('stress_type'):
                    return True
        except Exception:
            pass
        return False

    # ── 流程入口 ──

    def run(self, case_filter: Optional[str] = None) -> List[CaseResult]:
        """执行全部用例。

        Args:
            case_filter: 可选，按 case_id / detail 过滤（模糊匹配）
        """
        # ── 新增：压测路由 ──
        if self._has_stress_cases():
            from .stress_executor import main as stress_main
            stress_main(str(self.yaml_path))
            return []  # 压测模式不返回 CaseResult

        self._cases = self._parser.parse()
        if case_filter:
            self._cases = [
                c for c in self._cases
                if case_filter in c.case_id or case_filter in c.detail
            ]

        self._results = []
        for case in self._cases:
            if not case.is_run:
                continue
            result = self._run_one(case)
            self._results.append(result)

        return self._results

    def run_api(self, api_path: str, case_filter: Optional[str] = None) -> List[CaseResult]:
        """按接口路径过滤执行"""
        return self.run(case_filter=api_path if not case_filter else case_filter)

    # ── 单条执行 ──

    def _run_one(self, case: CaseData) -> CaseResult:
        start = time.perf_counter()

        try:
            # 1) 变量替换
            resolved_case = self._resolve_case(case)

            # 2) 请求前等待
            if resolved_case.sleep and resolved_case.sleep > 0:
                time.sleep(resolved_case.sleep)

            # 3) 发送请求
            response = self._http.execute(resolved_case)

            # 4) 提取参数
            self._extractor.extract(response, resolved_case.extract)

            # 5) 断言
            rules = resolved_case.get_assert_list()
            assertion_results = []
            if rules:
                engine = AssertionEngine(response)
                assertion_results = engine.run(rules)

            # 6) HTTP 状态码断言
            if resolved_case.status_code is not None and response.status_code != resolved_case.status_code:
                assertion_results.append(
                    type("_", (), {"rule": None, "passed": False, "actual": response.status_code,
                                   "expect": resolved_case.status_code, "message": "HTTP状态码不匹配"})(),
                )

            all_passed = all(r.passed for r in assertion_results) if assertion_results else True
            elapsed_ms = (time.perf_counter() - start) * 1000

            return CaseResult(
                case=case,
                passed=all_passed,
                response=response,
                assertion_results=assertion_results,
                elapsed_ms=elapsed_ms,
            )

        except Exception as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return CaseResult(
                case=case,
                passed=False,
                error=f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
                elapsed_ms=elapsed_ms,
            )

    # ── 变量替换 ──

    def _resolve_case(self, case: CaseData) -> CaseData:
        """深拷贝 case 并替换所有模板变量"""
        import copy
        resolved = copy.deepcopy(case)

        # 递归解析所有字段
        resolved.host = self._resolver.resolve(case.host)
        resolved.url = self._resolver.resolve(case.url)
        resolved.headers = self._resolver.resolve(case.headers) or {}
        resolved.data = self._resolver.resolve(case.data)
        resolved.extract = self._resolver.resolve(case.extract) or {}

        # 解析断言规则中的 expect 值
        for key, rule in resolved.asserts.items():
            rule.expect = self._resolver.resolve(rule.expect)

        return resolved

    # ── 报告 ──

    def print_report(self):
        """打印执行报告"""
        total = len(self._results)
        passed = sum(1 for r in self._results if r.passed)
        failed = total - passed

        print(f"\n{'='*60}")
        print(f"  测试报告: {self.yaml_path.name}")
        print(f"  总计: {total} | 通过: {passed} | 失败: {failed}")
        if total > 0:
            print(f"  通过率: {passed/total*100:.1f}%")
        print(f"{'='*60}")

        for r in self._results:
            status = "✓" if r.passed else "✗"
            elapsed = f"{r.elapsed_ms:.0f}ms"
            print(f"\n  {status} [{r.case.method.value}] {r.case.detail}")
            print(f"     URL: {r.case.get_full_url()}")
            print(f"     耗时: {elapsed}")

            if r.response:
                print(f"     状态码: {r.response.status_code}")
                body_preview = str(r.response.body)[:80]
                print(f"     响应: {body_preview}")

            for ar in r.assertion_results:
                s = "✓" if ar.passed else "✗"
                print(f"     {s} 断言: {ar}")

            if r.error:
                print(f"     ✗ 异常: {r.error[:200]}")

    @property
    def results(self) -> List[CaseResult]:
        return self._results

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self._results)

    def to_dict(self) -> List[Dict]:
        """导出结果列表为可序列化的 dict"""
        output = []
        for r in self._results:
            item = {
                "case_id": r.case.case_id,
                "detail": r.case.detail,
                "passed": r.passed,
                "elapsed_ms": r.elapsed_ms,
                "method": r.case.method.value,
                "url": r.case.get_full_url(),
                "assertions": [],
                "error": r.error,
            }
            if r.response:
                item["status_code"] = r.response.status_code
                item["response_body"] = str(r.response.body)[:500]
            for ar in r.assertion_results:
                item["assertions"].append({
                    "passed": ar.passed,
                    "jsonpath": ar.rule.jsonpath,
                    "operator": ar.rule.operator.value,
                    "expect": ar.rule.expect,
                    "actual": ar.actual,
                    "message": ar.message,
                })
            output.append(item)
        return output

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._http.close()
