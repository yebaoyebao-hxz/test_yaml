# -*- coding: utf-8 -*-
"""弹幕接口: /api/danmaku/*"""
import json, traceback, time, threading, struct, random, string
import requests as _requests
import websocket as _ws
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from utils.read_files_tools.regular_control import regular
from flask import Blueprint, request, jsonify, Response

from web_server.config import PROJECT_ROOT
from web_server.db import get_db_conn
import uuid
from threading import Event


# 动态导入 proto（避免在没有 protobuf 环境时报错）
try:
    from utils.msg.msg_pb2 import ReqUserInfo, ReqCreateRoom
    _HAS_PROTO = True
except Exception:
    _HAS_PROTO = False
    ReqUserInfo = None
    ReqCreateRoom = None

danmaku_bp = Blueprint("danmaku", __name__)
_active_stress_runs = {}  # {run_id: {"cancel": Event, "pause": Event}}

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

def _cleanup_run(run_id):
    if run_id in _active_stress_runs:
        # 确保先发 cancel 信号停掉线程
        _active_stress_runs[run_id]["cancel"].set()
    _active_stress_runs.pop(run_id, None)

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
        body_str = regular(str(body))
        try:
            body_json = json.loads(body_str)
            rsep = _requests.request(method, url, headers=headers, json=body_json, timeout=10)
        except json.JSONDecodeError:
            rsep = _requests.request(method, url, headers=headers, data=body_str, timeout=10)


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
            try:
                resp = _requests.request(method, url, headers=headers, data=body, timeout=10)
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

@danmaku_bp.route("/api/danmaku/stress/cancel", methods=["POST"])
def api_danmaku_stress_cancel():
    rid = (request.get_json(silent=True) or {}).get("run_id", "")
    if rid in _active_stress_runs:
        _active_stress_runs[rid]["cancel"].set()
        return jsonify({"success": True, "msg": "取消信号已发送"})
    return jsonify({"success": False, "error": "run_id 不存在"}), 404

@danmaku_bp.route("/api/danmaku/stress/pause", methods=["POST"])
def api_danmaku_stress_pause():
    rid = (request.get_json(silent=True) or {}).get("run_id", "")
    if rid in _active_stress_runs:
        _active_stress_runs[rid]["pause"].set()
        return jsonify({"success": True, "msg": "暂停信号已发送"})
    return jsonify({"success": False, "error": "run_id 不存在"}), 404

@danmaku_bp.route("/api/danmaku/stress/resume", methods=["POST"])
def api_danmaku_stress_resume():
    rid = (request.get_json(silent=True) or {}).get("run_id", "")
    if rid in _active_stress_runs:
        _active_stress_runs[rid]["pause"].clear()
        return jsonify({"success": True, "msg": "已恢复"})
    return jsonify({"success": False, "error": "run_id 不存在"}), 404


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

        table = _WS_PROJECTS_TABLE
        conn = get_db_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""INSERT INTO {table}
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


@danmaku_bp.route("/api/danmaku/ws-projects/<int:pid>", methods=["PUT"])
def api_danmaku_ws_update(pid):
    """更新弹幕 WS 压测项目"""
    try:
        _ensure_ws_table()
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

