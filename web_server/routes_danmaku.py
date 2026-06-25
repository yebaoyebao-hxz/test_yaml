# -*- coding: utf-8 -*-
"""弹幕接口: /api/danmaku/*"""
import json, traceback, time, threading, struct, random, string
import re

import requests as _requests
import websocket as _ws
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from utils.read_files_tools.regular_control import regular
from flask import Blueprint, request, jsonify

from web_server.db import get_db_conn

# 动态导入 proto（避免在没有 protobuf 环境时报错）
try:
    from utils.msg.msg_pb2 import ReqUserInfo, ReqCreateRoom
    _HAS_PROTO = True
except Exception:
    _HAS_PROTO = False
    ReqUserInfo = None
    ReqCreateRoom = None

danmaku_bp = Blueprint("danmaku", __name__)

# ── WS 项目表名 ──
_WS_PROJECTS_TABLE = "danmaku_ws_projects"

def _ensure_ws_table():
    """确保 danmaku_ws_projects 表存在"""
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {_WS_PROJECTS_TABLE} (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    project_category VARCHAR(100) DEFAULT '默认',
                    project_name VARCHAR(200) NOT NULL,
                    endpoint_name VARCHAR(200) NOT NULL,
                    endpoint_url VARCHAR(500) NOT NULL,
                    method VARCHAR(10) DEFAULT 'POST',
                    headers TEXT,
                    body TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            conn.commit()
    finally:
        conn.close()


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
    if body:
        if isinstance(body, dict):
            body_str = regular(json.dumps(body))
        else:
            body_str = regular(str(body))
        try:
            body_json = json.loads(body_str)
            _has_body_json = True
        except json.JSONDecodeError:
            _has_body_json = False
    else:
        body_str = None
        body_json = None
        _has_body_json = False

    latencies = []
    errors = 0
    error_logs = []  # 收集错误详情 [{idx, status, body, error}]
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
            print("DEBUG body:", repr(body_str))
            try:
                resp = _requests.request(method, url, headers=headers,
                                         json=body_json if _has_body_json else None,
                                         data=body_str if not _has_body_json else None,
                                         timeout=10)
                ms = (time.time() - t0) * 1000
                with lock:
                    latencies.append(ms)
                    if resp.status_code >= 400:
                        errors += 1
                        if len(error_logs) < 50:
                            error_logs.append({
                                'idx': i + 1, 'status': resp.status_code,
                                'body': (resp.text or '')[:300], 'error': None
                            })
            except Exception as e:
                ms = (time.time() - t0) * 1000
                with lock:
                    latencies.append(ms)
                    errors += 1
                    if len(error_logs) < 50:
                        error_logs.append({
                            'idx': i + 1, 'status': 0,
                            'body': None, 'error': str(e)[:300]
                        })

    threads = []
    for _ in range(concurrency):
        t = threading.Thread(target=worker, daemon=True)
        threads.append(t)
        t.start()
    for t in threads:
        t.join()

    return latencies, errors, error_logs


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
        keep_flag = int(body.get("keep_flag", 0))

        conn = get_db_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO danmaku_endpoints
                        (project_category, project_name, endpoint_name, endpoint_url, method, headers, body, keep_flag)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    (category, project_name, endpoint_name, endpoint_url, method, headers, req_body, keep_flag)
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
        for f in ["project_category", "project_name", "endpoint_name", "endpoint_url", "method", "body", "keep_flag"]:
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

        latencies, errors, error_logs = _perf_test_single(ep, concurrency, total_req)
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
            "error_logs": error_logs,
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


# ═══════════════════════════════════════════════════════════════
# 弹幕长链接压测 - 项目管理
# ═══════════════════════════════════════════════════════════════

@danmaku_bp.route("/api/danmaku/ws-projects", methods=["GET"])
def api_danmaku_ws_list():
    """列出所有弹幕 WS 压测项目"""
    try:
        _ensure_ws_table()
        category = request.args.get("category", "")
        conn = get_db_conn()
        try:
            with conn.cursor() as cur:
                table = _WS_PROJECTS_TABLE
                if category:
                    cur.execute(
                        f"SELECT * FROM {table} WHERE project_category=%s ORDER BY created_at DESC",
                        (category,)
                    )
                else:
                    cur.execute(f"SELECT * FROM {table} ORDER BY project_category, created_at DESC")
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


@danmaku_bp.route("/api/danmaku/ws-projects", methods=["POST"])
def api_danmaku_ws_create():
    """新增弹幕 WS 压测项目"""
    try:
        _ensure_ws_table()
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
        method = (body.get("method") or "POST").strip().upper()
        headers = json.dumps(body.get("headers") or {}, ensure_ascii=False)
        req_body = body.get("body") or ""
        keep_flag = int(body.get("keep_flag", 0))

        table = _WS_PROJECTS_TABLE
        conn = get_db_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""INSERT INTO {table}
                        (project_category, project_name, endpoint_name, endpoint_url, method, headers, body, keep_flag)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    (category, project_name, endpoint_name, endpoint_url, method, headers, req_body, keep_flag)
                )
                conn.commit()
                new_id = cur.lastrowid
            return jsonify({"success": True, "id": new_id, "message": "项目已添加"})
        finally:
            conn.close()
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@danmaku_bp.route("/api/danmaku/ws-projects/<int:pid>", methods=["PUT"])
def api_danmaku_ws_update(pid):
    """更新弹幕 WS 压测项目"""
    try:
        _ensure_ws_table()
        body = request.get_json(force=True) or {}
        fields = []
        values = []
        for f in ["project_category", "project_name", "endpoint_name", "endpoint_url", "method", "body", "keep_flag"]:
            if f in body:
                fields.append(f"{f}=%s")
                values.append(body[f])
        if "headers" in body:
            fields.append("headers=%s")
            values.append(json.dumps(body["headers"], ensure_ascii=False))
        if not fields:
            return jsonify({"success": False, "error": "无更新字段"}), 400
        values.append(pid)
        table = _WS_PROJECTS_TABLE
        conn = get_db_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(f"UPDATE {table} SET {', '.join(fields)} WHERE id=%s", values)
                conn.commit()
            return jsonify({"success": True, "message": "已更新"})
        finally:
            conn.close()
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@danmaku_bp.route("/api/danmaku/ws-projects/<int:pid>", methods=["DELETE"])
def api_danmaku_ws_delete(pid):
    """删除弹幕 WS 压测项目"""
    try:
        _ensure_ws_table()
        table = _WS_PROJECTS_TABLE
        conn = get_db_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(f"DELETE FROM {table} WHERE id=%s", (pid,))
                conn.commit()
            return jsonify({"success": True, "message": "已删除"})
        finally:
            conn.close()
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════
# 弹幕长链接压测 - 执行
# ═══════════════════════════════════════════════════════════════

