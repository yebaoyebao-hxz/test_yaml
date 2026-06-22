# -*- coding: utf-8 -*-
"""弹幕接口: /api/danmaku/*"""
import json, traceback, time, threading
import requests as _requests
from flask import Blueprint, request, jsonify

from web_server.db import get_db_conn

danmaku_bp = Blueprint("danmaku", __name__)


def _row_to_dict(row):
    """将数据库行转为 dict，headers 字段做 JSON 解析"""
    d = dict(row)
    if d.get('headers') and isinstance(d['headers'], str):
        try:
            d['headers'] = json.loads(d['headers'])
        except Exception:
            pass
    return d


def _perf_test_single(endpoint, concurrency=5, total_req=20):
    """对单个 endpoint 执行压测，返回延迟数组和错误数"""
    url = endpoint['endpoint_url']
    method = endpoint.get('method', 'GET')
    headers = {}
    if endpoint.get('headers'):
        h = endpoint['headers']
        if isinstance(h, str):
            try:
                h = json.loads(h)
            except Exception:
                pass
        if isinstance(h, dict):
            headers = h
    body = endpoint.get('body') or None

    latencies = []
    errors = 0
    lock = threading.Lock()
    idx = [0]

    def worker():
        nonlocal errors
        while True:
            with lock:
                i = idx[0]
                idx[0] += 1
            if i >= total_req:
                break
            t0 = time.time()
            try:
                resp = _requests.request(method, url, headers=headers, data=body, timeout=10)
                ms = (time.time() - t0) * 1000
                with lock:
                    latencies.append(ms)
                    if resp.status_code >= 400:
                        errors += 1
            except Exception:
                ms = (time.time() - t0) * 1000
                with lock:
                    latencies.append(ms)
                    errors += 1

    threads = []
    for _ in range(concurrency):
        t = threading.Thread(target=worker, daemon=True)
        threads.append(t)
        t.start()
    for t in threads:
        t.join()

    return latencies, errors


@danmaku_bp.route("/api/danmaku/projects", methods=["GET"])
def api_danmaku_list():
    """列出所有弹幕项目，可按分类分组"""
    try:
        category = request.args.get("category", "")
        conn = get_db_conn()
        try:
            with conn.cursor() as cur:
                if category:
                    cur.execute(
                        "SELECT * FROM danmaku_endpoints WHERE project_category=%s ORDER BY created_at DESC",
                        (category,)
                    )
                else:
                    cur.execute("SELECT * FROM danmaku_endpoints ORDER BY project_category, created_at DESC")
                rows = cur.fetchall()
            items = []
            for r in rows:
                d = _row_to_dict(r)
                d['created_at'] = d['created_at'].strftime('%Y-%m-%d %H:%M:%S') if d.get('created_at') else ''
                d['updated_at'] = d['updated_at'].strftime('%Y-%m-%d %H:%M:%S') if d.get('updated_at') else ''
                items.append(d)
            groups = {}
            for item in items:
                cat = item.get('project_category', '默认')
                groups.setdefault(cat, []).append(item)
            return jsonify({"success": True, "items": items, "groups": groups})
        finally:
            conn.close()
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@danmaku_bp.route("/api/danmaku/projects", methods=["POST"])
def api_danmaku_create():
    """新增弹幕项目"""
    try:
        body = request.get_json(force=True) or {}
        project_name = (body.get("project_name") or "").strip()
        endpoint_name = (body.get("endpoint_name") or "").strip()
        endpoint_url = (body.get("endpoint_url") or "").strip()
        if not project_name:
            return jsonify({"success": False, "error": "项目名称不能为空"}), 400
        if not endpoint_name:
            return jsonify({"success": False, "error": "接口名称不能为空"}), 400
        if not endpoint_url:
            return jsonify({"success": False, "error": "接口地址不能为空"}), 400

        category = (body.get("project_category") or "默认").strip()
        method = (body.get("method") or "GET").strip().upper()
        headers = json.dumps(body.get("headers") or {}, ensure_ascii=False)
        req_body = body.get("body") or ""

        conn = get_db_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO danmaku_endpoints
                        (project_category, project_name, endpoint_name, endpoint_url, method, headers, body)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (category, project_name, endpoint_name, endpoint_url, method, headers, req_body)
                )
                conn.commit()
                new_id = cur.lastrowid
            return jsonify({"success": True, "id": new_id, "message": "项目已添加"})
        finally:
            conn.close()
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@danmaku_bp.route("/api/danmaku/projects/<int:pid>", methods=["PUT"])
def api_danmaku_update(pid):
    """更新弹幕项目"""
    try:
        body = request.get_json(force=True) or {}
        fields = []
        values = []
        for f in ["project_category", "project_name", "endpoint_name", "endpoint_url", "method", "body"]:
            if f in body:
                fields.append(f"{f}=%s")
                values.append(body[f])
        if "headers" in body:
            fields.append("headers=%s")
            values.append(json.dumps(body["headers"], ensure_ascii=False))
        if not fields:
            return jsonify({"success": False, "error": "无更新字段"}), 400
        values.append(pid)
        conn = get_db_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(f"UPDATE danmaku_endpoints SET {', '.join(fields)} WHERE id=%s", values)
                conn.commit()
            return jsonify({"success": True, "message": "已更新"})
        finally:
            conn.close()
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@danmaku_bp.route("/api/danmaku/projects/<int:pid>", methods=["DELETE"])
def api_danmaku_delete(pid):
    """删除弹幕项目"""
    try:
        conn = get_db_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM danmaku_endpoints WHERE id=%s", (pid,))
                conn.commit()
            return jsonify({"success": True, "message": "已删除"})
        finally:
            conn.close()
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@danmaku_bp.route("/api/danmaku/perf/<int:pid>", methods=["POST"])
def api_danmaku_perf(pid):
    """对指定弹幕项目执行压测"""
    try:
        body = request.get_json(force=True) or {}
        concurrency = min(int(body.get("concurrency", 5)), 50)
        total_req = min(int(body.get("total_req", 20)), 500)

        conn = get_db_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM danmaku_endpoints WHERE id=%s", (pid,))
                row = cur.fetchone()
            if not row:
                return jsonify({"success": False, "error": "项目不存在"}), 404
            ep = _row_to_dict(row)
        finally:
            conn.close()

        latencies, errors = _perf_test_single(ep, concurrency, total_req)
        latencies.sort()
        n = len(latencies)

        def p(pct):
            if n == 0:
                return 0
            return round(latencies[min(int(n * pct / 100), n - 1)])

        elapsed = sum(latencies) / 1000 if n > 0 else 0
        return jsonify({
            "success": True,
            "total": total_req,
            "completed": n,
            "ok": n - errors,
            "errors": errors,
            "error_rate": f"{errors / total_req * 100:.1f}%" if total_req else "0%",
            "tps": round(n / elapsed, 1) if elapsed > 0 else 0,
            "latency": {
                "avg": round(sum(latencies) / n) if n > 0 else 0,
                "p50": p(50), "p90": p(90), "p95": p(95), "p99": p(99),
                "min": latencies[0] if n > 0 else 0,
                "max": latencies[-1] if n > 0 else 0,
            }
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
