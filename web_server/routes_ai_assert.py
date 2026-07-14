# -*- coding: utf-8 -*-
"""AI 断言接口: /api/ai_assert"""
import sys, traceback

import httpx
import yaml as _yaml
from flask import Blueprint, request, jsonify

from web_server.config import PROJECT_ROOT
from web_server.yaml_utils import sanitize_yaml_scalars

sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "utils" / "read_files_tools"))

ai_assert_bp = Blueprint("ai_assert", __name__)


@ai_assert_bp.route("/api/ai_assert", methods=["POST"])
def api_ai_assert():
    """解析 YAML → 发送 HTTP 请求 → 调用 AI 语义断言"""
    from utils.assertion.assert_control import AI_Assert  # 延迟导入（避免循环依赖）
    try:
        body = request.get_json(force=True) or {}
        yaml_body = body.get("yaml_body", "")
        normalize_asserts = body.get("normalize_asserts", False)
        if not yaml_body:
            return jsonify({"success": False, "error": "YAML 内容为空"}), 400

        safe_yaml_body = sanitize_yaml_scalars(yaml_body)

        class _L(_yaml.SafeLoader):
            pass

        def _h(loader, tag, node):
            if isinstance(node, _yaml.nodes.ScalarNode):
                return tag
            return None

        _L.add_multi_constructor('', _h)
        case_data = _yaml.load(safe_yaml_body, Loader=_L)

        case_ids = [k for k, v in case_data.items() if k != "case_common" and not v.get('stress_type')]
        if not case_ids:
            return jsonify({"success": False, "error": "YAML 中没有用例"}), 400

        # --- 自动补全 host 字段缺失的 scheme ---
        for k, v in case_data.items():
            if k == "case_common":
                continue
            h = v.get('host')
            if isinstance(h, str) and h and not h.startswith(('http://', 'https://')):
                v['host'] = 'https://' + h
        # ---------------------------------------

        results = []
        with httpx.Client(verify=False, timeout=30.0) as client:
            common_host = case_data.get("case_common", {}).get("host", "") if isinstance(
                case_data.get("case_common"), dict) else ""
            for cid in case_ids:
                case = case_data[cid]
                host = case.get("host", "") or common_host
                url = case.get("url", "")
                method = case.get("method", "POST").upper()
                headers = case.get("headers", {})
                data = case.get("data", {})
                detail = case.get("detail", "")

                if not host or not url:
                    results.append({"case_id": cid, "status": "错误", "reason": "缺少 host 或 url"})
                    continue

                full_url = host.rstrip("/") + "/" + url.lstrip("/")

                try:
                    content_type = headers.get("Content-Type", "")
                    if method == "GET":
                        resp = client.get(full_url, params=data, headers=headers)
                    elif "json" in content_type:
                        resp = client.request(method, full_url, json=data, headers=headers)
                    else:
                        resp = client.request(method, full_url, data=data, headers=headers)

                    try:
                        resp_body = resp.json()
                    except Exception:
                        resp_body = resp.text

                    response_data = {
                        "status_code": resp.status_code,
                        "body": resp_body
                    }

                    assert_block = case.get("assert", {})
                    if normalize_asserts:
                        code_rules = assert_block.get("code", {})
                        if isinstance(code_rules, dict):
                            val = code_rules.get("value", "")
                            jp = code_rules.get("jsonpath", "$.code")
                            typ = code_rules.get("type", "==")
                            assert_desc = f"{jp} {typ} {val}"
                        else:
                            assert_desc = detail or ""
                    else:
                        assert_desc_parts = []
                        for field_name, field_rules in assert_block.items():
                            if isinstance(field_rules, dict):
                                val = field_rules.get("value", "")
                                typ = field_rules.get("type", "")
                                jp = field_rules.get("jsonpath", f"$.{field_name}")
                            else:
                                val = field_rules
                                typ = ""
                                jp = f"$.{field_name}"
                            if field_name == "status_code":
                                continue
                            assert_desc_parts.append(f"{jp} {typ} {val}")
                        assert_desc = "; ".join(assert_desc_parts) if assert_desc_parts else detail

                    ai = AI_Assert()
                    status, reason = ai.ai_handle(response_data, assert_desc or detail)

                    results.append({
                        "case_id": cid,
                        "status": status,
                        "reason": reason,
                        "assert_desc": assert_desc or detail,
                        "response_code": resp.status_code
                    })
                except Exception as req_err:
                    results.append({
                        "case_id": cid,
                        "status": "错误",
                        "reason": f"请求异常: {str(req_err)}"
                    })

        all_passed = all(r["status"] == "通过" for r in results)
        return jsonify({
            "success": all_passed,
            "status": "通过" if all_passed else "不通过",
            "results": results,
            "summary": f"{sum(1 for r in results if r['status'] == '通过')}/{len(results)} 通过"
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": f"AI断言异常: {str(e)}"}), 500