@danmaku_bp.route("/api/danmaku/stress/run", methods=["POST"])
def api_danmaku_stress_run():
    """接收 YAML 内容 → 保存临时文件 → 调用 stress_executor → SSE 流式返回进度"""
    import tempfile, os, json, queue, threading
    from framework.stress_executor import run_stress_suite

    body = request.get_json(force=True) or {}
    yaml_body = body.get("yaml_body", "")
    if not yaml_body:
        return jsonify({"success": False, "error": "yaml_body 为空"}), 400

    # ── 预检验：写入临时文件后立即 yaml.safe_load 验证 ──
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False,
        dir=str(PROJECT_ROOT / "data"), encoding="utf-8"
    )
    tmp.write(yaml_body)
    tmp_path = tmp.name
    tmp.close()

    import yaml as _yaml
    _valid = False
    with open(tmp_path, 'r', encoding='utf-8') as _f:
        _content = _f.read()
    try:
        _parsed = _yaml.safe_load(_content)
        if _parsed is None:
            raise ValueError("YAML 为空")
        _valid = True
    except Exception as _ye:
        first_lines = "\n".join(_content.split("\n")[:5])
        _err_msg = f"YAML 解析失败: {_ye}\n\n文件前5行:\n{first_lines}"

    run_id = uuid.uuid4().hex[:8]
    cancel_ev = Event()
    pause_ev = Event()
    _active_stress_runs[run_id] = {"cancel": cancel_ev, "pause": pause_ev}
    _q: queue.Queue = queue.Queue()
    _summary = []
    _start_t = time.time()

    def _cb(progress):
        _q.put(progress)

    def _producer():
        if not _valid:
            _q.put({"error": _err_msg})
            _q.put(None)
            return
        result = None
        try:
            result = run_stress_suite(tmp_path, callback=_cb,
                                      cancel_event=cancel_ev,
                                      pause_event=pause_ev)
            _summary.extend(result.get('results', []))
        except Exception as e:
            _q.put({"error": str(e)})
        finally:
            # ── 企微通知 ──
            if result and result.get('results'):
                try:
                    from utils.notify.wechat_send import WeChatSend
                    from utils.other_tools.models import TestMetrics
                    results = result['results']
                    passed = sum(1 for r in results if r.get('pass'))
                    total = len(results)
                    elapsed_t = time.time() - _start_t
                    lines = [
                        "## 🚀 弹幕压测完成",
                        f"> 通过：<font color=\"info\">{passed}/{total}</font>　耗时：{elapsed_t:.1f}s",
                    ]
                    for r in results:
                        m = r.get('metrics', {})
                        icon = "✅" if r.get('pass') else "❌"
                        lines.append(
                            f"{icon} {r.get('name','')}　并发:{r.get('concurrency','')}　"
                            f"TPS:{m.get('tps','')}　P99:{m.get('p99','')}ms"
                        )
                    ws = WeChatSend(TestMetrics(0, 0, 0, 0, 0, 0, "0"))
                    ws.send_markdown("\n".join(lines))
                except Exception:
                    pass
            _q.put(None)

    def event_stream():
        t = threading.Thread(target=_producer, daemon=True)
        t.start()
        yield f"data: {json.dumps({'run_id': run_id}, ensure_ascii=False)}\n\n"
        while True:
            item = _q.get()

            if item is None:
                break
            if "error" in item:
                yield f"data: {json.dumps({'done': True, 'error': item['error']}, ensure_ascii=False)}\n\n"
                break
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
        _active_stress_runs.pop(run_id, None)
        yield f"data: {json.dumps({'done': True, 'summary': _summary}, ensure_ascii=False)}\n\n"
        try:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        except Exception:
            pass

    try:
        return Response(
            event_stream(),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        )
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": f"压测异常: {e}"}), 500

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

