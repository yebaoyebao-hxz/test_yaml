# -*- coding: utf-8 -*-
"""生成接口: /api/generate, /api/batch"""
import re, traceback
from flask import Blueprint, request, jsonify

from web_server.config import PROJECT_ROOT
from web_server.yaml_utils import normalize_yaml_assertions, sanitize_yaml_scalars
from web_server.db import get_db_conn

import sys
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "utils" / "read_files_tools"))

gen_bp = Blueprint("generate", __name__)


@gen_bp.route("/api/generate", methods=["POST"])
def api_generate():
    from utils.read_files_tools.get_yaml_case import generate  # 延迟导入
    """统一生成接口"""
    try:
        body = request.get_json(force=True)
        if not body:
            return jsonify({"success": False, "error": "请求体为空"})

        input_type = body.get("type", "text")
        content = body.get("content", "")
        images = body.get("images", [])

        if not content and not images:
            return jsonify({"success": False, "error": "输入内容为空"})

        if images and content and input_type in ("curl", "text"):
            result = generate("mixed", {"text": content, "input_type": input_type, "images": images})
        elif images and not content:
            result = generate("image", images[0])
        else:
            result = generate(input_type, content)

        normalize = body.get("normalize_asserts", False)

        if normalize and result.get("success"):
            raw_yaml = result.get("yaml", "") or result.get("yaml_body", "")
            if raw_yaml:
                normalized = normalize_yaml_assertions(raw_yaml)
                if result.get("yaml_body"):
                    result["yaml_body"] = normalized
                if result.get("yaml"):
                    result["yaml"] = normalized

        yaml_body = result.get("yaml_body", "")
        if result.get("success") and yaml_body:
            safe_name = result.get("summary", "generated")
            safe_name = re.sub(r'[\\/:*?"<>|]', '', safe_name)[:30] or "auto_yaml"
            try:
                mysql_conn = get_db_conn()
                try:
                    with mysql_conn.cursor() as cur:
                        cur.execute(
                            """INSERT INTO test_yaml_cases
                                (filename, yaml_body, input_type, input_content, summary, model, exec_status)
                                VALUES (%s, %s, %s, %s, %s, %s, 'generated')""",
                            (safe_name, yaml_body, input_type,
                             (content or "")[:10000],
                             result.get("summary", ""),
                             result.get("model", ""))
                        )
                        mysql_conn.commit()
                finally:
                    mysql_conn.close()
            except Exception as e:
                print(f"[WARN] MySQL 写入 YAML 失败: {e}")

        return jsonify(result)

    except Exception as e:
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": f"服务异常: {str(e)}",
        }), 500


@gen_bp.route("/api/batch", methods=["POST"])
def api_batch():
    """批量生成接口"""
    from utils.read_files_tools.get_yaml_case import generate_batch  # 延迟导入
    try:
        body = request.get_json(force=True)
        if not body or "requests" not in body:
            return jsonify({"success": False, "error": "缺少 requests 字段"})

        results = generate_batch(body["requests"])
        return jsonify({"success": True, "results": results})

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
