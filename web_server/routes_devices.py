# -*- coding: utf-8 -*-
"""
设备管理 Blueprint
  花仙子科技 AI 测试平台 — MSAITest
"""

import csv
import io
import traceback
import datetime
from pathlib import Path

from flask import Blueprint, request, jsonify, Response

from utils.device_remote.adb_remote_ctrl import AdbRemoteCtrl
from web_server.db import get_db_conn

devices_bp = Blueprint("devices", __name__)


# ── 辅助 ─────────────────────────────────────────────



# ── 缩略图辅助 ───────────────────────────────────

# 项目根/data/screen 目录，由 adb_remote_ctrl.py 维护
_SCREEN_DIR = Path(__file__).parent.parent / "data" / "screen"


def _find_thumb(serial: str) -> str:
    """找该设备最近一张截图，返回 /data/screen/<filename> URL"""
    if not _SCREEN_DIR.exists():
        return ""
    files = list(_SCREEN_DIR.glob(f"{serial}_*.png"))
    if not files:
        return ""
    latest = max(files, key=lambda p: p.stat().st_mtime)
    return f"/data/screen/{latest.name}"


def _row_to_device(row):
    """DB 行 → 前端设备对象，字段名对齐旧版 Vue3 的 makeDevice"""
    return {
        "id":         row["id"],
        "name":       row["name"],
        "model":      row["model"],
        "serial":     row["serial"],
        "os":         row["os"],
        "resolution": row["resolution"],
        "connection": row.get("connection", "USB"),
        "group":      row["group_name"],
        "type":       row["device_type"],
        "platform":   row["platform"],
        "status":     row["status"],
        "temp":       float(row.get("temp", 0) or 0),
        "fps":        int(row.get("fps", 0) or 0),
        "cpu":        float(row.get("cpu", 0) or 0),
        "thumb":      _find_thumb(row["serial"]),
    }


# ═══════════════════════════════════════════════════
#  ① GET /api/devices — 设备列表（搜索/筛选）
# ═══════════════════════════════════════════════════

@devices_bp.route("", methods=["GET"])
def get_devices():
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        _auto_sync_adb()  # noqa
        search = request.args.get("search", "").strip()
        dtype  = request.args.get("type",   "").strip()
        status = request.args.get("status", "").strip()
        group  = request.args.get("group",  "").strip()

        sql = "SELECT * FROM devices WHERE 1=1 AND status != 'deleted'"
        params = []

        if search:
            sql += " AND (name LIKE %s OR model LIKE %s OR serial LIKE %s)"
            like = f"%{search}%"
            params += [like, like, like]
        if dtype:
            sql += " AND device_type = %s"
            params.append(dtype)
        if status:
            sql += " AND status = %s"
            params.append(status)
        if group:
            sql += " AND group_name = %s"
            params.append(group)

        sql += " ORDER BY id"

        cur.execute(sql, params)
        rows = cur.fetchall()
        devices = [_row_to_device(r) for r in rows]

        cur.close()
        conn.close()

        return jsonify({"code": 0, "data": devices, "total": len(devices)})
    except Exception:
        traceback.print_exc()
        return jsonify({"code": 1, "msg": traceback.format_exc()}), 500
    status = request.args.get("status", "").strip()


# ═══════════════════════════════════════════════════
#  ② GET /api/devices/stats — 统计卡片
# ═══════════════════════════════════════════════════