# ═══════ 弹幕用例生成 / 执行 ═══════
@danmaku_bp.route("/api/danmaku/case/generate", methods=["POST"])
def api_danmaku_case_generate():
    """根据选中的弹幕项目 ID 列表，生成冒烟或压测 YAML"""
    try:
        body = request.get_json(force=True) or {}
        ids = body.get("ids") or []
        mode = (body.get("mode") or "smoke").strip().lower()
        normalize = bool(body.get("normalize_assert", False))
        if not isinstance(ids, list) or not ids:
            return jsonify({"success": False, "error": "ids 不能为空"}), 400
        if mode not in ("smoke", "stress"):
            return jsonify({"success": False, "error": "mode 必须是 smoke 或 stress"}), 400

        # 1. 取项目
        conn = get_db_conn()
        try:
            with conn.cursor() as cur:
                fmt = ",".join(["%s"] * len(ids))
                cur.execute(f"SELECT * FROM danmaku_endpoints WHERE id IN ({fmt})", tuple(ids))
                rows = cur.fetchall()
                cols = [c[0] for c in cur.description] if cur.description else []
        finally:
            conn.close()

        if not rows:
            return jsonify({"success": False, "error": "未找到所选接口"}), 404

        projects = [dict(r) if not isinstance(r, dict) else r for r in rows]
        # 2. 构建文本输入（按项目逐段拼接）
        import json as _json
        chunks = []
        for p in projects:
            name = p.get("endpoint_name") or p.get("project_name") or "接口" + str(p.get("id", ""))
            url = p.get("endpoint_url") or ""
            # 自动补全缺失的 scheme
            if url and not url.startswith(("http://", "https://")):
                url = "https://" + url
            method = p.get("method") or "GET"
            headers_raw = p.get("headers") or ""
            body_content = p.get("body") or ""
            chunk = "[{}]\nURL: {}\nMethod: {}\n".format(name, url, method)
            if headers_raw:
                try:
                    hdrs = _json.loads(headers_raw) if isinstance(headers_raw, str) else headers_raw
                    if isinstance(hdrs, dict) and hdrs:
                        chunk += "Headers:\n" + "\n".join("  {}: {}".format(k, v) for k, v in hdrs.items()) + "\n"
                except Exception:
                    if headers_raw.strip():
                        chunk += "Headers: {}\n".format(headers_raw)
            if body_content and method != "GET":
                chunk += "Body: {}\n".format(body_content)
            chunks.append(chunk)
        rich_input = "\n".join(chunks)
        if mode == "smoke":
            rich_input += "\n请按接口分别生成冒烟测试用例（每个接口一个 case_id），覆盖正常/异常流程，提取 token 写入 dependence_case。"
        else:
            rich_input += "\n请按接口分别生成压测测试用例（每个接口一个 case_id），使用并发/循环结构验证性能，提取 token 写入 dependence_case。"
        if normalize:
            rich_input += "\n【标准化断言】仅保留 status_code 和 code 两条断言，其余删除。"

        # 3. 调用 AI 生成器
        from utils.read_files_tools.smoke_test_case_generator import generate_smoke_case
        from utils.read_files_tools.stress_test_case_generator import generate_stress_case
        if mode == "smoke":
            ai_result = generate_smoke_case("text", rich_input, normalize_assert=normalize)
        else:
            ai_result = generate_stress_case("text", rich_input, normalize_assert=normalize)
        if not ai_result.get("success"):
            return jsonify({"success": False, "error": ai_result.get("error", "AI 生成失败")}), 500

        return jsonify({
            "success": True,
            "yaml": ai_result.get("yaml", ""),
            "summary": ai_result.get("summary") or ("danmaku_{}".format(mode)),
            "model": ai_result.get("model", ""),
            "count": len(projects),
            "mode": mode,
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": "生成失败: {}".format(e)}), 500


@danmaku_bp.route("/api/danmaku/case/run", methods=["POST"])
def api_danmaku_case_run():
    """把生成的 YAML 存到数据库 + 跑 pytest + 生成 Allure 报告（内部转发到 /api/execute）"""
    try:
        body = request.get_json(force=True) or {}
        yaml_body = body.get("yaml_body", "") or body.get("yaml", "")
        if not yaml_body:
            return jsonify({"success": False, "error": "yaml_body 为空"}), 400
        summary = body.get("summary") or "danmaku_case"
        filename = body.get("filename") or (summary.replace(" ", "_")[:30] or "danmaku_case")
        # 复用 /api/execute
        from web_server.routes_execute import api_execute
        from flask import current_app
        with current_app.test_request_context(
            "/api/execute",
            method="POST",
            json={
                "yaml_body": yaml_body,
                "filename": filename,
                "input_type": "danmaku_project",
                "input_content": body.get("input_content", ""),
                "summary": summary,
                "model": body.get("model", ""),
            },
        ):
            resp = api_execute()
            if isinstance(resp, tuple):
                data, status = resp
                payload = data.get_json() if hasattr(data, "get_json") else {}
            else:
                payload = resp.get_json() if hasattr(resp, "get_json") else {"success": False, "error": "no data"}
                status = resp.status_code if hasattr(resp, "status_code") else 200
        if status and status >= 400:
            return jsonify(payload), status
        return jsonify({"success": True, **payload})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": "执行失败: {}".format(e)}), 500


@danmaku_bp.route("/api/danmaku/case/ai-assert", methods=["POST"])
def api_danmaku_case_ai_assert():
    """对生成的 YAML 跑 AI 断言（转发到 /api/ai_assert），返回丰富日志字段供运行窗口显示"""
    import time
    t0 = time.time()
    log_lines = []
    try:
        body = request.get_json(force=True) or {}
        yaml_body = body.get("yaml_body", "") or body.get("yaml", "")
        if not yaml_body:
            return jsonify({"success": False, "error": "yaml_body 为空",
                            "log": "[ERROR] yaml_body 为空", "elapsed": 0}), 400
        normalize = bool(body.get("normalize_asserts", False))
        log_lines.append(f"[INFO] 收到 YAML 长度: {len(yaml_body)} 字节")
        log_lines.append(f"[INFO] normalize_asserts = {normalize}")
        log_lines.append("[INFO] 转发到 /api/ai_assert ...")
        from web_server.routes_ai_assert import api_ai_assert
        from flask import current_app
        with current_app.test_request_context(
            "/api/ai_assert",
            method="POST",
            json={"yaml_body": yaml_body, "normalize_asserts": normalize},
        ):
            resp = api_ai_assert()
            if isinstance(resp, tuple):
                data, status = resp
                payload = data.get_json() if hasattr(data, "get_json") else {}
            else:
                payload = resp.get_json() if hasattr(resp, "get_json") else {"success": False, "error": "no data"}
                status = resp.status_code if hasattr(resp, "status_code") else 200
        if status and status >= 400:
            elapsed = round(time.time() - t0, 2)
            err_msg = payload.get("error", f"HTTP {status}")
            log_lines.append(f"[FAIL] {err_msg}")
            return jsonify({
                "success": False, "error": err_msg,
                "log": "\n".join(log_lines), "elapsed": elapsed,
            }), status
        # 成功：把 results 展开成可读日志
        results = payload.get("results", [])
        all_passed = payload.get("success", False)
        log_lines.append(f"[INFO] 验证用例数: {len(results)}")
        passed = 0
        for r in results:
            cid = r.get("case_id", "?")
            st = r.get("status", "?")
            reason = r.get("reason", "")
            if st in ("通过", "通过", "PASS"):
                passed += 1
                log_lines.append(f"  ✓ [{cid}] {st}  {reason}")
            else:
                log_lines.append(f"  ✗ [{cid}] {st}  {reason}")
        log_lines.append(f"[{'OK' if all_passed else 'FAIL'}] 通过 {passed}/{len(results)} (用时 {round(time.time()-t0,2)}s)")
        elapsed = round(time.time() - t0, 2)
        return jsonify({
            "success": all_passed,
            "yaml": yaml_body,  # 当前后端不修改 YAML
            "results": results,
            "summary": payload.get("summary", f"{passed}/{len(results)}"),
            "assertions_count": len(results),
            "elapsed": elapsed,
            "log": "\n".join(log_lines),
            "mode": "ai_assert",
        })
    except Exception as e:
        elapsed = round(time.time() - t0, 2)
        traceback.print_exc()
        log_lines.append(f"[EXCEPTION] {type(e).__name__}: {e}")
        return jsonify({
            "success": False, "error": f"AI 断言异常: {e}",
            "log": "\n".join(log_lines), "elapsed": elapsed,
            "traceback": traceback.format_exc(),
        }), 500