# WS 服务器固定地址
WS_HOST_DEFAULT = "192.168.1.47"
WS_PORT_DEFAULT = 94
WS_PATH_DEFAULT = "/game/ws/dsqy"


def _pack_frame(user_id, module, cmd, body=b""):
    """打包二进制帧: userId(8B LE) + module(2B LE) + cmd(2B LE) + body"""
    return struct.pack('<QHH', user_id, module, cmd) + body


def _ws_worker(login_url, method, headers, body_str, timeout_sec, results, lock):
    """单个 WS 连接的工作线程"""
    stage = {
        "login_ms": 0,
        "ws_connect_ms": 0,
        "auth_ms": 0,
        "create_room_ms": 0,
        "total_ms": 0,
        "success": False,
        "error": None,
    }
    ws = None
    t_total = time.time()


    try:
        # ── Stage 1: HTTP 登录 ──
        t0 = time.time()
        hdrs = dict(headers) if headers else {}
        if body_str:
            try:
                payload = json.loads(body_str)
            except Exception:
                payload = body_str
        else:
            payload = {"roomId": random.randint(100000, 999999)}

        resp = _requests.request(
            method, login_url, headers=hdrs,
            json=payload if isinstance(payload, dict) else None,
            data=body_str if not isinstance(payload, dict) else None,
            timeout=timeout_sec, verify=False
        )
        stage["login_ms"] = round((time.time() - t0) * 1000)

        if resp.status_code >= 400:
            stage["error"] = f"登录 HTTP {resp.status_code}"
            return

        data = resp.json()
        if isinstance(data, str):
            stage["error"] = "登录返回纯文本"
            return

        # 提取 token 和 userId
        if "data" in data and isinstance(data["data"], dict):
            inner = data["data"]
            token = inner.get("token", "")
            user_id = int(inner.get("id", 0))
        else:
            token = data.get("token", "")
            user_id = int(data.get("id", 0))

        if not token or not user_id:
            stage["error"] = f"登录未获取 token 或 userId: token={bool(token)} id={user_id}"
            return

        # ── Stage 2: WebSocket 连接 ──
        t0 = time.time()
        ws_url = f"ws://{WS_HOST_DEFAULT}:{WS_PORT_DEFAULT}{WS_PATH_DEFAULT}?token={token}"
        ws = _ws.create_connection(ws_url, timeout=timeout_sec)
        stage["ws_connect_ms"] = round((time.time() - t0) * 1000)

        room_id = random.randint(100000, 999999)

        # ── Stage 3: WS 认证 ──
        t0 = time.time()
        if _HAS_PROTO:
            msg = ReqUserInfo()
            msg.token = token
            msg.roomCode = str(room_id)
            frame = _pack_frame(user_id, module=10, cmd=1, body=msg.SerializeToString())
        else:
            # fallback: 空 body
            frame = _pack_frame(user_id, module=10, cmd=1)

        ws.send_binary(frame)

        # 收认证响应（可能先收到网关消息）
        ws.settimeout(5)
        try:
            raw = ws.recv()
            if isinstance(raw, bytes) and len(raw) >= 12:
                rid, mod, cmd_val, _ = struct.unpack_from('<QHH', raw, 0)
                if mod == 0 and cmd_val == 10001:
                    # 网关心跳/欢迎，再收一次
                    try:
                        raw = ws.recv()
                    except Exception:
                        pass
        except Exception:
            pass  # 无响应也继续

        stage["auth_ms"] = round((time.time() - t0) * 1000)

        # ── Stage 4: 创建房间 ──
        t0 = time.time()
        if _HAS_PROTO:
            msg2 = ReqCreateRoom()
            msg2.DifficultyLevel = 1
            msg2.duel = True
            msg2.pwd = ""
            frame2 = _pack_frame(user_id, module=100, cmd=50, body=msg2.SerializeToString())
        else:
            frame2 = _pack_frame(user_id, module=100, cmd=50)

        ws.send_binary(frame2)

        # 收创建房间响应
        ws.settimeout(3)
        try:
            ws.recv()
        except Exception:
            pass

        stage["create_room_ms"] = round((time.time() - t0) * 1000)
        stage["total_ms"] = round((time.time() - t_total) * 1000)
        stage["success"] = True

    except Exception as e:
        stage["error"] = str(e)[:200]
        stage["total_ms"] = round((time.time() - t_total) * 1000)
    finally:
        if ws:
            try:
                ws.close()
            except Exception:
                pass

        with lock:
            results.append(stage)


