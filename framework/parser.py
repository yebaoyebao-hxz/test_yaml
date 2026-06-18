"""YAML 用例解析器 —— 读取兔子.yaml 并生成 CaseData 对象列表。"""

from __future__ import annotations
import re
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .models import (
    CaseData, CaseMeta, AssertRule, AssertOperator,
    HTTPMethod, RequestType,
)


class CaseParser:
    """YAML → CaseData 列表

    处理兔子.yaml 的 "case_common_N / 兔子_NN" 键值对结构：
    - case_common_N → CaseMeta (Allure标签)
    - 兔子_NN → CaseData (请求+断言)
    """

    def __init__(self, yaml_path: str):
        self.yaml_path = Path(yaml_path)
        if not self.yaml_path.exists():
            raise FileNotFoundError(f"YAML 文件不存在: {yaml_path}")
        with open(self.yaml_path, "r", encoding="utf-8") as f:
            self._raw = yaml.safe_load(f) or {}

    # ── 公共入口 ──

    def parse(self) -> List[CaseData]:
        """返回所有解析后的用例列表"""
        pairs = self._pair_cases()
        cases = []
        for meta, case_data_raw in pairs:
            case = self._parse_single(case_data_raw, meta)
            if case is not None:
                cases.append(case)
        return cases

    def parse_grouped(self) -> Dict[str, List[CaseData]]:
        """按 url（接口）分组返回"""
        groups: Dict[str, List[CaseData]] = {}
        for case in self.parse():
            groups.setdefault(case.url, []).append(case)
        return groups

    # ── 键值对匹配 ──

    def _pair_cases(self) -> List[Tuple[Optional[CaseMeta], Dict]]:
        """将 raw YAML 的 case_common / case_common_N 与用例键配对

        规则：
        - case_common / case_common_N → 提取 Allure 元信息，应用到后续所有用例
        - 其余所有键（非 dict 值除外）视为用例，key 即 case_id
        """
        pairs = []
        current_meta = None

        for key in list(self._raw.keys()):
            if key.startswith("case_common"):
                # 提取 Allure 元信息（支持 case_common / case_common_1 等）
                meta_raw = self._raw[key] or {}
                if isinstance(meta_raw, dict):
                    current_meta = CaseMeta(
                        epic=meta_raw.get("allureEpic", ""),
                        feature=meta_raw.get("allureFeature", ""),
                        story=meta_raw.get("allureStory", ""),
                    )
                continue

            # 其余键视为用例（必须为 dict）
            case_raw = self._raw[key]
            if not isinstance(case_raw, dict):
                continue
            case_raw = dict(case_raw)  # 浅拷贝避免修改原始数据
            case_raw["_case_id"] = key
            pairs.append((current_meta, case_raw))

        return pairs

    # ── 单条解析 ──

    def _parse_single(self, raw: Dict[str, Any], meta: Optional[CaseMeta]) -> Optional[CaseData]:
        """从单个 raw dict 构建 CaseData"""
        case_id = raw.pop("_case_id", "unknown")

        # is_run 处理: None / True → True, False → False
        is_run = raw.get("is_run")
        if is_run is None or is_run == "":
            is_run = True
        else:
            is_run = bool(is_run)

        # 构建 CaseData
        case = CaseData(
            case_id=case_id,
            detail=raw.get("detail", ""),
            host=raw.get("host", ""),
            url=raw.get("url", ""),
            method=HTTPMethod(raw.get("method", "POST").upper()),
            headers=raw.get("headers") or {},
            request_type=RequestType(raw.get("requestType", "json").lower()),
            data=raw.get("data"),
            is_run=is_run,
            sleep=self._parse_sleep(raw.get("sleep")),
            dependence_case=raw.get("dependence_case", False),
            dependence_case_data=self._parse_dep(raw.get("dependence_case_data")),
            asserts=self._parse_asserts(raw.get("assert")),
            extract=raw.get("extract") or {},
            sql=raw.get("sql"),
            setup_sql=raw.get("setup_sql"),
            teardown_sql=raw.get("teardown_sql"),
            meta=meta,
        )
        return case

    # ── 断言解析 ──

    def _parse_asserts(self, assert_raw: Any) -> Dict[str, AssertRule]:
        """解析 assert 块 → {key: AssertRule}"""
        if not assert_raw or not isinstance(assert_raw, dict):
            return {}

        rules = {}
        for key, item in assert_raw.items():
            if not isinstance(item, dict):
                continue

            # 提取字段
            jsonpath = item.get("jsonpath", "")
            op_str = item.get("type", "==")
            value = item.get("value")
            assert_type = item.get("AssertType") or None

            # 映射运算符
            operator = self._map_operator(op_str)

            rules[key] = AssertRule(
                jsonpath=jsonpath,
                operator=operator,
                expect=value,
                assert_type=assert_type,
                message=item.get("message"),
            )
        return rules

    @staticmethod
    def _map_operator(op: str) -> AssertOperator:
        _map = {
            "==": AssertOperator.EQ,
            "!=": AssertOperator.NOT_EQ,
            ">": AssertOperator.GT,
            ">=": AssertOperator.GE,
            "<": AssertOperator.LT,
            "<=": AssertOperator.LE,
            "contains": AssertOperator.CONTAINS,
            "not_contains": AssertOperator.NOT_CONTAINS,
            "len_eq": AssertOperator.LEN_EQ,
            "len_gt": AssertOperator.LEN_GT,
            "len_lt": AssertOperator.LEN_LT,
            "regex": AssertOperator.REGEX,
            "is_null": AssertOperator.IS_NULL,
            "is_not_null": AssertOperator.IS_NOT_NULL,
        }
        return _map.get(op, AssertOperator.EQ)

    # ── 辅助 ──

    def _parse_dep(self, dep: Any) -> Optional[List]:
        if not dep:
            return None
        return dep if isinstance(dep, list) else [dep]

    @staticmethod
    def _parse_sleep(val: Any) -> Optional[float]:
        if val is None:
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    def __repr__(self):
        return f"CaseParser(path={self.yaml_path!r})"
