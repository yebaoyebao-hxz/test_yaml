# -*- coding: utf-8 -*-
"""执行接口: /api/execute"""
import os, sys, re, traceback, subprocess, shutil, json
from pathlib import Path
from datetime import datetime as _dt

import yaml as _yaml
from flask import Blueprint, request, jsonify

from web_server.config import PROJECT_ROOT, REPORT_DIR, _get_db
from web_server.yaml_utils import trim_yaml_head, sanitize_yaml_scalars
from web_server.db import get_db_conn
from web_server.templates import CONFTEST_CODE, make_test_code

sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "utils" / "read_files_tools"))
sys.path.insert(0, str(PROJECT_ROOT / "utils" / "mysql_tool"))

exec_bp = Blueprint("execute", __name__)


def _safe_ident(raw: str, fallback: str = "auto_case") -> str:
    """清洗为合法 Python 标识符（仅保留 ASCII 字母数字下划线）"""
    s = raw.replace(" ", "_").replace("-", "_")
    s = "".join(c for c in s if c.isascii() and (c.isalnum() or c == "_"))
    s = s.strip("_")
    if not s or s[0].isdigit():
        s = "_" + s if s else ""
    return s if s else fallback


@exec_bp.route("/api/execute", methods=["POST"])
def api_execute():
    """保存 YAML → 生成测试文件 → 执行 pytest → 生成 Allure 报告"""
    try:
        body = request.get_json(force=True) or {}
        yaml_body = body.get("yaml_body", "")
        filename = body.get("filename", "auto_yaml_case")
        input_type = body.get("input_type", "")
        input_content = body.get("input_content", "")
        summary = body.get("summary", "")
        model = body.get("model", "")

        if not yaml_body:
            return jsonify({"success": False, "error": "YAML 内容为空"}), 400

        # 1. 保存 YAML 到 data/ 目录
        safe_name = filename.replace(" ", "_").replace("/", "_").replace("\\", "_")
        data_dir = PROJECT_ROOT / "data"
        data_dir.mkdir(exist_ok=True)
        yaml_path = data_dir / f"{safe_name}.yaml"
        clean_yaml = trim_yaml_head(yaml_body)
        clean_yaml = sanitize_yaml_scalars(clean_yaml)
        yaml_path.write_text(clean_yaml, encoding="utf-8")

        # 2. 存入数据库
        with _get_db() as conn:
            conn.execute(
                """INSERT INTO test_cases (filename, input_type, input_content, summary, yaml_body, model)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (safe_name, input_type, input_content[:10000], summary, yaml_body, model)
            )
            record_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        # 2.5 MySQL
        mysql_case_id = None
        try:
            mysql_conn = get_db_conn()
            try:
                with mysql_conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO test_yaml_cases
                            (filename, yaml_body, input_type, input_content, summary, model, exec_status)
                            VALUES (%s, %s, %s, %s, %s, %s, 'generated')""",
                        (safe_name, yaml_body, input_type, input_content[:10000], summary, model)
                    )
                    mysql_conn.commit()
                    mysql_case_id = cur.lastrowid
            finally:
                mysql_conn.close()
                print(f"[DEBUG] mysql_case_id = {mysql_case_id}")
        except Exception as e:
            print(f"[WARN] MySQL 写入 YAML 失败: {e}")

        # 3. 解析 YAML
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
        except Exception as _ye:
            preview = safe_yaml_body[:500]
            return jsonify({
                "success": False,
                "error": f"YAML 解析失败：{_ye}",
                "yaml_preview": preview,
                "hint": "请检查 YAML 缩进、特殊字符或重复键"
            }), 400

        common = case_data.get("case_common", {})
        case_ids = [k for k in case_data.keys() if k != "case_common"]

        feature = common.get("allureFeature", "") or common.get("allureEpic", "")
        yaml_stem = _safe_ident(feature) if feature and _safe_ident(feature) != "auto_case" else _safe_ident(safe_name)
        bare = yaml_stem.lstrip("_")
        if yaml_stem == "auto_case" or len(yaml_stem) < 2 or bare == "" or bare.isdigit():
            yaml_stem = "case_" + _dt.now().strftime("%m%d_%H%M%S")

        # 测试文件路径
        test_case_dir = PROJECT_ROOT / "test_case"
        test_case_dir.mkdir(exist_ok=True)
        file_name = f"test_{yaml_stem}.py"
        case_path_obj = test_case_dir / file_name
        case_path = str(case_path_obj)

        # 写入 conftest
        (test_case_dir / "conftest.py").write_text(CONFTEST_CODE, encoding="utf-8")

        # 写入测试文件
        test_code = make_test_code(case_ids, common, yaml_stem, file_name)
        case_path_obj.write_text(test_code, encoding="utf-8")

        _exec_env = {**os.environ, "CASE_YAML": str(yaml_path)}

        # 清理旧的 allure-results
        allure_results_dir = PROJECT_ROOT / "report" / "allure-results"
        if allure_results_dir.exists():
            shutil.rmtree(str(allure_results_dir))
        allure_results_dir.mkdir(parents=True, exist_ok=True)

        # 4. 执行 pytest
        pytest_cmd = [
            sys.executable, "-m", "pytest", case_path,
            "--alluredir", str(allure_results_dir),
            "-v"
        ]
        proc = subprocess.run(
            pytest_cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(PROJECT_ROOT),
            env=_exec_env,
        )

        # 生成 Allure HTML 报告
        allure_bin = r"E:\allure-2.41.0\bin\allure.bat"
        if not os.path.exists(allure_bin):
            allure_bin = "allure"
        allure_cmd = [
            allure_bin, "generate",
            str(allure_results_dir),
            "-o", str(REPORT_DIR),
            "--clean"
        ]
        allure_ok = False
        try:
            allure_proc = subprocess.run(allure_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
            allure_ok = ("successfully generated" in allure_proc.stdout or
                         "successfully generated" in allure_proc.stderr or
                         os.path.exists(REPORT_DIR / "index.html"))
        except (FileNotFoundError, OSError) as e:
            print(f"[WARN] allure 命令 ({allure_bin}) 不可用: {e}")

        # 5. 更新数据库执行状态
        with _get_db() as conn:
            conn.execute(
                "UPDATE test_cases SET executed=1, report_path=? WHERE id=?",
                (str(REPORT_DIR), record_id)
            )

        # 5.5 MySQL Allure 报告
        if mysql_case_id:
            summary_file = REPORT_DIR / "widgets" / "summary.json"
            print(f"[DEBUG] summary_file exists: {summary_file.exists()}, path: {summary_file}")
            if summary_file.exists():
                try:
                    with open(summary_file, "r", encoding="utf-8") as f:
                        stats = json.load(f).get("statistic", {})
                except Exception:
                    stats = {}
                try:
                    mysql_conn = get_db_conn()
                    try:
                        with mysql_conn.cursor() as cur:
                            total = stats.get("total", 0) or 1
                            cur.execute(
                                """INSERT INTO test_allure_reports
                                    (yaml_case_id, report_path, total_tests, passed, failed,
                                     skipped, broken, pass_rate, duration_ms)
                                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                                (
                                    mysql_case_id,
                                    str(REPORT_DIR),
                                    stats.get("total", 0),
                                    stats.get("passed", 0),
                                    stats.get("failed", 0),
                                    stats.get("skipped", 0),
                                    stats.get("broken", 0),
                                    round(stats.get("passed", 0) / total * 100, 2),
                                    stats.get("duration", 0),
                                )
                            )
                            mysql_conn.commit()
                    finally:
                        mysql_conn.close()
                except Exception as e:
                    print(f"[WARN] MySQL 写入报告失败: {e}")

                # exec_status UPDATE（独立 try，报告写失败不影响状态更新）
                try:
                    mysql_conn = get_db_conn()
                    try:
                        with mysql_conn.cursor() as cur:
                            cur.execute(
                                "UPDATE test_yaml_cases SET exec_status=%s WHERE id=%s",
                                ("passed" if proc.returncode == 0 else "failed", mysql_case_id),
                            )
                            mysql_conn.commit()
                    finally:
                        mysql_conn.close()
                except Exception as e:
                    print(f"[WARN] MySQL 更新状态失败: {e}")
            else:
                try:
                    mysql_conn = get_db_conn()
                    try:
                        with mysql_conn.cursor() as cur:
                            cur.execute(
                                "UPDATE test_yaml_cases SET exec_status=%s WHERE id=%s",
                                ("passed" if proc.returncode == 0 else "failed", mysql_case_id),
                            )
                            mysql_conn.commit()
                    finally:
                        mysql_conn.close()
                except Exception as e:
                    print(f"[WARN] MySQL 更新状态失败: {e}")

        # 6. 返回结果
        report_url = f"/report/index.html" if os.path.exists(REPORT_DIR / "index.html") else ""
        return jsonify({
            "success": True,
            "pytest_rc": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "yaml_file": str(yaml_path),
            "test_file": case_path,
            "report_url": report_url
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": f"执行失败: {str(e)}",
            "traceback": traceback.format_exc()
        }), 500