@devices_bp.route("/stats", methods=["GET"])
def get_device_stats():
    try:
        conn = get_db_conn()
        cur = conn.cursor()

        cur.execute("""
            SELECT
              COUNT(*)                                            AS all_count,
              SUM(CASE WHEN status='online'   THEN 1 ELSE 0 END)  AS online,
              SUM(CASE WHEN status='offline'  THEN 1 ELSE 0 END)  AS offline,
              SUM(CASE WHEN status='fault'    THEN 1 ELSE 0 END)  AS fault,
              SUM(CASE WHEN status='busy'     THEN 1 ELSE 0 END)  AS busy,
              SUM(CASE WHEN device_type='真机'  THEN 1 ELSE 0 END) AS real_count,
              SUM(CASE WHEN device_type='模拟器' THEN 1 ELSE 0 END) AS emu_count,
              SUM(CASE WHEN platform='Android' THEN 1 ELSE 0 END) AS android,
              SUM(CASE WHEN platform='iOS'     THEN 1 ELSE 0 END) AS ios,
              SUM(CASE WHEN platform='鸿蒙'     THEN 1 ELSE 0 END) AS harmony
            FROM devices
        """)
        row = cur.fetchone()

        all_count = int(row["all_count"]  or 0)
        online    = int(row["online"]     or 0)
        offline   = int(row["offline"]    or 0)
        fault     = int(row["fault"]      or 0)
        busy      = int(row["busy"]       or 0)
        real_cnt  = int(row["real_count"] or 0)
        emu_cnt   = int(row["emu_count"]  or 0)
        android   = int(row["android"]    or 0)
        ios       = int(row["ios"]        or 0)
        harmony   = int(row["harmony"]    or 0)

        harmony_idle = 0
        if harmony > 0:
            cur.execute(
                "SELECT COUNT(*) AS idle FROM devices "
                "WHERE platform='鸿蒙' AND status='online'"
            )
            harmony_idle = int(cur.fetchone()["idle"] or 0)

        stats = [
            {"key": "all",     "label": "全部设备",     "icon": "📱",
             "value": all_count, "sub": "总计在线设备池"},
            {"key": "online",  "label": "在线设备",     "icon": "🟢",
             "value": online,    "sub": "空闲可用"},
            {"key": "offline", "label": "离线设备",     "icon": "⚫",
             "value": offline,   "sub": "需排查"},
            {"key": "real",    "label": "真机",         "icon": "📲",
             "value": real_cnt,  "sub": "物理设备"},
            {"key": "emu",     "label": "模拟器",       "icon": "💻",
             "value": emu_cnt,   "sub": "虚拟设备"},
            {"key": "android", "label": "安卓",         "icon": "🤖",
             "value": android,   "sub": "Android 设备"},
            {"key": "ios",     "label": "iOS",          "icon": "🍎",
             "value": ios,       "sub": "Apple 设备"},
            {"key": "harmony", "label": "鸿蒙/手游闲置", "icon": "🔷",
             "value": harmony,   "sub": f"空闲: {harmony_idle}台"},
        ]

        util_rate = int(round(busy / all_count * 100)) if all_count else 0

        cur.close()
        conn.close()

        return jsonify({
            "code": 0,
            "data": {
                "stats":      stats,
                "busyCount":  busy,
                "utilRate":   util_rate,
                "faultCount": fault,
            }
        })
    except Exception:
        traceback.print_exc()
        return jsonify({"code": 1, "msg": traceback.format_exc()}), 500


# ═══════════════════════════════════════════════════
#  ③ GET /api/devices/perf/<id> — 性能曲线
# ═══════════════════════════════════════════════════

@devices_bp.route("/perf/<int:device_id>", methods=["GET"])
def get_device_perf(device_id):
    try:
        conn = get_db_conn()
        cur = conn.cursor()

        cur.execute("""
            SELECT temp, fps, cpu, recorded_at
            FROM device_perf_history
            WHERE device_id = %s
            ORDER BY recorded_at DESC
            LIMIT 60
        """, (device_id,))
        rows = cur.fetchall()
        rows.reverse()

        fps_series  = [int(r["fps"]  or 0) for r in rows]
        temp_series = [float(r["temp"] or 0) for r in rows]
        cpu_series  = [float(r["cpu"]  or 0) for r in rows]
        ts_series   = [r["recorded_at"].strftime("%H:%M:%S") for r in rows]

        cur.close()
        conn.close()

        return jsonify({
            "code": 0,
            "data": {
                "fps":        fps_series,
                "temp":       temp_series,
                "cpu":        cpu_series,
                "timestamps": ts_series,
            }
        })
    except Exception:
        traceback.print_exc()
        return jsonify({"code": 1, "msg": traceback.format_exc()}), 500


# ═══════════════════════════════════════════════════
#  ④ GET /api/devices/export — CSV 导出
# ═══════════════════════════════════════════════════

@devices_bp.route("/export", methods=["GET"])
def export_devices():
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("SELECT * FROM devices ORDER BY id")
        rows = cur.fetchall()
        devices = [_row_to_device(r) for r in rows]
        cur.close()
        conn.close()

        output = io.StringIO()
        output.write("\ufeff")
        writer = csv.writer(output)
        writer.writerow([
            "设备名", "型号", "序列号", "OS", "分辨率",
            "连接方式", "分组", "类型", "平台", "状态",
            "温度(°C)", "FPS", "CPU(%)",
        ])
        for d in devices:
            writer.writerow([
                d["name"], d["model"], d["serial"], d["os"],
                d["resolution"], d["connection"], d["group"],
                d["type"], d["platform"], d["status"],
                d["temp"], d["fps"], d["cpu"],
            ])

        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=devices.csv"},
        )
    except Exception:
        traceback.print_exc()
        return jsonify({"code": 1, "msg": traceback.format_exc()}), 500


# ═══════════════════════════════════════════════════
#  ⑤ POST /api/devices/batch — 批量运维
# ═══════════════════════════════════════════════════

OP_LABELS = {
    "restart":     "批量重启",
    "clear_cache": "批量清理游戏缓存",
    "uninstall":   "批量卸载App",
}


