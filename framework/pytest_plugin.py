"""pytest 集成插件 —— 自动发现 YAML 文件，生成参数化测试，接入 Allure 报告。"""

from __future__ import annotations
import json
import os
import pytest
from pathlib import Path
import yaml
from typing import Any, Dict, Generator, List, Optional

from .parser import CaseParser
from .runner import TestRunner
from .context import RuntimeContext, get_global_context, reset_global_context
from .models import CaseData, CaseResult


# ============================================================
#  Fixtures
# ============================================================

@pytest.fixture(scope="session")
def runtime_context() -> RuntimeContext:
    """全局运行时上下文，整个 session 共享"""
    ctx = get_global_context()
    yield ctx
    reset_global_context()


@pytest.fixture(scope="function")
def test_context() -> RuntimeContext:
    """每个测试函数独立的上下文（会继承 session 级上下文的数据）"""
    return get_global_context()


@pytest.fixture(scope="session")
def test_runner(request, runtime_context):
    """session 级 TestRunner，从命令行参数获取 YAML 路径"""
    yaml_path = request.config.getoption("--yaml-path", default=None)
    if not yaml_path:
        pytest.skip("未指定 --yaml-path")
    config_path = request.config.getoption("--config", default=None)
    with TestRunner(yaml_path, config_path=config_path, context=runtime_context) as runner:
        yield runner


# ============================================================
#  pytest 命令行参数
# ============================================================

def pytest_addoption(parser):
    """注册自定义命令行参数"""
    group = parser.getgroup("rabbit-test")
    group.addoption(
        "--yaml-path",
        action="store",
        default=None,
        help="YAML 用例文件路径，如 data/兔子.yaml",
    )
    group.addoption(
        "--config",
        action="store",
        default=None,
        help="框架配置文件路径，如 common/config.yaml",
    )
    group.addoption(
        "--case-filter",
        action="store",
        default=None,
        help="用例过滤（按 case_id 或 detail 模糊匹配）",
    )


# ============================================================
#  pytest 收集钩子：自动发现 YAML 文件
# ============================================================

def pytest_collect_file(file_path: Path, parent):
    """识别 .yaml/.yml 文件，交给 YamlTestFile 收集"""
    if file_path.suffix in (".yaml", ".yml"):
        # 支持 test_api / test_case / data 目录，以及 --yaml-path 指定的路径
        path_str = str(file_path)
        yaml_path_opt = parent.config.getoption("--yaml-path", default=None) if hasattr(parent, 'config') else None
        if ("test_api" in path_str or "test_case" in path_str or "data" in path_str
                or (yaml_path_opt and os.path.abspath(yaml_path_opt) == os.path.abspath(path_str))):
            return YamlTestFile.from_parent(parent, path=file_path)
    return None


class YamlTestFile(pytest.File):
    """YAML 测试文件 —— 对应一个 .yaml 文件"""

    def collect(self):
        parser = CaseParser(str(self.path))
        cases = parser.parse()

        # ── 新增：压测路由 ──
        if self._has_stress_cases():
            from framework.stress_executor import main as stress_main
            stress_main(str(self.path))
            return  # 不生成 pytest Item

        for case in cases:
            if not case.is_run:
                continue
            yield YamlTestItem.from_parent(
                self,
                name=f"{case.case_id}[{case.detail}]",
                case=case,
            )
    def _has_stress_cases(self) -> bool:
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                raw = yaml.safe_load(f)
            for key, value in raw.items():
                if key.startswith('case_common'):
                    continue
                if isinstance(value, dict) and value.get('stress_type'):
                    return True
        except Exception:
            pass
        return False


