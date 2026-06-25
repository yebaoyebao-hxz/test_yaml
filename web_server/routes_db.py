# -*- coding: utf-8 -*-
"""数据库接口: /api/db/config, /api/db/records"""
import os, traceback
from flask import Blueprint, request, jsonify

import web_server.config as _cfg
from web_server.config import _get_db, init_db
from web_server.db import get_db_conn

db_bp = Blueprint("db", __name__)


@db_bp.route("/api/db/config", methods=["GET", "POST"])
def api_db_config():
    """查询/设置数据库路径"""
    if request.method == "GET":
        return jsonify({
            "db_path": _cfg.DB_PATH,
            "exists": os.path.exists(_cfg.DB_PATH),
        })
    else:
        body = request.get_json(force=True) or {}
        new_path = body.get("db_path", "")
        if new_path and os.path.isdir(os.path.dirname(new_path) or "."):
            _cfg.DB_PATH = new_path
            init_db()
            return jsonify({"success": True, "db_path": _cfg.DB_PATH})
        return jsonify({"success": False, "error": "无效路径"}), 400


@db_bp.route("/api/db/records", methods=["GET"])
def api_db_records():
    """查询历史记录（MySQL 两表 JOIN，失败回退 SQLite）"""
    limit = request.args.get("limit", 50, type=int)
    try:
        mysql_conn = get_db_conn()
        try:
            with mysql_conn.cursor() as cur:
                cur.execute(
                    """SELECT
                        tc.id, tc.filename, tc.summary, tc.model,
                        tc.exec_status, tc.input_type,
                        COALESCE(tc.input_content, '') as input_content,
                        COALESCE(tc.yaml_body, '') as yaml_body,
                        COALESCE(tc.keep_flag, 0) as keep_flag,
                        DATE_FORMAT(tc.created_at, '%%Y-%%m-%%d %%H:%%i:%%S') as created_at,
                        tr.id as report_id, tr.total, tr.passed, tr.failed,
                        tr.skipped, tr.broken, tr.pass_rate, tr.duration,
                        tr.report_path
                    FROM test_yaml_cases tc
                    LEFT JOIN test_allure_reports tr ON tc.id = tr.yaml_case_id
                    ORDER BY tc.id DESC
                    LIMIT %s""",
                    (limit,)
                )
                rows = cur.fetchall()
                cols = [d[0] for d in cur.description]
            records = [dict(zip(cols, row)) for row in rows]
        finally:
            mysql_conn.close()
        return jsonify({
            "success": True,
            "count": len(records),
            "source": "mysql",
            "records": records,
        })
    except Exception:
        # MySQL 不可用时回退 SQLite
        try:
            with _get_db() as conn:
                rows = conn.execute(
                    "SELECT * FROM test_cases ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
            return jsonify({
                "success": True,
                "count": len(rows),
                "source": "sqlite",
                "records": [{**dict(r), "exec_status": "done" if r["executed"] else "generated"} for r in rows],
            })
        except Exception as e2:
            return jsonify({"success": False, "error": str(e2)}), 500


@db_bp.route("/api/db/records/<int:rid>/keep", methods=["PATCH"])
def api_db_record_keep(rid):
    """切换运行记录的 keep_flag"""
    try:
        body = request.get_json(force=True) or {}
        keep = int(body.get("keep_flag", 0))
        conn = get_db_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE test_yaml_cases SET keep_flag=%s WHERE id=%s",
                    (keep, rid)
                )
                conn.commit()
            return jsonify({"success": True, "id": rid, "keep_flag": keep})
        finally:
            conn.close()
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