@devices_bp.route("/batch", methods=["POST"])
def batch_operation():
    try:
        body = request.get_json(silent=True) or {}
        operation = body.get("operation", "").strip()
        ids = body.get("ids", [])

        if not operation or operation not in OP_LABELS:
            return jsonify({"code": 1, "msg": f"未知操作: {operation}"}), 400
        if not ids or not isinstance(ids, list):
            return jsonify({"code": 1, "msg": "ids 不能为空"}), 400

        conn = get_db_conn()
        cur = conn.cursor()

        placeholders = ",".join(["%s"] * len(ids))
        cur.execute(
            f"SELECT id, name FROM devices WHERE id IN ({placeholders})",
            ids,
        )
        targets = cur.fetchall()
        if not targets:
            cur.close()
            conn.close()
            return jsonify({"code": 1, "msg": "未找到匹配设备"}), 404

        label = OP_LABELS[operation]
        names = ", ".join(d["name"] for d in targets)

        cur.close()
        conn.close()

        return jsonify({
            "code": 0,
            "msg": f"{label}指令已下发 — {names}（共{len(targets)}台）",
            "count": len(targets),
        })
    except Exception:
        traceback.print_exc()
        return jsonify({"code": 1, "msg": traceback.format_exc()}), 500


# ═══════════════════════════════════════════════════
#  ⑥ GET /api/devices/utilization — 利用率大盘
# ═══════════════════════════════════════════════════

@devices_bp.route("/utilization", methods=["GET"])
def get_utilization():
    try:
        conn = get_db_conn()
        cur = conn.cursor()

        cur.execute("""
            SELECT
              SUM(CASE WHEN group_name='手游专用组' AND status='busy' THEN 1 ELSE 0 END) AS game,
              SUM(CASE WHEN group_name!='手游专用组' AND status='busy' THEN 1 ELSE 0 END) AS app
            FROM devices
        """)
        row = cur.fetchone()
        game_busy = int(row["game"] or 0)
        app_busy  = int(row["app"]  or 0)

        pie = [
            {"name": "AI手游任务",   "value": game_busy * 60},
            {"name": "普通App自动化", "value": app_busy * 40},
        ]

        today = datetime.date.today()
        trend = []
        for i in range(6, -1, -1):
            day = today - datetime.timedelta(days=i)
            trend.append({
                "date": day.strftime("%m/%d"),
                "game": game_busy,
                "app":  app_busy,
            })

        cur.close()
        conn.close()

        return jsonify({"code": 0, "data": {"pie": pie, "trend": trend}})
    except Exception:
        traceback.print_exc()
        return jsonify({"code": 1, "msg": traceback.format_exc()}), 500
# ═══════════════════════════════════════════════════
#  ⑦ GET /api/devices/adb-list — 实时 ADB 设备发现
# ═══════════════════════════════════════════════════

@devices_bp.route("/adb-list", methods=["GET"])
def get_adb_devices():
    """获取本机 ADB 真实连接的设备列表（非数据库）"""
    try:
        data = AdbRemoteCtrl.get_all_devices()
        return jsonify({"code": 0, "data": data, "total": len(data)})
    except Exception as e:
        return jsonify({"code": 0, "data": [], "total": 0,
                        "msg": f"ADB 未连接: {e}"})

# ═══════════════════════════════════════════════════
#  ⑧ POST /api/devices/sync — ADB 设备同步到数据库
# ═══════════════════════════════════════════════════
@devices_bp.route("/sync", methods=["POST"])
def _auto_sync_adb():
    """静默同步 ADB 设备到数据库"""
    try:
        adb_devs = AdbRemoteCtrl.get_all_devices()
        conn = get_db_conn()
        cur = conn.cursor()
        for ad in adb_devs:
            cur.execute("SELECT id FROM devices WHERE serial=%s", (ad["serial"],))
            if cur.fetchall():
                cur.execute(
                    "UPDATE devices SET status='online' WHERE serial=%s",
                    (ad["serial"],),
                )
            else:
                cur.execute(
                    """INSERT INTO devices (name,model,serial,os,resolution,
                       connection,group_name,device_type,platform,status)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (ad["model"],ad["model"],ad["serial"],ad["system"],
                     ad["resolution"],ad["connect_type"],"普通测试组",
                     ad["type"],"Android","online")
                )
        conn.commit()
        cur.close(); conn.close()
    except Exception as e:
        print(f"[auto_sync] {e}")

def sync_adb_to_db():
    """将 ADB 在线设备同步到 MySQL devices 表"""
    try:
        adb_devs = AdbRemoteCtrl.get_all_devices()
        conn = get_db_conn()
        cur = conn.cursor()
        synced = 0
        for ad in adb_devs:
            cur.execute(
                "SELECT id FROM devices WHERE serial=%s", (ad["serial"],)
            )
            exist = cur.fetchone()
            if exist:
                cur.execute(
                    """UPDATE devices SET status='online', os=%s, resolution=%s,
                       model=%s, device_type=%s WHERE serial=%s""",
                    (ad["system"], ad["resolution"], ad["model"],
                     ad["type"], ad["serial"])
                )
            else:
                cur.execute(
                    """INSERT INTO devices (name,model,serial,os,resolution,
                       connection,group_name,device_type,platform,status)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (ad["model"], ad["model"], ad["serial"], ad["system"],
                     ad["resolution"], ad["connect_type"], "普通测试组",
                     ad["type"], "Android", "online")
                )
            synced += 1
        conn.commit()
        cur.close(); conn.close()
        return jsonify({"code": 0, "msg": f"已同步 {synced} 台设备"})
    except Exception as e:
        return jsonify({"code": 1, "msg": f"同步失败: {e}"}), 500