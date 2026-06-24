# -*- coding: utf-8 -*-
# web_server/routes_wsperf.py  — WebSocket 长链接压测后端
import time, threading, json

from flask import Blueprint, request, jsonify
import websocket as _ws

wsperf_bp = Blueprint("wsperf", __name__)

@wsperf_bp.route("/api/perf/ws", methods=["POST"])

def api_perf_ws():
    """
    请求体:{
        "url": "ws://host/path?token=...",
        "connections": 10,       # 并发连接数
        "msgs_per_conn": 50,     # 每连接消息数
        "payload": "{...}",      # 消息体
        "timeout_sec": 10,       # 连接超时
        "ping_interval": 0       # 心跳间隔(秒)
    }
    返回: { success, total_messages, msg_ok, msg_failed, conn_ok, conn_failed,
            latency: { avg, p50, p90, p95, p99, min, max },
            conn_latency_avg, tps }
    """

    body = request.get_json(force=True) or {}
    url = body.get("url", "").strip()
    if not url:
        return jsonify({"success": False, "error": "缺少 url"}), 400

    connections = min(int(body.get("connections", 10)), 200)
    msgs_per_conn = min(int(body.get("msgs_per_conn", 50)), 5000)
    payload = body.get("payload", "")
    timeout_sec = int(body.get("timeout_sec", 10))
    ping_interval = int(body.get("ping_interval", 0))

    msg_latencies = []
    conn_latencies = []
    conn_ok = [0]
    conn_failed = [0]
    msg_ok = [0]
    msg_failed = [0]
    msg_sent = [0]
    lock = threading.Lock()
    abort = [False]

    def worker(cid):
        try:
            t0 = time.time()
            ws = _ws.create_connection(url, timeout=timeout_sec)
            conn_ms = (time.time() - t0) * 1000
            with lock:
                conn_latencies.append(conn_ms)
                conn_ok[0] += 1

            #  心跳包
            ping_timer = None
            if ping_interval > 0 and payload:
                def do_ping():
                    if not abort[0]:
                        try: ws.send(payload)
                        except:pass
                        if not abort[0]:
                            ping_timer = threading.Timer(ping_interval, do_ping)
                            ping_timer.start()
                ping_timer = threading.Timer(ping_interval, do_ping)
                ping_timer.start()

            # 发送信息 RTT
            for m in range(msgs_per_conn):
                if abort[0]:
                    break
                seq = cid * 100000 + m
                try:
                    if payload:
                        p = json.loads(payload)
                        p["_seq"] = seq
                    else:
                        p = {"_seq": seq, "ts": int(time.time()*1000)}
                except Exception:
                    p = payload or str(seq)

                t1 = time.time()
                try:
                    ws.send(json.dumps(p)if isinstance(p, dict) else str(p))
                    with lock:
                        msg_sent[0] += 1
                    # 收响应（超时3秒）
                    ws.settimeout(3)
                    resp = ws.recv()
                    rtt = (time.time() - t1) * 1000
                    with lock:
                        msg_latencies.append(rtt)
                        msg_ok[0] += 1
                except Exception:
                    with lock:
                        msg_failed[0] += 1

            if ping_timer:
                ping_timer.cancel()
            ws.close()
        except Exception:
            with lock:
                conn_failed[0] += 1

    t_start = time.time()
    threads = [threading.Thread(target=worker, args=(c,), daemon=True) for c in range(connections)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=timeout_sec + msgs_per_conn * 5 + 30)

    elapsed = time.time() - t_start
    if msg_latencies:
        msg_latencies.sort()
    n = len(msg_latencies)

    return jsonify({
        "success": True,
        "total_messages": msg_sent[0],
        "msg_ok": msg_ok[0],
        "msg_failed": msg_failed[0],
        "conn_ok": conn_ok[0],
        "conn_failed": conn_failed[0],
        "conn_latency_avg": round(sum(conn_latencies) / len(conn_latencies)) if conn_latencies else 0,
        "tps": round(msg_sent[0] / elapsed, 1) if elapsed > 0 else 0,
        "latency": {
            "avg": round(sum(msg_latencies) / n) if n else 0,
            "p50": msg_latencies[min(int(n * 0.5), n - 1)] if n else 0,
            "p90": msg_latencies[min(int(n * 0.9), n - 1)] if n else 0,
            "p95": msg_latencies[min(int(n * 0.95), n - 1)] if n else 0,
            "p99": msg_latencies[min(int(n * 0.99), n - 1)] if n else 0,
            "min": msg_latencies[0] if n else 0,
            "max": msg_latencies[-1] if n else 0,
        }
    })