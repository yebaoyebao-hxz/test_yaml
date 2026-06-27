# -*- coding: utf-8 -*-
"""
智能用例生成: 选中多个 API 描述 → 批量生成冒烟/压测 YAML
POST /api/smart-case/generate-smoke
POST /api/smart-case/generate-stress
"""
import re
import traceback
from typing import List

from flask import Blueprint, request, jsonify
from utils.read_files_tools.smoke_test_case_generator import generate_smoke_case
from utils.read_files_tools.stress_test_case_generator import generate_stress_case
from web_server.config import PROJECT_ROOT
from web_server.db import get_db_conn

import sys

sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "utils" / "read_files_tools"))

smart_bp = Blueprint("smart_case", __name__)


# ── YAML 合并工具 ──

def _merge_yamls(yaml_bodies: list) -> str:
    """
    将多个生成器返回的 YAML 合并为一个统一的 YAML。
    规则：
      - 取第一份的 case_common 作为公共块
      - 各用例块去重编号，避免 key 冲突
    """
    import yaml as yaml_lib

    all_cases = {}
    common = {}

    for i, body in enumerate(yaml_bodies):
        if not body or not body.strip():
            continue
        try:
            data = yaml_lib.safe_load(body)
            if not isinstance(data, dict):
                continue
        except Exception:
            continue

        if i == 0 and "case_common" in data:
            common = data["case_common"]

        for k, v in data.items():
            if k == "case_common":
                continue
            # 去重：如果 key 冲突，加后缀
            base = k
            suffix = 1
            key = base
            while key in all_cases:
                suffix += 1
                key = f"{base}_{suffix}"
            all_cases[key] = v

    if not all_cases and not common:
        return ""

    result = {}
    if common:
        result["case_common"] = common
    result.update(all_cases)
    return yaml_lib.dump(
        result, allow_unicode=True, default_flow_style=False, sort_keys=False
    )


def _guess_input_type(description: str) -> str:
    """根据描述内容判断输入类型: curl | text"""
    desc = description.strip()
    if desc.startswith("curl ") or "--data" in desc or "-X " in desc:
        return "curl"
    return "text"


def _call_generator(generator_func, description: str) -> dict:
    """调用生成器，对单个 API 描述生成 YAML"""
    input_type = _guess_input_type(description)
    return generator_func(input_type, description)


def _save_to_db(descriptions: list, merged_yaml: str, tag: str, model: str):
    """将合并后的 YAML 写入 MySQL test_yaml_cases 表"""
    safe_name = re.sub(
        r'[\\/:*?"<>|]', "", (descriptions[0] or "smart")[:20].strip()
    )[:30] or f"smart_{tag}"
    try:
        mysql_conn = get_db_conn()
        try:
            with mysql_conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO test_yaml_cases
                       (filename, yaml_body, input_type, input_content, summary, model, exec_status)
                       VALUES (%s, %s, %s, %s, %s, %s, 'generated')""",
                    (
                        safe_name,
                        merged_yaml,
                        "text",
                        "\n---\n".join(d[:200] for d in descriptions),
                        f"智能{tag}: {len(descriptions)}个API",
                        model,
                    ),
                )
                mysql_conn.commit()
        finally:
            mysql_conn.close()
    except Exception as e:
        print(f"[WARN] MySQL 写入智能{tag}用例失败: {e}")


# ── 路由 ──

@smart_bp.route("/api/smart-case/generate-smoke", methods=["POST"])
def api_generate_smoke():
    """选中多个 API 描述 → 批量生成冒烟测试用例"""


    try:
        body = request.get_json()
        if not body or "descriptions" not in body:
            return jsonify({"success": False, "error": "缺少 descriptions 字段"}), 400

        descriptions = body.get("descriptions", [])
        normalize_asserts = body.get("normalize_asserts", False)
        if not descriptions:
            return jsonify({"success": False, "error": "无接口描述"}), 400

        results = []
        yaml_bodies = []
        errors = []
        for i, desc in enumerate(descriptions):
            if not desc or not desc.strip():
                continue
            r = _call_generator(generate_smoke_case, desc)
            results.append(r)
            if r.get("success"):
                yb = r.get("yaml_body") or r.get("yaml") or ""
                if yb:
                    yaml_bodies.append(yb)
            else:
                errors.append(f"#{i + 1}: {r.get('error', '未知错误')}")

        if not yaml_bodies:
            return jsonify(
                {"success": False, "error": "所有用例生成失败", "details": errors}
            ), 400

        merged_yaml = _merge_yamls(yaml_bodies)
        _save_to_db(descriptions, merged_yaml, "冒烟", results[0].get("model", ""))

        return jsonify(
            {
                "success": True,
                "yaml_body": merged_yaml,
                "summary": f"智能冒烟: {len(descriptions)}个API → {len(yaml_bodies)}组用例",
                "merged_count": len(yaml_bodies),
                "model": results[0].get("model", ""),
                "errors": errors if errors else None,
            }
        )

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": f"服务异常: {str(e)}"}), 500


@smart_bp.route("/api/smart-case/generate-stress", methods=["POST"])
def api_generate_stress():
    """选中多个 API 描述 → 批量生成压测测试用例"""


    try:
        body = request.get_json()
        if not body or "descriptions" not in body:
            return jsonify({"success": False, "error": "缺少 descriptions 字段"}), 400

        descriptions = body.get("descriptions", [])
        normalize_asserts = body.get("normalize_asserts", False)
        if not descriptions:
            return jsonify({"success": False, "error": "无接口描述"}), 400

        results = []
        yaml_bodies = []
        errors = []

        for i, desc in enumerate(descriptions):
            if not desc or not desc.strip():
                continue
            r = _call_generator(generate_stress_case, desc)
            results.append(r)
            if r.get("success"):
                yb = r.get("yaml_body") or r.get("yaml") or ""
                if yb:
                    yaml_bodies.append(yb)
            else:
                errors.append(f"#{i + 1}: {r.get('error', '未知错误')}")

        if not yaml_bodies:
            return jsonify(
                {"success": False, "error": "所有用例生成失败", "details": errors}
            )

        merged_yaml = _merge_yamls(yaml_bodies)
        _save_to_db(descriptions, merged_yaml, "压测", results[0].get("model", ""))

        return jsonify(
            {
                "success": True,
                "yaml_body": merged_yaml,
                "summary": f"智能压测: {len(descriptions)}个API → {len(yaml_bodies)}组用例",
                "merged_count": len(yaml_bodies),
                "model": results[0].get("model", ""),
                "errors": errors if errors else None,
            }
        )

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": f"服务异常: {str(e)}"}), 500

def generate_smoke_batch(requests: List[dict], normalize_assert=False) -> List[dict]:
    results = []
    for i, req in enumerate(requests):
        r = generate_smoke_case(req.get("type", "text"), req.get("content", ""), normalize_assert)
        r["index"] = i
        results.append(r)
    return results
