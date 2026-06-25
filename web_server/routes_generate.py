# -*- coding: utf-8 -*-
"""生成接口: /api/generate, /api/batch, /api/generate-and-run"""
import re, os, sys, traceback, subprocess, shutil, json
from pathlib import Path
from datetime import datetime as _dt

from flask import Blueprint, request, jsonify

from web_server.config import PROJECT_ROOT, REPORT_DIR, _get_db
from web_server.yaml_utils import normalize_yaml_assertions, sanitize_yaml_scalars
from web_server.db import get_db_conn
from web_server.templates import CONFTEST_CODE, make_test_code

sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "utils" / "read_files_tools"))

gen_bp = Blueprint("generate", __name__)


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════

def _safe_ident(raw: str, fallback: str = "auto_case") -> str:
    """清洗为合法 Python 标识符（仅保留 ASCII 字母数字下划线）"""
    s = raw.replace(" ", "_").replace("-", "_")
    s = "".join(c for c in s if c.isascii() and (c.isalnum() or c == "_"))
    s = s.strip("_")
    if not s or s[0].isdigit():
        s = "_" + s if s else ""
    return s if s else fallback


def _save_yaml_to_mysql(filename, yaml_body, input_type, input_content, summary, model, test_type="functional"):
    """统一 MySQL 存储：写入 test_yaml_cases 表，返回 case_id。
    若 test_type 列不存在（旧表），自动降级为不写该字段。
    """
    try:
        mysql_conn = get_db_conn()
        try:
            with mysql_conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO test_yaml_cases
                        (filename, yaml_body, input_type, input_content, summary, model, test_type, exec_status)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, 'generated')""",
                    (filename, yaml_body, input_type, (input_content or "")[:10000],
                     summary, model, test_type)
                )
                mysql_conn.commit()
                return cur.lastrowid
        finally:
            mysql_conn.close()
    except Exception as e:
        # 可能是 test_type 列不存在（旧表），降级重试
        if "test_type" in str(e).lower() or "Unknown column" in str(e):
            try:
                mysql_conn = get_db_conn()
                try:
                    with mysql_conn.cursor() as cur:
                        cur.execute(
                            """INSERT INTO test_yaml_cases
                                (filename, yaml_body, input_type, input_content, summary, model, exec_status)
                                VALUES (%s, %s, %s, %s, %s, %s, 'generated')""",
                            (filename, yaml_body, input_type, (input_content or "")[:10000],
                             summary, model)
                        )
                        mysql_conn.commit()
                        return cur.lastrowid
                finally:
                    mysql_conn.close()
            except Exception as e2:
                print(f"[WARN] MySQL 降级写入也失败: {e2}")
                return None
        print(f"[WARN] MySQL 写入 YAML 失败: {e}")
        return None


def _save_yaml_to_sqlite(filename, input_type, input_content, summary, yaml_body, model):
    """写入 SQLite history.db，返回 record_id"""
    try:
        with _get_db() as conn:
            conn.execute(
                """INSERT INTO test_cases (filename, input_type, input_content, summary, yaml_body, model)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (filename, input_type, input_content[:10000] if input_content else "",
                 summary, yaml_body, model)
            )
            return conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    except Exception as e:
        print(f"[WARN] SQLite 写入失败: {e}")
        return None


def _dispatch_generator(test_type: str, input_type: str, content: str, images=None):
    """按 test_type 分发到对应的生成器，返回统一 dict 结果"""
    if test_type == "smoke":
        from utils.read_files_tools.smoke_test_case_generator import generate_smoke_case
        return generate_smoke_case(input_type, content)
    elif test_type == "stress":
        from utils.read_files_tools.stress_test_case_generator import generate_stress_case
        return generate_stress_case(input_type, content)
    else:
        from utils.read_files_tools.get_yaml_case import generate
        if images and content and input_type in ("curl", "text"):
            return generate("mixed", {"text": content, "input_type": input_type, "images": images})
        elif images and not content:
            return generate("image", images[0])
        else:
            return generate(input_type, content)


# ═══════════════════════════════════════════════════════════════
# 核心：一站式 生成→执行→AI断言→报告→存库
# ═══════════════════════════════════════════════════════════════

