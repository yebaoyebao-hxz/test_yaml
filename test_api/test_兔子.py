"""测试流程：读取 YAML 用例 → 发送请求 → 断言 → Allure 报告"""

import json
import pytest
import requests
import yaml
import allure
import os
import urllib3
from jsonpath import JSONPath

urllib3.disable_warnings()  # 内网测试，忽略 SSL 警告

# ============================================================
#  第1步：加载配置
# ============================================================
_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(_PROJ_ROOT, "common", "config.yaml"), encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)

HOST = CONFIG["host"]  # wwyd.vip.hnhxzkj.com
BASE_URL = f"https://{HOST}"

# ============================================================
#  第2步：读取 YAML 用例 + 解析模板变量
# ============================================================
def load_yaml_cases(yaml_path: str) -> list[dict]:
    """读取 YAML，替换 ${{host()}} 等模板变量，返回用例列表"""
    with open(yaml_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    cases = []
    for case_id, case_data in raw.items():
        if case_id == "case_common":   # 跳过公共配置
            continue

        # 替换 host 模板变量
        host_val = case_data.get("host", "")
        if "${{host()}}" in str(host_val):
            host_val = BASE_URL

        # 拼接完整 URL
        url = host_val + case_data.get("url", "")

        cases.append({
            "case_id": case_id,
            "url": url,
            "method": case_data.get("method", "POST"),
            "detail": case_data.get("detail", ""),
            "headers": case_data.get("headers") or {},
            "data": case_data.get("data") or {},
            "asserts": case_data.get("assert") or {},
            "extract": case_data.get("extract") or {},
        })
    return cases

# ============================================================
#  第3步：发送 HTTP 请求
# ============================================================
def send_request(case: dict, session: requests.Session) -> dict:
    """根据用例配置发送请求，返回响应 JSON"""
    method = case["method"].upper()
    url = case["url"]
    headers = case["headers"] | {"accept": "application/json"}
    body = case["data"]

    if method in ("GET", "DELETE"):
        resp = session.request(method, url, headers=headers, params=body,
                               timeout=10, verify=False)
    else:
        resp = session.request(method, url, headers=headers, json=body,
                               timeout=10, verify=False)
    return resp.json()

# ============================================================
#  第4步：断言校验
# ============================================================
def run_assertions(response: dict, asserts: dict, case_name: str):
    """遍历 assert 字段，用 jsonpath 提取实际值，与期望值对比"""
    for field_name, rule in asserts.items():
        if not isinstance(rule, dict):
            continue

        jsonpath_expr = rule.get("jsonpath")      # 如 $.code
        expect_value = rule.get("value")
        op = rule.get("type", "==")               # == / != / contains 等

        if not jsonpath_expr:
            continue

        results = JSONPath(jsonpath_expr).parse(response)
        actual_value = results[0] if results else None

        if op == "==":
            assert actual_value == expect_value, \
                f"[{case_name}] {field_name}: 期望={expect_value}, 实际={actual_value}"
        elif op == "!=":
            assert actual_value != expect_value, \
                f"[{case_name}] {field_name}: 期望≠{expect_value}, 实际={actual_value}"

# ============================================================
#  第5步：pytest + Allure 执行
# ============================================================
CASE_LIST = load_yaml_cases(os.path.join(_PROJ_ROOT, "data", "兔子.yaml"))

# 创建全局 session（保持 cookie/连接复用）
_http_session = requests.Session()

@pytest.mark.parametrize("case", CASE_LIST, ids=[c["case_id"] for c in CASE_LIST])
def test_case(case):
    """每条 YAML 用例生成一个 pytest 测试函数"""
    detail = case["detail"]
    allure.dynamic.title(detail)
    allure.dynamic.description(case["url"])

    with allure.step(f"[{case['method']}] {case['url']}"):
        response = send_request(case, _http_session)

    with allure.step("断言校验"):
        run_assertions(response, case["asserts"], case["case_id"])

    allure.attach(
        json.dumps(response, ensure_ascii=False, indent=2),
        name="响应数据", attachment_type=allure.attachment_type.JSON
    )

# ============================================================
#  第6步：命令行执行
# ============================================================
if __name__ == "__main__":
    pytest.main([
        "-vs",
        __file__,
        "--clean-alluredir",
        "--alluredir=allure-result"
    ])
    # 生成 HTML 报告
    import os
    os.system("allure generate allure-result -o report/html --clean")
    print("[报告] report/html/index.html")