@danmaku_bp.route("/api/danmaku/ws-perf", methods=["POST"])
def api_danmaku_ws_perf():
    """
    弹幕长链接压测
    请求体: {
        "project_id": 1,
        "concurrency": 10,
        "timeout_sec": 15
    }
    """
    try:
        _ensure_ws_table()
        body = request.get_json(force=True) or {}
        project_id = int(body.get("project_id", 0))
        concurrency = min(int(body.get("concurrency", 5)), 100)
        timeout_sec = int(body.get("timeout_sec", 15))

        if not project_id:
            return jsonify({"success": False, "error": "缺少 project_id"}), 400

        # 加载项目配置
        table = _WS_PROJECTS_TABLE
        conn = get_db_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(f"SELECT * FROM {table} WHERE id=%s", (project_id,))
                row = cur.fetchone()
            if not row:
                return jsonify({"success": False, "error": "项目不存在"}), 404
            ep = _row_to_dict(row)
        finally:
            conn.close()

        login_url = ep["endpoint_url"]
        method = ep.get("method", "POST")
        headers = ep.get("headers") or {}
        body_str = ep.get("body") or ""
        body_str = regular(body_str)

        t_start = time.time()
        results = []
        lock = threading.Lock()

        threads = []
        for _ in range(concurrency):
            t = threading.Thread(
                target=_ws_worker,
                args=(login_url, method, headers, body_str, timeout_sec, results, lock),
                daemon=True
            )
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=timeout_sec + 30)

        elapsed = time.time() - t_start
        total = len(results)
        success = sum(1 for r in results if r["success"])
        failed = total - success

        # 总延迟统计
        total_lats = sorted([r["total_ms"] for r in results])
        n = len(total_lats)

        def _p(arr, pct):
            if not arr:
                return 0
            return round(arr[min(int(len(arr) * pct / 100), len(arr) - 1)])

        # 阶段延迟统计（仅成功）
        ok_results = [r for r in results if r["success"]]
        def _stage_stats(key):
            vals = sorted([r[key] for r in ok_results])
            if not vals:
                return {"avg": 0, "p50": 0, "min": 0, "max": 0}
            return {
                "avg": round(sum(vals) / len(vals)),
                "p50": _p(vals, 50),
                "min": vals[0],
                "max": vals[-1],
            }

        tps = round(total / elapsed, 1) if elapsed > 0 else 0

        return jsonify({
            "success": True,
            "total": total,
            "ok": success,
            "failed": failed,
            "tps": tps,
            "elapsed_sec": round(elapsed, 2),
            "latency": {
                "avg": round(sum(total_lats) / n) if n else 0,
                "p50": _p(total_lats, 50),
                "p90": _p(total_lats, 90),
                "p95": _p(total_lats, 95),
                "p99": _p(total_lats, 99),
                "min": total_lats[0] if n else 0,
                "max": total_lats[-1] if n else 0,
            },
            "stage_breakdown": {
                "login": _stage_stats("login_ms"),
                "ws_connect": _stage_stats("ws_connect_ms"),
                "auth": _stage_stats("auth_ms"),
                "create_room": _stage_stats("create_room_ms"),
            },
            "errors": [r["error"] for r in results if r.get("error")][:20],
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ─── AI 用例生成 ────────────────────────────────────────────
@danmaku_bp.route("/api/danmaku/ai-generate", methods=["POST"])
def api_danmaku_ai_generate():
    """选中弹幕接口 → AI 生成测试用例"""
    import sys, os, traceback as tb
    try:
        body = request.get_json(force=True) or {}
        ids = body.get("ids", [])
        if not ids or not isinstance(ids, list):
            return jsonify({"success": False, "error": "请提供接口 ID 列表"}), 400

        # 取每个 id 的端点详情
        conn = get_db_conn()
        try:
            with conn.cursor() as cur:
                placeholders = ",".join(["%s"] * len(ids))
                cur.execute(
                    f"SELECT id, endpoint_name, endpoint_url, method, headers, body FROM danmaku_endpoints WHERE id IN ({placeholders}) ORDER BY id",
                    ids)
                rows = cur.fetchall()
        finally:
            conn.close()

        if not rows:
            return jsonify({"success": False, "error": "未找到匹配的接口"}), 404

        # 延迟导入 AI 生成模块
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        case_type = body.get("case_type", "")
        if case_type == "stress":
            from utils.read_files_tools.stress_test_case_generator import generate_stress_case as _gen_func
        elif case_type == "smoke":
            from utils.read_files_tools.smoke_test_case_generator import generate_smoke_case as _gen_func
        else:
            from utils.read_files_tools.get_yaml_case import generate as _gen_func

        results = []
        for row in rows:
            eid = row["id"]
            ename = row["endpoint_name"] or "unnamed"
            try:
                # 构造文本描述给 AI
                method = (row.get("method") or "GET").upper()
                url = row.get("endpoint_url") or ""
                headers_str = row.get("headers") or "{}"
                body_str = row.get("body") or ""

                desc = f"接口名称: {ename}\n请求方法: {method}\nURL: {url}"
                if headers_str and headers_str.strip() not in ("{}", ""):
                    desc += f"\nHeaders: {headers_str}"
                if body_str and body_str.strip() not in ("{}", ""):
                    desc += f"\nBody: {body_str}"

                gen_result = _gen_func("text", desc)
                # 用例存入数据库test_yaml_cases中
                if gen_result.get("success") and gen_result.get("yaml_body"):
                    safe_name = ename or "auto_yaml"
                    safe_name = re.sub(r'[\\/:*?"<>|]', '', safe_name)
                    safe_name = safe_name[:30]
                    try:
                        conn2 = get_db_conn()
                        try:
                            with conn2.cursor() as cur2:
                                cur2.execute(
                                    """INSERT INTO test_yaml_cases
                                        (filename, yaml_body, input_type, input_content, summary, model, exec_status)
                                        VALUES (%s, %s, %s, %s, %s, %s, 'generated')""",
                                    (safe_name,
                                     gen_result["yaml_body"],
                                     "text",
                                     desc[:10000],
                                     gen_result.get("summary",""),
                                     gen_result.get("model",""))
                                )
                                # 返回自增ID，前端可以用
                                gen_result["db_id"] = cur2.lastrowid
                            conn2.commit()
                        finally:
                            conn2.close()
                    except Exception as e:
                        print(f"[WARN] 写入 test_yaml_cases 失败 ({ename}): {e}")
                        gen_result["db_save_error"] = str(e)
                results.append({
                    "id": eid,
                    "endpoint_name": ename,
                    "success": gen_result.get("success", False),
                    "yaml_body": gen_result.get("yaml_body") or gen_result.get("yaml", ""),
                    "summary": gen_result.get("summary", ""),
                    "error": gen_result.get("error") if not gen_result.get("success") else None,
                })
            except Exception as e2:
                tb.print_exc()
                results.append({
                    "id": eid,
                    "endpoint_name": ename,
                    "success": False,
                    "yaml_body": "",
                    "error": str(e2),
                })

        ok_count = sum(1 for r in results if r["success"])
        return jsonify({"success": ok_count > 0, "results": results, "total": len(results), "ok": ok_count})
    except Exception as e:
        tb.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500