def _execute_and_report(yaml_body, safe_name, input_type="", input_content="",
                        summary="", model="", test_type="functional"):
    """
    一站式执行管线：
      1. 保存 YAML 到 data/ 目录
      2. 存入 SQLite + MySQL
      3. 解析 YAML → 生成 test_*.py
      4. 执行 pytest（带 Allure）
      5. 生成 Allure HTML 报告
      6. AI 语义断言（遍历每个用例发真实请求）
      7. 更新数据库执行状态
    返回 dict。
    """
    import yaml as _yaml

    result = {
        "success": True,
        "execute": {},
        "ai_assert": None,
        "report_url": "",
        "mysql_case_id": None,
        "sqlite_id": None,
    }

    # ── 1. 保存 YAML 到 data/ ──
    data_dir = PROJECT_ROOT / "data"
    data_dir.mkdir(exist_ok=True)
    yaml_path = data_dir / f"{safe_name}.yaml"
    clean_yaml = sanitize_yaml_scalars(yaml_body)
    yaml_path.write_text(clean_yaml, encoding="utf-8")

    # ── 2. 数据库 ──
    result["sqlite_id"] = _save_yaml_to_sqlite(
        safe_name, input_type, input_content, summary, yaml_body, model
    )
    result["mysql_case_id"] = _save_yaml_to_mysql(
        safe_name, yaml_body, input_type, input_content, summary, model, test_type
    )

    # ── 3. 解析 YAML ──
    class _SafeStringLoader(_yaml.SafeLoader):
        pass

    def _tag_handler(loader, tag_suffix, node):
        if isinstance(node, _yaml.nodes.ScalarNode):
            return tag_suffix
        return None
    _SafeStringLoader.add_multi_constructor('', _tag_handler)

    safe_yaml_body = sanitize_yaml_scalars(yaml_body)
    try:
        case_data = _yaml.load(safe_yaml_body, Loader=_SafeStringLoader)
    except Exception as ye:
        result["success"] = False
        result["error"] = f"YAML 解析失败: {ye}"
        return result

    common = case_data.get("case_common", {})
    case_ids = [k for k in case_data.keys() if k != "case_common"]
    if not case_ids:
        result["success"] = False
        result["error"] = "YAML 中没有用例"
        return result

    # 生成 yaml_stem（文件名标识）
    feature = common.get("allureFeature", "") or common.get("allureEpic", "")
    yaml_stem = _safe_ident(feature) if feature and _safe_ident(feature) != "auto_case" else _safe_ident(safe_name)
    bare = yaml_stem.lstrip("_")
    if yaml_stem == "auto_case" or len(yaml_stem) < 2 or bare == "" or bare.isdigit():
        yaml_stem = "case_" + _dt.now().strftime("%m%d_%H%M%S")

    # extra_tags（smoke / stress Allure 标签）
    extra_tags = []
    if common.get("smoke"):
        extra_tags.append("smoke")
    if common.get("stress"):
        extra_tags.append("stress")

    # ── 4. 生成 pytest 测试文件 ──
    test_case_dir = PROJECT_ROOT / "test_case"
    test_case_dir.mkdir(exist_ok=True)
    file_name = f"test_{yaml_stem}.py"
    case_path_obj = test_case_dir / file_name
    case_path = str(case_path_obj)

    (test_case_dir / "conftest.py").write_text(CONFTEST_CODE, encoding="utf-8")
    test_code = make_test_code(case_ids, common, yaml_stem, file_name, extra_tags)
    case_path_obj.write_text(test_code, encoding="utf-8")

    _exec_env = {**os.environ, "CASE_YAML": str(yaml_path)}

    # ── 5. 清理旧的 allure-results ──
    allure_results_dir = PROJECT_ROOT / "report" / "allure-results"
    if allure_results_dir.exists():
        shutil.rmtree(str(allure_results_dir))
    allure_results_dir.mkdir(parents=True, exist_ok=True)

    # ── 6. 执行 pytest ──
    pytest_cmd = [
        sys.executable, "-m", "pytest", case_path,
        "--alluredir", str(allure_results_dir),
        "-v",
    ]
    proc = subprocess.run(
        pytest_cmd,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(PROJECT_ROOT), env=_exec_env,
    )
    result["execute"] = {
        "pytest_rc": proc.returncode,
        "stdout": proc.stdout[-5000:] if len(proc.stdout) > 5000 else proc.stdout,
        "stderr": proc.stderr[-2000:] if len(proc.stderr) > 2000 else proc.stderr,
        "test_file": case_path,
        "yaml_file": str(yaml_path),
    }

    # ── 7. 生成 Allure HTML 报告 ──
    allure_bin = r"E:\allure-2.41.0\bin\allure.bat"
    if not os.path.exists(allure_bin):
        allure_bin = "allure"
    allure_ok = False
    try:
        allure_proc = subprocess.run(
            [allure_bin, "generate", str(allure_results_dir), "-o", str(REPORT_DIR), "--clean"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        allure_ok = ("successfully generated" in (allure_proc.stdout or "") or
                     "successfully generated" in (allure_proc.stderr or "") or
                     os.path.exists(REPORT_DIR / "index.html"))
    except (FileNotFoundError, OSError) as e:
        print(f"[WARN] allure 命令 ({allure_bin}) 不可用: {e}")

    if os.path.exists(REPORT_DIR / "index.html"):
        result["report_url"] = "/report/index.html"

    # ── 8. AI 语义断言 ──
    from utils.assertion.assert_control import AI_Assert
    import httpx

    ai_results = []
    with httpx.Client(verify=False, timeout=30.0) as client:
        common_host = common.get("host", "") if isinstance(common, dict) else ""
        for cid in case_ids:
            case = case_data[cid]
            host = case.get("host", "") or common_host
            url = case.get("url", "")
            method = case.get("method", "POST").upper()
            headers = case.get("headers", {}) or {}
            data = case.get("data", {}) or {}
            detail = case.get("detail", "")

            if not host or not url:
                ai_results.append({"case_id": cid, "status": "错误", "reason": "缺少 host 或 url"})
                continue

            full_url = host.rstrip("/") + "/" + url.lstrip("/")
            try:
                content_type = headers.get("Content-Type", "")
                if method == "GET":
                    resp = client.get(full_url, params=data, headers=headers)
                elif "json" in str(content_type).lower():
                    resp = client.request(method, full_url, json=data, headers=headers)
                else:
                    resp = client.request(method, full_url, data=data, headers=headers)

                try:
                    resp_body = resp.json()
                except Exception:
                    resp_body = resp.text

                response_data = {"status_code": resp.status_code, "body": resp_body}

                # 构建断言描述（跳过性能类断言字段，那些需压测框架才有数据）
                assert_block = case.get("assert", {}) or {}
                assert_parts = []
                skip_fields = {"status_code", "response_time", "avg_response_time",
                               "max_response_time", "tps", "error_rate"}
                for field_name, field_rules in assert_block.items():
                    if field_name in skip_fields:
                        continue
                    if isinstance(field_rules, dict):
                        val = field_rules.get("value", "")
                        typ = field_rules.get("type", "")
                        jp = field_rules.get("jsonpath", f"$.{field_name}")
                    else:
                        val = field_rules
                        typ = ""
                        jp = f"$.{field_name}"
                    assert_parts.append(f"{jp} {typ} {val}")
                assert_desc = "; ".join(assert_parts) if assert_parts else detail

                ai = AI_Assert()
                status, reason = ai.ai_handle(response_data, assert_desc)

                ai_results.append({
                    "case_id": cid,
                    "status": status,
                    "reason": reason,
                    "response_code": resp.status_code,
                })
            except Exception as req_err:
                ai_results.append({
                    "case_id": cid,
                    "status": "错误",
                    "reason": f"请求异常: {str(req_err)}",
                })

    passed = sum(1 for r in ai_results if r["status"] == "通过")
    result["ai_assert"] = {
        "total": len(ai_results),
        "passed": passed,
        "failed": len(ai_results) - passed,
        "results": ai_results,
        "summary": f"{passed}/{len(ai_results)} 通过",
    }

    # ── 9. 更新数据库执行状态 ──
    if result["sqlite_id"]:
        try:
            with _get_db() as conn:
                conn.execute(
                    "UPDATE test_cases SET executed=1, report_path=? WHERE id=?",
                    (str(REPORT_DIR), result["sqlite_id"])
                )
        except Exception as e:
            print(f"[WARN] SQLite 更新状态失败: {e}")

    mysql_cid = result["mysql_case_id"]
    if mysql_cid:
        # 读取 Allure summary 统计
        summary_file = REPORT_DIR / "widgets" / "summary.json"
        stats = {}
        if summary_file.exists():
            try:
                with open(summary_file, "r", encoding="utf-8") as f:
                    stats = json.load(f).get("statistic", {})
            except Exception:
                pass

        exec_status = "passed" if proc.returncode == 0 else "failed"
        try:
            mysql_conn = get_db_conn()
            try:
                with mysql_conn.cursor() as cur:
                    total = stats.get("total", len(case_ids)) or len(case_ids)
                    # 写入 Allure 报告记录
                    cur.execute(
                        """INSERT INTO test_allure_reports
                            (yaml_case_id, report_path, total, passed, failed, skipped, broken,
                             pass_rate, duration, exec_status)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        (
                            mysql_cid, str(REPORT_DIR),
                            stats.get("total", len(case_ids)),
                            stats.get("passed", 0),
                            stats.get("failed", 0),
                            stats.get("skipped", 0),
                            stats.get("broken", 0),
                            round(stats.get("passed", 0) / max(total, 1) * 100, 2),
                            stats.get("duration", 0),
                            exec_status,
                        )
                    )
                    # 更新用例表执行状态
                    cur.execute(
                        "UPDATE test_yaml_cases SET exec_status=%s WHERE id=%s",
                        (exec_status, mysql_cid),
                    )
                    mysql_conn.commit()
            finally:
                mysql_conn.close()
        except Exception as e:
            print(f"[WARN] MySQL 更新报告失败: {e}")

    return result


# ═══════════════════════════════════════════════════════════════
# /api/generate  — 支持 test_type 分发
# ═══════════════════════════════════════════════════════════════

@gen_bp.route("/api/generate", methods=["POST"])
def api_generate():
    """统一生成接口。

    test_type 参数分发:
      - "default" (默认): 通用功能测试 → get_yaml_case.generate()
      - "smoke"         : 冒烟测试      → smoke_test_case_generator.generate_smoke_case()
      - "stress"        : 压测测试      → stress_test_case_generator.generate_stress_case()
    """
    try:
        body = request.get_json(force=True)
        if not body:
            return jsonify({"success": False, "error": "请求体为空"})

        test_type = body.get("test_type", "default")
        input_type = body.get("type", "text")
        content = body.get("content", "")
        images = body.get("images", [])

        if not content and not images:
            return jsonify({"success": False, "error": "输入内容为空"})

        # ── 分发到对应生成器 ──
        result = _dispatch_generator(test_type, input_type, content, images)

        # ── 断言标准化（可选） ──
        normalize = body.get("normalize_asserts", False)
        if normalize and result.get("success"):
            raw_yaml = result.get("yaml", "") or result.get("yaml_body", "")
            if raw_yaml:
                normalized = normalize_yaml_assertions(raw_yaml)
                if result.get("yaml_body"):
                    result["yaml_body"] = normalized
                if result.get("yaml"):
                    result["yaml"] = normalized

        # ── 统一 MySQL 存储 ──
        yaml_body = result.get("yaml_body", "")
        if result.get("success") and yaml_body:
            safe_name = result.get("summary", "generated")
            safe_name = re.sub(r'[\\/:*?"<>|]', '', safe_name)[:30] or "auto_yaml"
            _save_yaml_to_mysql(
                filename=safe_name,
                yaml_body=yaml_body,
                input_type=input_type,
                input_content=(content or "")[:10000],
                summary=result.get("summary", ""),
                model=result.get("model", ""),
                test_type=test_type,
            )

        return jsonify(result)

    except Exception as e:
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": f"服务异常: {str(e)}",
        }), 500


# ═══════════════════════════════════════════════════════════════
# /api/generate-and-run  — 一站式：生成→执行→AI断言→报告→存库
# ═══════════════════════════════════════════════════════════════

@gen_bp.route("/api/generate-and-run", methods=["POST"])
def api_generate_and_run():
    """一站式接口：生成 YAML 用例 → 执行 pytest → AI 语义断言 → Allure 报告 → 数据库。

    请求体:
      {
        "test_type": "default" | "smoke" | "stress",
        "type": "text" | "curl",
        "content": "API描述或curl命令",
        "images": []           // 可选
      }

    返回:
      {
        "success": true/false,
        "generate": { ... },   // 生成阶段结果
        "execute": { ... },    // pytest 执行结果
        "ai_assert": { ... },  // AI 断言结果
        "report_url": "...",   // Allure 报告路径
        "yaml_file": "..."     // 保存的 YAML 文件路径
      }
    """
    try:
        body = request.get_json(force=True)
        if not body:
            return jsonify({"success": False, "error": "请求体为空"})

        test_type = body.get("test_type", "default")
        input_type = body.get("type", "text")
        content = body.get("content", "")
        images = body.get("images", [])

        if not content and not images:
            return jsonify({"success": False, "error": "输入内容为空"})

        # ── 阶段1: 用例生成 ──
        gen_result = _dispatch_generator(test_type, input_type, content, images)

        if not gen_result.get("success"):
            return jsonify({
                "success": False,
                "error": f"用例生成失败: {gen_result.get('error', '未知错误')}",
                "generate": gen_result,
            }), 400

        yaml_body = gen_result.get("yaml_body", "")
        if not yaml_body:
            return jsonify({
                "success": False,
                "error": "生成的 YAML 为空",
                "generate": gen_result,
            }), 400

        # ── 阶段2: 执行 + AI 断言 + 报告 + 存库 ──
        safe_name = gen_result.get("summary", "auto_yaml")
        safe_name = re.sub(r'[\\/:*?"<>|]', '', safe_name)[:30] or "auto_yaml"

        exec_result = _execute_and_report(
            yaml_body=yaml_body,
            safe_name=safe_name,
            input_type=input_type,
            input_content=(content or "")[:10000],
            summary=gen_result.get("summary", ""),
            model=gen_result.get("model", ""),
            test_type=test_type,
        )

        return jsonify({
            "success": exec_result.get("success", False),
            "generate": {
                "summary": gen_result.get("summary", ""),
                "model": gen_result.get("model", ""),
                "test_type": test_type,
                "case_count": gen_result.get("yaml_body", "").count("\n  url:") or "未知",
            },
            "execute": exec_result.get("execute", {}),
            "ai_assert": exec_result.get("ai_assert"),
            "report_url": exec_result.get("report_url", ""),
            "yaml_file": str(PROJECT_ROOT / "data" / f"{safe_name}.yaml"),
            "error": exec_result.get("error", ""),
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": f"执行异常: {str(e)}",
            "traceback": traceback.format_exc(),
        }), 500


# ═══════════════════════════════════════════════════════════════
# /api/batch  — 支持 test_type 分发
# ═══════════════════════════════════════════════════════════════

@gen_bp.route("/api/batch", methods=["POST"])
def api_batch():
    """批量生成接口，通过 body.test_type 分发生成器。

    请求体:
      {
        "test_type": "default" | "smoke" | "stress",
        "requests": [
          {"type": "text", "content": "..."},
          {"type": "curl", "content": "..."}
        ]
      }
    """
    try:
        body = request.get_json(force=True)
        if not body or "requests" not in body:
            return jsonify({"success": False, "error": "缺少 requests 字段"})

        test_type = body.get("test_type", "default")
        requests_list = body["requests"]
        results = []

        for i, req in enumerate(requests_list):
            input_type = req.get("type", "text")
            content = req.get("content", "")

            r = _dispatch_generator(test_type, input_type, content)
            r["index"] = i

            # 批量也存 MySQL
            yaml_body = r.get("yaml_body", "")
            if r.get("success") and yaml_body:
                safe_name = r.get("summary", "generated")
                safe_name = re.sub(r'[\\/:*?"<>|]', '', safe_name)[:30] or "auto_yaml"
                _save_yaml_to_mysql(
                    filename=safe_name,
                    yaml_body=yaml_body,
                    input_type=input_type,
                    input_content=(content or "")[:10000],
                    summary=r.get("summary", ""),
                    model=r.get("model", ""),
                    test_type=test_type,
                )

            results.append(r)

        return jsonify({"success": True, "results": results})

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