class YamlTestItem(pytest.Item):
    """单条 YAML 用例的 pytest Item"""

    def __init__(self, name, parent, case: CaseData):
        super().__init__(name, parent)
        self._case = case

    @property
    def case(self) -> CaseData:
        return self._case

    def runtest(self):
        """执行用例"""
        from .http_client import HttpClient
        from .assertion import AssertionEngine
        from .extractor import Extractor
        from .resolver import VariableResolver
        from .config import Config

        ctx = get_global_context()
        config = Config()

        # 变量替换
        resolver = VariableResolver()
        resolved = self._deep_resolve(self._case, resolver)

        # 请求
        http = HttpClient(config)
        try:
            response = http.execute(resolved)
        finally:
            http.close()

        # 提取
        extractor = Extractor(ctx)
        extractor.extract(response, resolved.extract)

        # 断言
        rules = resolved.get_assert_list()
        if rules:
            engine = AssertionEngine(response)
            results = engine.run(rules)
            failed = [r for r in results if not r.passed]
            if failed:
                # 附加请求/响应用到 Allure
                self._attach_request_response(resolved, response)
                msgs = "\n".join(
                    f"  [{r.rule.jsonpath}] expect={r.rule.expect!r} actual={r.actual!r}"
                    for r in failed
                )
                pytest.fail(f"断言失败 ({len(failed)}/{len(results)}):\n{msgs}")

    def _deep_resolve(self, case: CaseData, resolver) -> CaseData:
        import copy
        c = copy.deepcopy(case)
        c.host = resolver.resolve(c.host)
        c.url = resolver.resolve(c.url)
        c.headers = resolver.resolve(c.headers) or {}
        c.data = resolver.resolve(c.data)
        c.extract = resolver.resolve(c.extract) or {}
        for key, rule in c.asserts.items():
            rule.expect = resolver.resolve(rule.expect)
        return c

    def _attach_request_response(self, case: CaseData, response):
        """附加请求/响应到 Allure 报告"""
        try:
            import allure
            allure.attach(
                json.dumps({
                    "method": case.method.value,
                    "url": case.get_full_url(),
                    "headers": case.headers,
                    "data": case.data,
                }, ensure_ascii=False, indent=2),
                name="请求详情",
                attachment_type=allure.attachment_type.JSON,
            )
            allure.attach(
                json.dumps(response.body, ensure_ascii=False, indent=2)
                if isinstance(response.body, (dict, list))
                else str(response.body),
                name=f"响应 (status={response.status_code})",
                attachment_type=allure.attachment_type.JSON,
            )
        except ImportError:
            pass

    def reportinfo(self):
        return self.path, 0, f"{self._case.case_id}: {self._case.detail}"


# ============================================================
#  allure 报告标记钩子
# ============================================================

@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items):
    """为每个 YAML 测试项添加 Allure 标签"""
    try:
        import allure
    except ImportError:
        return

    for item in items:
        if isinstance(item, YamlTestItem):
            case = item.case
            if case.meta:
                allure.dynamic.epic(case.meta.epic)
                allure.dynamic.feature(case.meta.feature)
                allure.dynamic.story(case.meta.story)
            # 始终打上接口路径标签
            allure.dynamic.tag(case.url)
            allure.dynamic.tag(case.method.value)


# ============================================================
#  报告摘要钩子
# ============================================================

def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """测试结束时打印 YAML 测试的摘要"""
    yaml_items = [
        item for item in terminalreporter.stats.get("passed", [])
        + terminalreporter.stats.get("failed", [])
        if isinstance(item, YamlTestItem)
    ]
    if not yaml_items:
        return

    passed = len([i for i in yaml_items if i in terminalreporter.stats.get("passed", [])])
    failed = len([i for i in yaml_items if i in terminalreporter.stats.get("failed", [])])
    total = passed + failed

    terminalreporter.write_sep("=", "兔子测试框架 - YAML 用例统计")
    terminalreporter.write_line(f"  YAML 用例总数: {total}")
    terminalreporter.write_line(f"  通过: {passed}  |  失败: {failed}")
    if total > 0:
        terminalreporter.write_line(f"  通过率: {passed/total*100:.1f}%")
